"""Regression tests for the v1.3 changes (backoff, source tiers, grounding, evidence rating,
authority fallback search, fail-fast on bad keys, pacing, per-claim retry, truncation warning)."""
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

os.environ["VERITY_CLAIM_DELAY"] = "0"
os.environ["VERITY_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "v13.db")

import app.services.providers as providers
from app.services import factcheck, database
from app.services.factcheck import (
    assess_evidence, check_correction, evidence_rating, extract_date_hint, gather_evidence,
    retry_failed, review_claim, run_audit, count_skipped_chunks,
)
from app.services.providers import ProviderError, source_type


def claim(text="X is 5.", ctype="statistic"):
    return {"claim": text, "excerpt": "", "page": 1, "claim_type": ctype}


def ev(url, stype="Other — review source", snippet="s", domain=None, **kw):
    d = {"title": "T", "url": url, "domain": domain or url.split("/")[2], "source_type": stype,
         "snippet": snippet, "published_date": ""}
    d.update(kw)
    return d


def resp(status, retry_after=None):
    m = MagicMock(status_code=status)
    m.headers = {"Retry-After": str(retry_after)} if retry_after is not None else {}
    return m


class BackoffTests(unittest.TestCase):
    def test_exponential_backoff_over_several_attempts(self):
        seq = [resp(429), resp(429), resp(503), resp(200)]
        with patch("app.services.providers.requests.post", side_effect=seq) as post, \
                patch("app.services.providers.time.sleep") as sleep, \
                patch("app.services.providers.random.uniform", return_value=0):
            r = providers._post("https://x.example", json={})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(post.call_count, 4)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [2.0, 4.0, 8.0])

    def test_retry_after_header_is_honoured_and_capped(self):
        with patch("app.services.providers.requests.post", side_effect=[resp(429, 20), resp(429, 9999), resp(200)]), \
                patch("app.services.providers.time.sleep") as sleep, \
                patch("app.services.providers.random.uniform", return_value=0):
            providers._post("https://x.example", json={})
        waits = [c.args[0] for c in sleep.call_args_list]
        self.assertEqual(waits[0], 20)                       # server asked for 20 s (> 2 s backoff)
        self.assertEqual(waits[1], providers.MAX_RETRY_WAIT)  # absurd Retry-After is capped

    def test_gives_up_after_retries_and_returns_last_response(self):
        with patch("app.services.providers.requests.post", return_value=resp(429)) as post, \
                patch("app.services.providers.time.sleep"):
            r = providers._post("https://x.example", retries=2, json={})
        self.assertEqual(r.status_code, 429)
        self.assertEqual(post.call_count, 3)

    def test_network_errors_are_retried_then_raised(self):
        import requests
        with patch("app.services.providers.requests.post", side_effect=requests.ConnectionError("down")) as post, \
                patch("app.services.providers.time.sleep"):
            with self.assertRaises(requests.ConnectionError):
                providers._post("https://x.example", retries=2, json={})
        self.assertEqual(post.call_count, 3)

    def test_non_retryable_status_is_not_retried(self):
        with patch("app.services.providers.requests.post", return_value=resp(401)) as post, \
                patch("app.services.providers.time.sleep") as sleep:
            providers._post("https://x.example", json={})
        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()


class SourceTierTests(unittest.TestCase):
    def test_user_generated_and_reference_tiers(self):
        self.assertEqual(source_type("https://brainly.com/question/1"), "User-generated")
        self.assertEqual(source_type("https://www.facebook.com/x/posts/1"), "User-generated")
        self.assertEqual(source_type("https://www.youtube.com/watch?v=1"), "User-generated")
        self.assertEqual(source_type("https://en.wikipedia.org/wiki/Water"), "Reference / secondary")
        self.assertEqual(source_type("https://www.nasa.gov/x"), "Government")
        self.assertEqual(source_type("https://www.un.org/en/x"), "Official / institutional")
        self.assertEqual(source_type("https://gml.noaa.gov/ccgg/trends/"), "Government")

    def test_look_alike_domains_are_not_trusted(self):
        self.assertEqual(source_type("https://nasa.gov.evil.example/x"), "Other — review source")
        self.assertEqual(source_type("https://notbrainly.com/x"), "Other — review source")


