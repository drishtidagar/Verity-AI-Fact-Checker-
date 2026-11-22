"""Regression tests for the four v1.4 fixes.

HIGH-1   irrelevant official-domain sources cannot raise evidence strength (relevance >= 0.3, direct support)
HIGH-2   a corrected number must be traceable, source by source; secondary-only figures warn and are never Strong
HIGH-3   conflicting_values only reports disagreement BETWEEN supplied sources (not claim vs. corrected value)
MEDIUM-1 user-generated sources never count towards evidence strength (shown as "not counted")

Part of the tests replay the real v1.3 live audit (tests/fixtures/v13_live_audit_cases.json): the model's stored
answer is fed back through the v1.4 logic, so no API call is made.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["VERITY_CLAIM_DELAY"] = "0"
os.environ["VERITY_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "v14.db")

from app.services.factcheck import (
    MIN_RELEVANCE, assess_evidence, check_correction, evidence_rating,
    filter_conflict, split_counted, trace_correction,
)

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "v13_live_audit_cases.json").read_text(encoding="utf-8"))


def claim(text="X is 5.", ctype="other"):
    return {"claim": text, "excerpt": "", "page": 1, "claim_type": ctype}


def ev(url, stype="Other \u2014 review source", snippet="s", title="T", **kw):
    d = {"title": title, "url": url, "domain": url.split("/")[2], "source_type": stype,
         "snippet": snippet, "published_date": ""}
    d.update(kw)
    return d


def replay(name):
    """Run the stored v1.3 model answer for one real claim through the v1.4 assess_evidence()."""
    case = FIXTURE[name]
    with patch("app.services.factcheck.groq_json", return_value=case["model_response"]):
        return assess_evidence(case["claim"], case["evidence"], "k", "m"), case


def plain(text):
    """The real model writes '432\u202fppm' (narrow no-break space); compare with ordinary spaces."""
    return str(text).replace("\u202f", " ").replace("\u00a0", " ")


def reasons(result):
    return {x["url"]: x["reason"] for x in result["not_counted"]}


# ---------------------------------------------------------------------------------------------- real audit replays
class RealAuditReplayTests(unittest.TestCase):

    def test_eiffel_tower_is_no_longer_rated_strong(self):
        r, case = replay("eiffel")
        self.assertEqual(case["v13_rating"], "Strong")          # what v1.3 really produced
        self.assertEqual(r["verdict"], "INSUFFICIENT EVIDENCE")
        self.assertFalse(r["used_urls"])  # every selected source is irrelevant or user-generated
        self.assertIn("No relevant", r["downgrade_reason"])
        self.assertEqual(r["evidence_rating"], "Not rated")
        why = reasons(r)
        # ECB coin page and the CTBUH Capital Gate article: official domains, but off-topic
        self.assertTrue(why["https://www.ecb.europa.eu/euro/coins/comm/html/comm_2024.en.html"].startswith("low relevance"))
        self.assertTrue(why["https://global.ctbuh.org/embed/featured-buildings"].startswith("low relevance"))
        # Facebook x2 + Instagram
        self.assertEqual(sum(1 for v in why.values() if v == "user-generated"), 3)
        self.assertEqual(r["evidence_checks"], [])

    def test_skeleton_brainly_is_not_counted_but_the_official_source_still_is(self):
        r, case = replay("skeleton")
        self.assertEqual(r["verdict"], "VERIFIED")
        brainly = [u for u in r["cited_urls"] if "brainly.com" in u]       # v1.4.1: cited by the model ...
        self.assertEqual(len(brainly), 1)
        self.assertEqual(reasons(r)[brainly[0]], "user-generated")        # ... listed as not counted ...
        self.assertNotIn(brainly[0], r["used_urls"])                       # ... and NOT in the used-source list
        # SEER (.gov) + Lumen still count, so a good claim is not punished
        self.assertEqual(r["evidence_rating"], "Strong")
        counted_domains = {u.split("/")[2] for u in r["used_urls"]}
        self.assertIn("training.seer.cancer.gov", counted_domains)

    def test_current_official_co2_measurement_supersedes_secondary_value(self):
        r, case = replay("co2")
        self.assertEqual(r["verdict"], "INACCURATE")
        self.assertEqual(r["correction_check"], "supported")
        self.assertTrue(any(x["source_type"] == "Government" for x in r["correction_sources"]))
        self.assertIn("426 ppm", r["corrected_fact"])
        self.assertNotEqual(r["evidence_rating"], "Weak")
        self.assertIn("September 2026", r["explanation"])

    def test_differently_dated_co2_values_are_not_a_same_period_conflict(self):
        r, _ = replay("co2")
        self.assertFalse(r["conflicting_values"])
        self.assertEqual({x["date"] for x in r["source_values"]}, {"September 2026"})

    def test_world_population_outdated_claim_is_not_a_conflict(self):
        r, _ = replay("world_population")
        self.assertEqual(r["conflicting_values"], "")
        self.assertIn("7 billion", plain(r["conflict_ignored"]))
        self.assertEqual(r["verdict"], "INACCURATE")

    def test_india_figure_found_only_in_reference_sites_is_not_strong(self):
        r, case = replay("india_population")
        self.assertEqual(case["v13_rating"], "Strong")
        self.assertEqual(r["verdict"], "INACCURATE")
        self.assertNotEqual(r["evidence_rating"], "Strong")
        self.assertIn("secondary", r["correction_warning"])

    def test_definitive_verdicts_always_have_counted_sources(self):
        for name, case in FIXTURE.items():
            if name.startswith("_"):
                continue
            r, _ = replay(name)
            if r["verdict"] in {"VERIFIED", "INACCURATE", "FALSE"}:
                self.assertTrue(r["used_urls"], name)
            else:
                self.assertIn(r["verdict"], {"INSUFFICIENT EVIDENCE", "AI REVIEW FAILED", "SEARCH FAILED"}, name)


# ---------------------------------------------------------------------------------------------- HIGH-1
class IrrelevantOfficialSourceTests(unittest.TestCase):

    def rate(self, used, notes=None, verdict="FALSE", **kw):
        return evidence_rating(verdict, claim(), used, kw.get("conflict", False), kw.get("check", "n/a"), notes=notes)[0]

    def test_official_domain_below_threshold_cannot_make_a_claim_strong(self):
        self.assertEqual(MIN_RELEVANCE, 0.3)
        low = [ev("https://www.ecb.europa.eu/x", "Official / institutional", relevance_score=0.21),
               ev("https://global.ctbuh.org/y", "Official / institutional", relevance_score=0.14)]
        self.assertEqual(self.rate(low), "Weak")

    def test_same_source_with_good_relevance_is_strong(self):
        good = [ev("https://www.nasa.gov/p", "Government", relevance_score=0.77),
                ev("https://blog.example/b", relevance_score=0.8)]
        self.assertEqual(self.rate(good), "Strong")
        self.assertEqual(self.rate(good[:1]), "Moderate")      # v1.4.1: one domain alone cannot be Strong

    def test_relevance_threshold_is_inclusive_and_missing_score_is_allowed(self):
        c, nc = split_counted([ev("https://a.gov/1", "Government", relevance_score=0.3),
                               ev("https://b.gov/1", "Government", relevance_score=0.2999),
                               ev("https://c.gov/1", "Government")])
        self.assertEqual([e["url"] for e in c], ["https://a.gov/1", "https://c.gov/1"])
        self.assertEqual(nc[0]["url"], "https://b.gov/1")
        self.assertIn("0.30", nc[0]["reason"])

    def test_low_relevance_official_plus_one_good_secondary_source_is_not_boosted(self):
        used = [ev("https://www.ecb.europa.eu/x", "Official / institutional", relevance_score=0.2),
                ev("https://blog.example/b", relevance_score=0.8)]
        self.assertEqual(self.rate(used), "Weak")   # official ignored; a single secondary source stays Weak

    def test_source_noted_as_context_only_does_not_count(self):
        used = [ev("https://www.nasa.gov/p", "Government", relevance_score=0.9,
                    snippet="NASA records the measurement for the specified period."),
                ev("https://blog.example/b", snippet="The blog reports the same measurement for the specified period.")]
        ctx = [{"url": "https://www.nasa.gov/p", "says": "mentions the topic", "stance": "context"}]
        direct = [{"url": "https://www.nasa.gov/p", "says": "NASA records the measurement for the specified period.", "stance": "supports"},
                  {"url": "https://blog.example/b", "says": "The blog reports the same measurement for the specified period.", "stance": "supports"}]
        self.assertEqual(self.rate(used, notes=ctx), "Weak")
        self.assertEqual(self.rate(used, notes=direct), "Strong")
        self.assertEqual(self.rate(used, notes=None), "Strong")   # no notes supplied -> relevance rule only

    def test_source_without_any_note_does_not_count_when_notes_exist(self):
        used = [ev("https://www.nasa.gov/p", "Government", snippet="NASA reports the measurement was 426 ppm."),
                ev("https://www.noaa.gov/q", "Government", snippet="NOAA reports the monthly average was 425 ppm.")]
        notes = [{"url": "https://www.nasa.gov/p", "says": "NASA reports the measurement was 426 ppm.", "stance": "contradicts"}]
        c, nc = split_counted(used, notes)
        self.assertEqual([e["url"] for e in c], ["https://www.nasa.gov/p"])
        self.assertEqual(nc[0]["reason"], "no direct support stated")

    def test_assess_evidence_reports_why_a_source_was_not_counted(self):
        used = [ev("https://www.ecb.europa.eu/x", "Official / institutional", relevance_score=0.21)]
        with patch("app.services.factcheck.groq_json", return_value={
                "verdict": "FALSE", "evidence_quality": "HIGH", "used_urls": [used[0]["url"]]}):
            r = assess_evidence(claim("The Eiffel Tower is in Berlin."), used, "k", "m")
        self.assertEqual(r["verdict"], "INSUFFICIENT EVIDENCE")
        self.assertEqual(r["evidence_rating"], "Not rated")
        self.assertIn("No relevant", r["downgrade_reason"])
        self.assertEqual(r["not_counted"][0]["reason"], "low relevance (0.21)")


# ---------------------------------------------------------------------------------------------- HIGH-2
class CorrectionTraceTests(unittest.TestCase):
    WIKI = ev("https://en.wikipedia.org/wiki/CO2", "Reference / secondary", snippet="In 2026 CO2 reached 432 ppm")
    MIT = ev("https://climate.mit.edu/x", "Academic", snippet="NOAA announced 429 ppm in February 2026")
    NASA = ev("https://science.nasa.gov/co2", "Government", snippet="Latest value 432 parts per million")

    def test_number_only_in_wikipedia_is_not_official_backed(self):
        t = trace_correction("432 ppm (2026)", [self.WIKI, self.MIT])
        self.assertEqual(t["status"], "secondary_only")     # in a cited text, but not fully verified
        self.assertIs(t["official"], False)
        self.assertEqual([s["url"] for s in t["sources"]], [self.WIKI["url"]])

    def test_number_in_an_official_source_is_official_backed(self):
        t = trace_correction("432 ppm (2026)", [self.WIKI, self.NASA])
        self.assertIs(t["official"], True)
        self.assertEqual({s["source_type"] for s in t["sources"]}, {"Reference / secondary", "Government"})

    def test_number_found_nowhere_is_not_found(self):
        t = trace_correction("About 440 ppm", [self.WIKI, self.MIT, self.NASA])
        self.assertEqual((t["status"], t["official"], t["sources"]), ("not_found", False, []))

    def test_every_number_must_be_traceable(self):
        t = trace_correction("828 m (2,717 ft) and 163 floors",
                             [ev("https://ctbuh.org/a", "Official / institutional", snippet="828 m (2,717 ft)")])
        self.assertEqual(t["status"], "not_found")      # 163 is nowhere

    def test_numbers_may_come_from_different_official_sources(self):
        t = trace_correction("828 m and 163 floors", [
            ev("https://ctbuh.org/a", "Official / institutional", snippet="height 828 m"),
            ev("https://www.nasa.gov/b", "Government", snippet="it has 163 floors")])
        self.assertEqual((t["status"], t["official"]), ("supported", True))

    def test_nothing_numeric_means_not_applicable(self):
        self.assertEqual(trace_correction("The Eiffel Tower is in Paris.", [self.WIKI])["status"], "n/a")
        self.assertIsNone(trace_correction("", [self.WIKI])["official"])

    def test_check_correction_keeps_its_v13_behaviour(self):
        self.assertEqual(check_correction("about 432 ppm", ["NOAA announced 429 parts per million"]), "not_found")
        self.assertEqual(check_correction("About 1.48 billion", ["is 1,481,124,730"]), "supported")

    def test_secondary_only_correction_is_never_strong_even_with_an_official_citation(self):
        used = [self.MIT, self.WIKI]       # MIT (academic) is cited, but the corrected number is Wikipedia's
        for t in (claim("CO2 is 400 ppm", "statistic"),):
            rating, checks = evidence_rating("INACCURATE", t, [dict(e, published_date="2026-02-01") for e in used],
                                             False, "supported", correction_official=False)
            self.assertEqual(rating, "Moderate")
            rating_ok, _ = evidence_rating("INACCURATE", t, [dict(e, published_date="2026-02-01") for e in used],
                                           False, "supported", correction_official=True)
            self.assertEqual(rating_ok, "Strong")

    def test_user_generated_page_cannot_ground_a_correction(self):
        brainly = ev("https://brainly.com/q/1", "User-generated", snippet="it is 432 ppm")
        with patch("app.services.factcheck.groq_json", return_value={
                "verdict": "INACCURATE", "evidence_quality": "HIGH", "corrected_fact": "432 ppm",
                "used_urls": [brainly["url"], self.MIT["url"]],
                "source_notes": [{"url": self.MIT["url"], "says": "NOAA announced 429 ppm in February 2026.",
                                  "stance": "contradicts"}]}):
            r = assess_evidence(claim("CO2 is 400 ppm", "statistic"), [brainly, self.MIT], "k", "m")
        self.assertEqual(r["correction_check"], "not_found")
        self.assertIn("not found", r["correction_warning"])
        self.assertEqual(r["evidence_rating"], "Weak")


# ---------------------------------------------------------------------------------------------- HIGH-3
class ConflictFilterTests(unittest.TestCase):
    WIKI = ev("https://en.wikipedia.org/wiki/CO2", "Reference / secondary", snippet="reached 432 ppm in 2026")
    MIT = ev("https://climate.mit.edu/x", "Academic", snippet="reached 429 ppm in February 2026")

    def test_claim_versus_corrected_value_is_not_a_conflict(self):
        kept, ignored = filter_conflict("400 ppm (claim) vs 432 ppm (2026)", "CO2 is about 400 ppm",
                                        "432 ppm (2026)", [self.WIKI, self.MIT])
        self.assertEqual((kept, ignored), ("", "400 ppm (claim) vs 432 ppm (2026)"))

    def test_two_sources_with_different_values_are_a_conflict(self):
        text = "Wikipedia says 432 ppm; MIT (NOAA) says 429 ppm in February 2026"
        kept, ignored = filter_conflict(text, "CO2 is about 400 ppm", "about 430 ppm", [self.WIKI, self.MIT])
        self.assertEqual((kept, ignored), (text, ""))

    def test_values_that_sit_in_only_one_source_are_not_a_cross_source_conflict(self):
        both = ev("https://a.example/1", snippet="432 ppm and 429 ppm")
        kept, ignored = filter_conflict("432 ppm vs 429 ppm", "CO2 is 400 ppm", "", [both])
        self.assertEqual(kept, "")
        self.assertTrue(ignored)

    def test_conflicting_numbers_not_found_in_any_source_are_not_accepted(self):
        kept, _ = filter_conflict("500 ppm vs 600 ppm", "CO2 is 400 ppm", "", [self.WIKI, self.MIT])
        self.assertEqual(kept, "")

    def test_amazon_style_range_between_two_sources_is_kept(self):
        a = ev("https://en.wikipedia.org/wiki/Amazon", "Reference / secondary", snippet="6 million km2 are covered")
        b = ev("https://www.wwf.org.uk/amazon", snippet="covers an enormous 6.7 million square kilometres")
        text = "Wikipedia: 6 million km2; WWF: 6.7 million km2"
        self.assertEqual(filter_conflict(text, "Amazon covers 12 million km2", "", [a, b]), (text, ""))

    def test_empty_and_none_like_values(self):
        for v in ("", "none", "None", "n/a", None, "false"):
            self.assertEqual(filter_conflict(v, "c", "", []), ("", ""))

    def test_qualitative_conflict_without_numbers_is_kept_as_reported(self):
        text = "Source A calls it a planet, source B a dwarf planet"
        self.assertEqual(filter_conflict(text, "Pluto is a planet", "", []), (text, ""))

    def test_prompt_says_outdated_claim_is_never_a_source_conflict(self):
        captured = {}

        def fake(prompt, key, model, system, max_tokens=0):
            captured["p"] = prompt
            return {"verdict": "INSUFFICIENT EVIDENCE"}

        with patch("app.services.factcheck.groq_json", side_effect=fake):
            assess_evidence(claim(), [ev("https://a.example/1")], "k", "m")
        self.assertIn("NEVER a conflict", captured["p"])
        self.assertIn("SUPPLIED SOURCES", captured["p"])


# ---------------------------------------------------------------------------------------------- MEDIUM-1
class UserGeneratedExclusionTests(unittest.TestCase):

    def test_user_generated_sources_are_split_out_with_a_reason(self):
        c, nc = split_counted([ev("https://brainly.com/q/1", "User-generated"),
                               ev("https://www.facebook.com/p", "User-generated"),
                               ev("https://www.instagram.com/r", "User-generated"),
                               ev("https://www.nasa.gov/p", "Government")])
        self.assertEqual([e["url"] for e in c], ["https://www.nasa.gov/p"])
        self.assertEqual([x["reason"] for x in nc], ["user-generated"] * 3)

    def test_adding_user_generated_pages_cannot_raise_the_rating(self):
        single_secondary = [ev("https://blog.example/a")]
        padded = single_secondary + [ev("https://brainly.com/q/1", "User-generated"),
                                  ev("https://www.facebook.com/p", "User-generated")]
        r1 = evidence_rating("VERIFIED", claim(), single_secondary, False, "n/a")[0]
        r2 = evidence_rating("VERIFIED", claim(), padded, False, "n/a")[0]
        self.assertEqual(r1, r2)
        self.assertEqual(r1, "Weak")

    def test_only_user_generated_sources_still_downgrade_the_verdict(self):
        evs = [ev("https://brainly.com/q/1", "User-generated")]
        with patch("app.services.factcheck.groq_json", return_value={
                "verdict": "FALSE", "evidence_quality": "HIGH", "used_urls": [evs[0]["url"]]}):
            r = assess_evidence(claim("The Eiffel Tower is in Berlin."), evs, "k", "m")
        self.assertEqual(r["verdict"], "INSUFFICIENT EVIDENCE")

    def test_missing_model_confidence_is_unavailable_even_with_official_evidence(self):
        nasa = ev("https://www.nasa.gov/p", "Government", domain="www.nasa.gov",
                  snippet="NASA's official page directly states X is 5.")
        with patch("app.services.factcheck.groq_json", return_value={
                "verdict": "FALSE", "evidence_quality": "HIGH",
                "used_urls": [nasa["url"], "https://brainly.com/q/1", "https://www.facebook.com/p"],
                "source_notes": [{"url": nasa["url"], "says": "NASA's official page directly states X is 5.",
                                  "stance": "supports"}]}):
            r = assess_evidence(claim(), [nasa, ev("https://brainly.com/q/1", "User-generated"),
                                          ev("https://www.facebook.com/p", "User-generated")], "k", "m")
        self.assertIsNone(r["confidence"])
        self.assertIsNone(r["model_confidence"])
        self.assertEqual(r["used_urls"], [nasa["url"]])

    def test_results_keep_every_source_nothing_is_deleted(self):
        r, case = replay("eiffel")
        # v1.4.1: used_urls = counted sources only; the model's own selection is kept as cited_urls, and every
        # cited-but-not-counted source appears in not_counted with a reason.
        self.assertEqual(r["cited_urls"], case["model_response"]["used_urls"])
        self.assertEqual(r["used_urls"], [])
        self.assertEqual(sorted(x["url"] for x in r["not_counted"]), sorted(r["cited_urls"]))
        self.assertEqual(len(r["not_counted"]), 5)


if __name__ == "__main__":
    unittest.main()