class AuthoritySearchTests(unittest.TestCase):
    def test_extra_authority_search_when_no_official_source(self):
        primary = [ev("https://blog.example/a")]
        official = [ev("https://www.nasa.gov/p", "Government")]
        with patch("app.services.factcheck.tavily_search", side_effect=[primary, official]) as t:
            out = gather_evidence(claim(), "q", "tk")
        self.assertEqual(t.call_count, 2)
        self.assertEqual(t.call_args_list[1].kwargs["include_domains"], providers.AUTHORITY_DOMAINS)
        self.assertEqual(out[0]["url"], "https://www.nasa.gov/p")     # official evidence is listed first
        self.assertEqual(out[0]["via"], "authority_search")

    def test_adds_authority_search_when_only_one_official_domain_was_found(self):
        primary = [ev("https://www.un.org/a", "Official / institutional")]
        authority = [ev("https://www.nasa.gov/p", "Government")]
        with patch("app.services.factcheck.tavily_search", side_effect=[primary, authority]) as t:
            result = gather_evidence(claim(), "q", "tk")
        self.assertEqual(t.call_count, 2)
        self.assertEqual({x["url"] for x in result}, {"https://www.un.org/a", "https://www.nasa.gov/p"})

    def test_duplicates_are_not_added_twice(self):
        a = ev("https://blog.example/a")
        with patch("app.services.factcheck.tavily_search", side_effect=[[a], [dict(a)]]):
            out = gather_evidence(claim(), "q", "tk")
        self.assertEqual(len(out), 1)

    def test_extra_search_failure_is_not_fatal_but_bad_key_is(self):
        a = ev("https://blog.example/a")
        with patch("app.services.factcheck.tavily_search", side_effect=[[a], ProviderError("Tavily", "limit", 429)]):
            self.assertEqual(len(gather_evidence(claim(), "q", "tk")), 1)
        with patch("app.services.factcheck.tavily_search", side_effect=[[a], ProviderError("Tavily", "bad key", 401)]):
            with self.assertRaises(ProviderError):
                gather_evidence(claim(), "q", "tk")


class DateHintTests(unittest.TestCase):
    def test_dates_are_read_from_text_when_no_publish_date(self):
        self.assertEqual(extract_date_hint("as of Wednesday, November 4, 2026, based on"), "November 4, 2026")
        self.assertEqual(extract_date_hint("World Population Clock (LIVE, October 2026)"), "October 2026")
        self.assertEqual(extract_date_hint("no date here", "nor here 12345"), "")

    def test_enrich_evidence_sets_date_in_text(self):
        out = factcheck.enrich_evidence([ev("https://a.example/1", snippet="Updated February 2026.")])
        self.assertEqual(out[0]["date_in_text"], "February 2026")


class CorrectionGroundingTests(unittest.TestCase):
    def test_numbers_found_across_formats_and_scales(self):
        self.assertEqual(check_correction("About 1.48 billion people", ["population is 1,481,124,730 as of 2026"]), "supported")
        self.assertEqual(check_correction("approximately 6 million square kilometres", ["6 million km2 are covered"]), "supported")
        self.assertEqual(check_correction("The Burj Khalifa is 828 m tall.", ["roof height of 828 m (2,717 ft)"]), "supported")
        self.assertEqual(check_correction("About 8.3 billion", ["stands at approximately 8.3 billion"]), "supported")

    def test_figure_absent_from_the_cited_text_is_flagged(self):
        # The CO2 audit (#2) quoted 432 ppm while the cited MIT/NASA text said 429 / 426 ppm.
        self.assertEqual(check_correction("about 432 ppm", ["NOAA announced 429 parts per million", "Latest 426ppm"]), "not_found")

    def test_years_and_non_numeric_corrections_are_not_checked(self):
        self.assertEqual(check_correction("The Eiffel Tower is in Paris, France.", ["anything"]), "n/a")
        self.assertEqual(check_correction("As of 2026 it is the dwarf planet Pluto.", ["x"]), "n/a")
        self.assertEqual(check_correction("", ["x"]), "n/a")

    def test_figure_stated_in_a_source_title_is_traced_without_inventing_a_date(self):
        evs = [ev("https://example.net/eiffel", snippet="A tower in the city.", title="Eiffel Tower height: 828 metres")]
        resp_ = {"verdict": "INACCURATE", "evidence_quality": "HIGH", "corrected_fact": "828 metres",
                 "used_urls": ["https://example.net/eiffel"],
                 "source_notes": [{"url": "https://example.net/eiffel", "says": "The title states the Eiffel Tower is 828 metres.",
                                   "stance": "contradicts"}]}
        with patch("app.services.factcheck.groq_json", return_value=resp_):
            r = assess_evidence(claim("The Eiffel Tower is 381 metres tall.", "other"), evs, "k", "m")
        self.assertEqual(r["correction_check"], "secondary_only")
        self.assertEqual(r["correction_values"][0]["found_in"][0]["url"], evs[0]["url"])
        self.assertEqual(check_correction("828 metres", [evs[0]["title"]]), "supported")

    def test_unsupported_correction_warns_and_cannot_be_strong(self):
        ev_ = [ev("https://www.nasa.gov/co2", "Government", snippet="Latest measurement 426 ppm (September 2026)")]
        resp_ = {"verdict": "INACCURATE", "evidence_quality": "HIGH", "corrected_fact": "About 432 ppm",
                 "used_urls": ["https://www.nasa.gov/co2"], "explanation": "e",
                 "source_notes": [{"url": "https://www.nasa.gov/co2", "says": "Latest measurement is 426 ppm.",
                                   "stance": "contradicts"}]}
        with patch("app.services.factcheck.groq_json", return_value=resp_):
            r = assess_evidence(claim("CO2 is about 400 ppm.", "statistic"), ev_, "k", "m")
        self.assertEqual(r["correction_check"], "not_found")
        self.assertIn("not found", r["correction_warning"])
        self.assertEqual(r["evidence_rating"], "Weak")


class EvidenceRatingTests(unittest.TestCase):
    def rate(self, verdict, used, ctype="other", conflict=False, check="n/a"):
        return evidence_rating(verdict, claim("c", ctype), used, conflict, check)[0]

    def test_replica_page_plus_q_and_a_site_is_weak(self):
        used = [ev("https://www.wonders-of-the-world.net/r"), ev("https://brainly.com/q/1", "User-generated")]
        self.assertEqual(self.rate("FALSE", used), "Weak")

    def test_official_source_without_problems_is_strong(self):
        used = [ev("https://www.nasa.gov/g", "Government"), ev("https://blog.example/b")]
        self.assertEqual(self.rate("FALSE", used), "Strong")

    def test_conflicting_values_cap_an_official_source_at_moderate(self):
        used = [ev("https://climate.mit.edu/x", "Academic", published_date="2026-02-01")]
        self.assertEqual(self.rate("INACCURATE", used, "statistic", conflict=True, check="supported"), "Moderate")

    def test_two_independent_secondary_sources_are_moderate(self):
        used = [ev("https://a.example/1"), ev("https://b.example/1")]
        self.assertEqual(self.rate("VERIFIED", used), "Moderate")
        self.assertEqual(self.rate("VERIFIED", [ev("https://a.example/1"), ev("https://a.example/2")]), "Weak")

    def test_undated_statistic_cannot_be_strong(self):
        # v1.4.1: Strong also needs 2 independent domains, so a second (non-official) domain is added here.
        used = [ev("https://www.un.org/p", "Official / institutional"), ev("https://other.example/q")]
        self.assertEqual(self.rate("INACCURATE", used, "statistic", check="supported"), "Moderate")
        used[0]["date_in_text"] = "July 2024"
        self.assertEqual(self.rate("INACCURATE", used, "statistic", check="supported"), "Strong")

    def test_insufficient_and_failed_states_are_not_rated(self):
        self.assertEqual(self.rate("INSUFFICIENT EVIDENCE", [ev("https://a.example/1")]), "Not rated")
        self.assertEqual(self.rate("AI REVIEW FAILED", []), "Not rated")


class UserGeneratedOnlyTests(unittest.TestCase):
    def test_verdict_resting_only_on_user_generated_pages_is_downgraded(self):
        evs = [ev("https://brainly.com/q/1", "User-generated", snippet="Paris")]
        with patch("app.services.factcheck.groq_json", return_value={
                "verdict": "FALSE", "evidence_quality": "HIGH", "used_urls": ["https://brainly.com/q/1"]}):
            r = assess_evidence(claim("The Eiffel Tower is in Berlin.", "other"), evs, "k", "m")
        self.assertEqual(r["verdict"], "INSUFFICIENT EVIDENCE")
        self.assertIn("user-generated", r["downgrade_reason"].lower())

    def test_mixed_support_is_not_downgraded(self):
        evs = [ev("https://brainly.com/q/1", "User-generated"),
               ev("https://www.nasa.gov/p", "Government",
                  snippet="The official NASA page says the claim is false and gives the contrary value.")]
        with patch("app.services.factcheck.groq_json", return_value={
                "verdict": "FALSE", "evidence_quality": "HIGH", "used_urls": [e["url"] for e in evs],
                "source_notes": [{"url": evs[1]["url"], "says": "The official NASA page says the claim is false.",
                                  "stance": "contradicts"}]}):
            r = assess_evidence(claim("c", "other"), evs, "k", "m")
        self.assertEqual(r["verdict"], "FALSE")


class PromptRulesTests(unittest.TestCase):
    def test_prompt_demands_correct_attribution_and_conflict_reporting(self):
        captured = {}

        def fake(prompt, key, model, system, max_tokens=0):
            captured["p"], captured["s"] = prompt, system
            return {"verdict": "INSUFFICIENT EVIDENCE"}

        with patch("app.services.factcheck.groq_json", side_effect=fake):
            assess_evidence(claim(), [ev("https://a.example/1")], "k", "m")
        self.assertIn("ATTRIBUTION RULE", captured["p"])
        self.assertIn("conflicting_values", captured["p"])
        self.assertIn("source_notes", captured["p"])
        self.assertIn("User-generated pages", captured["s"])

    def test_source_notes_only_keep_retrieved_urls(self):
        evs = [ev("https://a.example/1", snippet="Water has the chemical formula H2O.")]
        resp_ = {"verdict": "VERIFIED", "used_urls": ["https://a.example/1"], "source_notes": [
            {"url": "https://a.example/1", "says": "Water has the chemical formula H2O.", "stance": "supports"},
            {"url": "https://made-up.example", "says": "x", "stance": "supports"},
            {"url": "https://a.example/1", "says": "y", "stance": "weird"}]}
        with patch("app.services.factcheck.groq_json", return_value=resp_):
            r = assess_evidence(claim(), evs, "k", "m")
        self.assertEqual([n["stance"] for n in r["source_notes"]], ["supports", "context"])


class RunAuditBehaviourTests(unittest.TestCase):
    PDF = "sample_data/Verity_Evaluation_Trap_Sample_v2.pdf"

    def _claims(self, n=3):
        return {"claims": [{"claim": f"Fact {i} is {i}.", "excerpt": "", "page": 1, "claim_type": "other"} for i in range(n)]}

    def test_rejected_key_stops_the_audit_instead_of_failing_every_claim(self):
        with open(self.PDF, "rb") as f, patch("app.services.factcheck.groq_json", return_value=self._claims()), \
                patch("app.services.factcheck.tavily_search", side_effect=ProviderError("Tavily", "Tavily API key rejected.", 401)) as t:
            with self.assertRaises(ProviderError) as ctx:
                run_audit(f, "k", "t", "m", 5)
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(t.call_count, 1)    # no wasted calls on the remaining claims

    def test_rejected_groq_key_during_assessment_stops_too(self):
        calls = {"n": 0}

        def groq(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return self._claims()
            raise ProviderError("Groq", "Groq API key rejected.", 401)

        with open(self.PDF, "rb") as f, patch("app.services.factcheck.groq_json", side_effect=groq), \
                patch("app.services.factcheck.tavily_search", return_value=[ev("https://www.un.org/a", "Official / institutional")]):
            with self.assertRaises(ProviderError):
                run_audit(f, "k", "t", "m", 5)

    def test_pause_between_claims_but_not_after_the_last(self):
        with open(self.PDF, "rb") as f, patch("app.services.factcheck.CLAIM_DELAY_SECONDS", 1.5), \
                patch("app.services.factcheck.time.sleep") as sleep, \
                patch("app.services.factcheck.groq_json", return_value=self._claims(3)), \
                patch("app.services.factcheck.tavily_search", side_effect=ProviderError("Tavily", "x", 429)):
            run_audit(f, "k", "t", "m", 5)
        self.assertEqual(sleep.call_count, 2)

    def test_long_documents_report_skipped_sections(self):
        pages = [{"page": i, "text": "word " * 1900} for i in range(1, 12)]
        self.assertGreater(count_skipped_chunks(pages), 0)
        self.assertEqual(count_skipped_chunks([{"page": 1, "text": "short"}]), 0)

    def test_audit_result_carries_skipped_chunks(self):
        with open(self.PDF, "rb") as f, patch("app.services.factcheck.groq_json", return_value=self._claims(1)), \
                patch("app.services.factcheck.tavily_search", side_effect=ProviderError("Tavily", "x", 429)):
            audit = run_audit(f, "k", "t", "m", 5)
        self.assertEqual(audit["skipped_chunks"], 0)


class RetryFailedTests(unittest.TestCase):
    def setUp(self):
        database.init_db()

    def _findings(self):
        ok = {"claim": claim("Water is H2O.", "other"), "result": {"verdict": "VERIFIED", "used_urls": [], "evidence": []}}
        bad1 = {"claim": claim("Pluto is the ninth planet.", "other"), "result": {"verdict": "AI REVIEW FAILED", "evidence": []}}
        bad2 = {"claim": claim("Acme churn was 4.1%.", "financial"), "result": {"verdict": "SEARCH FAILED", "evidence": []}}
        return [ok, bad1, bad2]

    def test_only_failed_claims_are_rerun_and_others_are_untouched(self):
        evs = [ev("https://science.nasa.gov/p", "Government", snippet="reclassified as a dwarf planet")]
        seen = []

        def groq(prompt, *a, **k):
            seen.append(prompt)
            if "Pluto" not in prompt:
                return {"verdict": "INSUFFICIENT EVIDENCE", "confidence": 20, "used_urls": []}
            return {"verdict": "INACCURATE", "evidence_quality": "HIGH", "used_urls": [evs[0]["url"]],
                    "corrected_fact": "Pluto is a dwarf planet.",
                    "source_notes": [{"url": evs[0]["url"], "says": "Pluto has been reclassified as a dwarf planet.",
                                      "stance": "contradicts"}]}

        original = self._findings()
        with patch("app.services.factcheck.groq_json", side_effect=groq), \
                patch("app.services.factcheck.tavily_search", return_value=evs):
            merged = retry_failed(original, "k", "t", "m")
        self.assertEqual(len(seen), 2)                                   # two failed claims, two model calls
        self.assertIs(merged[0]["result"], original[0]["result"])         # completed finding preserved as-is
        self.assertEqual(merged[1]["result"]["verdict"], "INACCURATE")
        self.assertEqual(merged[2]["result"]["verdict"], "INSUFFICIENT EVIDENCE")
        self.assertEqual(original[1]["result"]["verdict"], "AI REVIEW FAILED")  # input not mutated

    def test_a_claim_that_fails_again_stays_failed_and_nothing_is_lost(self):
        with patch("app.services.factcheck.tavily_search", side_effect=ProviderError("Tavily", "limit", 429)):
            merged = retry_failed(self._findings(), "k", "t", "m")
        self.assertEqual([m["result"]["verdict"] for m in merged], ["VERIFIED", "SEARCH FAILED", "SEARCH FAILED"])

    def test_nothing_to_retry_makes_no_calls(self):
        done = [self._findings()[0]]
        with patch("app.services.factcheck.tavily_search") as t, patch("app.services.factcheck.groq_json") as g:
            self.assertEqual(retry_failed(done, "k", "t", "m"), done)
        t.assert_not_called()
        g.assert_not_called()

    def test_update_findings_recomputes_summary_and_keeps_other_fields(self):
        audit = {"page_count": 2, "claims_found": 3, "filtered_candidates": 1, "findings": self._findings()}
        aid = database.save_audit("t.pdf", audit, "s1")
        fixed = self._findings()
        fixed[1]["result"]["verdict"] = "INACCURATE"
        fixed[2]["result"]["verdict"] = "INSUFFICIENT EVIDENCE"
        database.update_findings(aid, fixed, "s1")
        row = database.get_audit(aid, "s1")
        self.assertEqual(row["summary"]["AI REVIEW FAILED"], 0)
        self.assertEqual(row["summary"]["SEARCH FAILED"], 0)
        self.assertEqual(row["summary"]["INACCURATE"], 1)
        self.assertEqual((row["filename"], row["page_count"], row["claims_found"]), ("t.pdf", 2, 3))

    def test_update_findings_cannot_touch_another_session(self):
        aid = database.save_audit("u.pdf", {"page_count": 1, "claims_found": 3, "filtered_candidates": 0,
                                            "findings": self._findings()}, "sA")
        database.update_findings(aid, [], "sB")
        self.assertEqual(len(database.get_audit(aid, "sA")["findings"]), 3)


class RetryButtonUITests(unittest.TestCase):
    def test_banner_and_retry_button_repair_only_failed_claims(self):
        os.environ["GROQ_API_KEY"], os.environ["TAVILY_API_KEY"] = "gsk_FAKE", "tvly-FAKE"
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError:
            self.skipTest("Streamlit testing utilities are not installed in this test environment")
        from pathlib import Path
        database.init_db()
        findings = [
            {"claim": claim("Water is H2O.", "other"), "result": {"verdict": "VERIFIED", "explanation": "ok", "used_urls": [], "evidence": []}},
            {"claim": claim("Pluto is the ninth planet.", "other"), "result": {"verdict": "AI REVIEW FAILED",
             "explanation": "Groq rate limit or token quota reached.", "evidence": []}}]
        aid = database.save_audit("trap.pdf", {"page_count": 1, "claims_found": 2, "filtered_candidates": 0, "findings": findings}, "sess-retry")
        evs = [ev("https://science.nasa.gov/dwarf-planets/pluto", "Government", snippet="reclassified as a dwarf planet in 2006")]
        app_path = str(Path(__file__).resolve().parents[1] / "app.py")
        with patch("app.services.factcheck.tavily_search", return_value=evs), \
                patch("app.services.factcheck.groq_json", return_value={
                    "verdict": "INACCURATE", "evidence_quality": "HIGH", "explanation": "Reclassified in 2006.",
                    "corrected_fact": "Pluto is a dwarf planet.", "used_urls": [evs[0]["url"]],
                    "source_notes": [{"url": evs[0]["url"], "says": "Pluto is reclassified as a dwarf planet.",
                                      "stance": "contradicts"}]}) as g:
            at = AppTest.from_file(app_path, default_timeout=30)
            at.session_state["session_id"] = "sess-retry"
            at.session_state["latest_audit"] = aid
            at.run()
            at.sidebar.radio[0].set_value("New audit").run()
            self.assertFalse(at.exception)
            self.assertTrue(any("could not be reviewed" in str(w.value) for w in at.warning))
            btn = [b for b in at.button if "Retry failed claims" in b.label]
            self.assertTrue(btn)
            btn[0].click().run()
            self.assertFalse(at.exception)
            self.assertEqual(g.call_count, 1)    # exactly the one failed claim
        row = database.get_audit(aid, "sess-retry")
        self.assertEqual([f["result"]["verdict"] for f in row["findings"]], ["VERIFIED", "INACCURATE"])
        self.assertFalse([b for b in at.button if "Retry failed claims" in b.label])
        text = " ".join(str(getattr(e, "value", "")) for e in list(at.markdown) + list(at.caption))
        self.assertIn("Pluto is a dwarf planet.", text)


if __name__ == "__main__":
    unittest.main()
