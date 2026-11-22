"""Regression tests for v1.4.1 - the five issues found in the live v1.4 audit (verity_1 (2).json).

1 HIGH-1    Strong must never be shown next to a failed checklist line (Eiffel: only 1 independent domain)
2 HIGH-2    each corrected figure is traced to the source(s) that contain it; secondary-only is "not fully verified"
3 HIGH-3    source-vs-source value differences are detected (CO2 432 vs 429); the outdated claim is never one side
4 MEDIUM-1  user-generated / not-counted sources are excluded from used_urls consistently
5 MEDIUM-3  snippets show only the sentence(s) that concern the claim (water: no Flash Point / Explosive Limit rows)

The first block replays the real v1.4 model answers (tests/fixtures/v14_live_audit_cases.json) through the new
logic with no API call.
"""
import itertools
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["VERITY_CLAIM_DELAY"] = "0"
os.environ["VERITY_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "v141.db")

from app.services.factcheck import (
    assess_evidence, detect_source_conflict, evidence_rating, extract_relevant_snippet, filter_conflict,
    focus_evidence, gather_evidence, trace_correction,
)

FIX = json.loads((Path(__file__).parent / "fixtures" / "v14_live_audit_cases.json").read_text(encoding="utf-8"))
CASES = [k for k in FIX if not k.startswith("_")]


def replay(name):
    case = FIX[name]
    with patch("app.services.factcheck.groq_json", return_value=case["model_response"]):
        return assess_evidence(case["claim"], case["evidence"], "k", "m"), case


def plain(text):
    return str(text).replace("\u202f", " ").replace("\u00a0", " ")


def claim(text="X is 5.", ctype="other"):
    return {"claim": text, "excerpt": "", "page": 1, "claim_type": ctype}


def ev(url, stype="Other \u2014 review source", snippet="s", title="T", **kw):
    d = {"title": title, "url": url, "domain": url.split("/")[2], "source_type": stype, "snippet": snippet,
         "published_date": ""}
    d.update(kw)
    return d


# =========================================================================================== 1  HIGH-1
class StrongNeedsEveryCheckTests(unittest.TestCase):

    def test_eiffel_tower_with_one_independent_domain_is_not_strong(self):
        r, case = replay("eiffel")
        self.assertEqual(case["v14_rating"], "Strong")                 # what v1.4 really displayed
        self.assertEqual(r["verdict"], "FALSE")                        # verdict itself unchanged
        self.assertEqual(r["evidence_rating"], "Moderate")
        independent_check = [c for c in r["evidence_checks"] if c["label"].startswith("At least 2")][0]
        self.assertIs(independent_check["ok"], False)

    def test_burj_two_ctbuh_subdomains_are_one_domain_so_not_strong(self):
        r, case = replay("burj")
        self.assertEqual(case["v14_rating"], "Strong")
        self.assertEqual(r["evidence_rating"], "Moderate")

    def test_two_independent_official_domains_can_still_be_strong(self):
        used = [ev("https://www.nasa.gov/a", "Government"), ev("https://www.un.org/b", "Official / institutional")]
        self.assertEqual(evidence_rating("FALSE", claim(), used, False, "n/a")[0], "Strong")

    def test_strong_is_never_returned_with_a_failed_check(self):
        """Exhaustive: every combination of source mix x conflict x correction state x claim type."""
        mixes = {
            "one official": [ev("https://www.nasa.gov/a", "Government")],
            "two official same domain": [ev("https://a.ctbuh.org/1", "Official / institutional"),
                                         ev("https://b.ctbuh.org/2", "Official / institutional")],
            "official + secondary": [ev("https://www.nasa.gov/a", "Government"), ev("https://blog.example/b")],
            "official + user-generated": [ev("https://www.nasa.gov/a", "Government"),
                                          ev("https://brainly.com/q", "User-generated")],
            "two secondary": [ev("https://x.example/1"), ev("https://y.example/2")],
            "official low relevance + secondary": [ev("https://www.nasa.gov/a", "Government", relevance_score=0.1),
                                                   ev("https://blog.example/b")],
        }
        seen_strong = 0
        for (name, used), conflict, check, official, ctype, dated in itertools.product(
                mixes.items(), (False, True), ("n/a", "supported", "secondary_only", "not_found"),
                (None, True, False), ("other", "statistic"), (False, True)):
            used = [dict(e, date_in_text="July 2026") if dated else dict(e) for e in used]
            rating, checks = evidence_rating("INACCURATE", claim("c", ctype), used, conflict, check,
                                             correction_official=official)
            if rating == "Strong":
                seen_strong += 1
                failed = [c["label"] for c in checks if c["ok"] is False]
                self.assertEqual(failed, [], (name, conflict, check, official, ctype, dated))
        self.assertGreater(seen_strong, 0)   # the test is not vacuous

    def test_checklist_and_rating_agree_on_every_replayed_claim(self):
        for name in CASES:
            r, _ = replay(name)
            if r["evidence_rating"] == "Strong":
                self.assertFalse([c for c in r["evidence_checks"] if c["ok"] is False], name)


# =========================================================================================== 2  HIGH-2
class CorrectionTracingTests(unittest.TestCase):
    WIKI = ev("https://en.wikipedia.org/wiki/CO2", "Reference / secondary", snippet="In 2026 CO2 reached 432 ppm")
    MIT = ev("https://climate.mit.edu/x", "Academic", snippet="NOAA announced 429 ppm in February 2026")

    def test_current_official_co2_measurement_replaces_secondary_number(self):
        r, _ = replay("co2")
        self.assertEqual(r["correction_check"], "supported")
        self.assertTrue(any(x["source_type"] == "Government" for x in r["correction_sources"]))
        self.assertIn("426 ppm", r["corrected_fact"])
        self.assertTrue(any("nasa.gov" in x["domain"] for x in r["correction_sources"]))
        self.assertIn("September 2026", r["explanation"])
        self.assertNotEqual(r["evidence_rating"], "Weak")

    def test_each_value_gets_its_own_sources(self):
        t = trace_correction("828 m and 163 floors", [
            ev("https://ctbuh.org/a", "Official / institutional", snippet="height 828 m"),
            ev("https://en.wikipedia.org/w", "Reference / secondary", snippet="828 m, 163 floors")])
        by_value = {v["value"]: v for v in t["values"]}
        self.assertEqual([h["domain"] for h in by_value["828"]["found_in"]], ["ctbuh.org", "en.wikipedia.org"])
        self.assertTrue(by_value["828"]["official"])
        self.assertEqual([h["domain"] for h in by_value["163"]["found_in"]], ["en.wikipedia.org"])
        self.assertFalse(by_value["163"]["official"])
        self.assertEqual(t["status"], "secondary_only")                      # one of two numbers is Wikipedia-only

    def test_all_numbers_in_official_sources_is_supported(self):
        t = trace_correction("432 ppm", [self.WIKI, ev("https://science.nasa.gov/c", "Government", snippet="432 ppm")])
        self.assertEqual((t["status"], t["official"]), ("supported", True))

    def test_not_found_is_still_not_found(self):
        self.assertEqual(trace_correction("440 ppm", [self.WIKI, self.MIT])["status"], "not_found")

    def test_india_2023_un_projection_is_not_used_as_a_2026_population_estimate(self):
        r, _ = replay("india")
        self.assertEqual(r["correction_check"], "secondary_only")
        self.assertFalse(r["correction_selection"]["official"])
        self.assertTrue(any("worldometers.info" in x["domain"] for x in r["correction_sources"]))
        self.assertNotIn("un.org", [h["domain"] for h in r["correction_sources"]])
        self.assertIn("No official 2026", r["explanation"])
        self.assertIn("not officially verified", r["explanation"])

    def test_world_population_figure_only_in_a_clock_site_is_secondary_only(self):
        r, case = replay("world_population")
        self.assertEqual(case["v14_rating"], "Weak")
        self.assertEqual(r["correction_check"], "secondary_only")
        self.assertIn("worldpopulationclock.net", [h["domain"] for h in r["correction_values"][0]["found_in"]])


# =========================================================================================== 3  HIGH-3
class SourceConflictDetectionTests(unittest.TestCase):

    def test_co2_432_vs_429_is_detected_from_the_sources_themselves(self):
        case = FIX["co2"]
        counted = [e for e in case["evidence"] if e["domain"] in ("en.wikipedia.org", "climate.mit.edu")]
        out = detect_source_conflict(case["claim"]["claim"], "432 ppm (as of 2026)", counted)
        self.assertTrue(out["conflict"])
        self.assertEqual(sorted(plain(v["value"]) for v in out["values"]), ["429", "432"])
        self.assertIn("February 2026", out["text"])               # MIT's date is part of the explanation
        self.assertIn("en.wikipedia.org", out["text"])
        self.assertNotIn("400", out["text"])                       # the outdated claim is never a side

    def test_different_measurement_dates_are_not_misreported_as_a_co2_conflict(self):
        case = json.loads(json.dumps(FIX["co2"]))
        case["model_response"]["conflicting_values"] = ""
        with patch("app.services.factcheck.groq_json", return_value=case["model_response"]):
            r = assess_evidence(case["claim"], case["evidence"], "k", "m")
        self.assertFalse(r["conflicting_values"])
        self.assertEqual({v["date"] for v in r["source_values"]}, {"September 2026"})
        self.assertTrue(any("carbon-dioxide" in url for url in r["used_urls"]))

    def test_real_model_text_that_v14_threw_away_is_now_kept(self):
        """v1.4 dropped this (it discarded the corrected value 432 and read '420' from a URL slug)."""
        case = FIX["co2"]
        text = ("Source: https://en.wikipedia.org/wiki/Carbon_dioxide_in_the_atmosphere_of_Earth \u2013 432 ppm; "
                "Source: https://climate.mit.edu/ask-mit/how-can-such-small-amount-carbon-dioxide-atmosphere-only-"
                "around-420-parts-million-cause-so \u2013 429 ppm. The difference reflects measurements at different times.")
        counted = [e for e in case["evidence"] if e["domain"] in ("en.wikipedia.org", "climate.mit.edu")]
        kept, ignored = filter_conflict(text, case["claim"]["claim"], "432 ppm (as of 2026)", counted)
        self.assertEqual((kept, ignored), (text, ""))

    def test_outdated_claim_versus_correction_is_still_not_a_conflict(self):
        wiki = ev("https://en.wikipedia.org/w", "Reference / secondary", snippet="In 2026 CO2 reached 432 ppm")
        mit = ev("https://climate.mit.edu/x", "Academic", snippet="CO2 hit 432 ppm; it passed 400 ppm in 2013")
        c = "CO2 is about 400 ppm"
        self.assertEqual(filter_conflict("400 ppm (claim) vs 432 ppm (2026)", c, "432 ppm", [wiki, mit]),
                         ("", "400 ppm (claim) vs 432 ppm (2026)"))
        out = detect_source_conflict(c, "432 ppm", [wiki, mit])    # the 400 in MIT's text is the claim's own number
        self.assertFalse(out["conflict"])

    def test_same_figure_rounded_differently_is_not_a_conflict(self):
        a = ev("https://a.example/1", snippet="India has about 1.4 billion people")
        b = ev("https://b.example/2", snippet="India has 1.43 billion people")
        self.assertFalse(detect_source_conflict("India has 1.2 billion", "approximately 1.4 billion", [a, b])["conflict"])

    def test_figures_far_from_the_corrected_value_are_other_quantities(self):
        a = ev("https://a.example/1", snippet="pre-industrial CO2 was 280 ppm; today 432 ppm")
        b = ev("https://b.example/2", snippet="CO2 is 432 ppm")
        self.assertFalse(detect_source_conflict("CO2 is 400 ppm", "432 ppm", [a, b])["conflict"])

    def test_one_source_alone_cannot_conflict(self):
        a = ev("https://a.example/1", snippet="432 ppm in May, 429 ppm in February")
        self.assertFalse(detect_source_conflict("CO2 is 400 ppm", "432 ppm", [a])["conflict"])

    def test_urls_are_not_read_as_figures(self):
        text = "see https://x.org/only-around-420-parts-million for 429 ppm vs 432 ppm"
        a = ev("https://a.example/1", snippet="432 ppm")
        b = ev("https://b.example/2", snippet="429 ppm")
        self.assertEqual(filter_conflict(text, "CO2 is 400 ppm", "432 ppm", [a, b]), (text, ""))

    def test_no_false_conflict_on_the_other_live_claims(self):
        for name in ("india", "world_population", "burj", "skeleton", "water", "eiffel"):
            r, _ = replay(name)
            self.assertEqual(r["conflicting_values"], "", name)


# =========================================================================================== 4  MEDIUM-1
class UsedSourceListTests(unittest.TestCase):

    def test_brainly_is_not_in_used_urls_but_stays_visible(self):
        r, case = replay("skeleton")
        brainly = "https://brainly.com/question/46078821"
        self.assertIn(brainly, case["model_response"]["used_urls"])      # the live v1.4 bug
        self.assertNotIn(brainly, r["used_urls"])
        self.assertIn(brainly, r["cited_urls"])                           # nothing is hidden: model's selection kept
        self.assertEqual({x["url"]: x["reason"] for x in r["not_counted"]}[brainly], "user-generated")
        self.assertEqual(len(r["used_urls"]), 2)                          # SEER + Lumen

    def test_used_urls_never_overlaps_not_counted_on_any_replayed_claim(self):
        for name in CASES:
            r, _ = replay(name)
            nc = {x["url"] for x in r["not_counted"]}
            self.assertFalse(nc & set(r["used_urls"]), name)
            self.assertTrue(set(r["used_urls"]) <= set(r["cited_urls"]), name)
            cited_nc = {x["url"] for x in r.get("cited_not_counted", [])}
            self.assertEqual(set(r["cited_urls"]), cited_nc | set(r["used_urls"]), name)
            self.assertTrue(set(r["used_urls"]).isdisjoint(nc), name)

    def test_low_relevance_and_user_generated_sources_are_all_excluded(self):
        evs = [ev("https://www.nasa.gov/a", "Government", relevance_score=0.9,
                   snippet="NASA's official measurement contradicts the claim."),
               ev("https://www.ecb.europa.eu/x", "Official / institutional", relevance_score=0.1),
               ev("https://www.facebook.com/p", "User-generated", relevance_score=0.9)]
        with patch("app.services.factcheck.groq_json", return_value={
                "verdict": "FALSE", "evidence_quality": "HIGH", "used_urls": [e["url"] for e in evs],
                "source_notes": [{"url": evs[0]["url"], "says": "NASA's official measurement contradicts the claim.",
                                  "stance": "contradicts"},
                                 {"url": evs[1]["url"], "says": "The source is low relevance.", "stance": "context"},
                                 {"url": evs[2]["url"], "says": "This is user-generated content.", "stance": "context"}]}):
            r = assess_evidence(claim("c"), evs, "k", "m")
        self.assertEqual(r["used_urls"], ["https://www.nasa.gov/a"])
        self.assertEqual({x["reason"].split(" ")[0] for x in r["not_counted"]}, {"low", "user-generated"})

    def test_verdict_resting_only_on_user_generated_pages_is_still_downgraded(self):
        evs = [ev("https://brainly.com/q/1", "User-generated")]
        with patch("app.services.factcheck.groq_json", return_value={
                "verdict": "FALSE", "evidence_quality": "HIGH", "used_urls": [evs[0]["url"]]}):
            r = assess_evidence(claim("c"), evs, "k", "m")
        self.assertEqual(r["verdict"], "INSUFFICIENT EVIDENCE")
        self.assertEqual(r["used_urls"], [])

    def test_verdicts_unchanged_on_every_replayed_claim(self):
        for name in CASES:
            r, case = replay(name)
            self.assertEqual(r["verdict"], case["model_response"]["verdict"], name)


# =========================================================================================== 5  MEDIUM-3
class SnippetExtractionTests(unittest.TestCase):
    WATER = "The chemical formula of water is H2O"

    def test_noaa_water_snippet_shows_only_the_formula(self):
        raw = FIX["water"]["evidence"][0]["snippet"]
        self.assertIn("Flash Point", raw)                                  # the live v1.4 screenshot problem
        snippet, focused = extract_relevant_snippet(raw, self.WATER)
        self.assertTrue(focused)
        self.assertEqual(snippet, "Chemical Formula: H2O")
        for junk in ("Flash Point", "Explosive", "Autoignition", "unavailable", "Melting"):
            self.assertNotIn(junk, snippet)

    def test_nist_navigation_text_is_removed(self):
        raw = FIX["water"]["evidence"][1]["snippet"]
        self.assertIn("Jump to content", raw)
        snippet, focused = extract_relevant_snippet(raw, self.WATER)
        self.assertIn("H2O", snippet)
        for junk in ("Jump to content", "Home", "Search", "FAQ", "Credits"):
            self.assertNotIn(junk, snippet)

    def test_prose_pages_yield_one_or_two_sentences(self):
        for e in FIX["water"]["evidence"][2:]:
            snippet, focused = extract_relevant_snippet(e["snippet"], self.WATER)
            self.assertTrue(focused)
            self.assertIn("H", snippet)
            self.assertLessEqual(len(snippet), 301)

    def test_flattened_table_is_cut_into_fields(self):
        flat = ("Chemical Formula: H2O Flash Point: data unavailable Lower Explosive Limit (LEL): data unavailable "
                "Autoignition Temperature: data unavailable Melting Point: 32\u00b0F")
        snippet, focused = extract_relevant_snippet(flat, self.WATER)
        self.assertEqual((snippet, focused), ("Chemical Formula: H2O", True))

    def test_label_and_value_in_separate_table_cells_are_rejoined(self):
        snippet, _ = extract_relevant_snippet("| Chemical Formula: |\n| H2O |\n| Flash Point: | n/a |", self.WATER)
        self.assertEqual(snippet, "Chemical Formula: H2O")

    def test_unicode_subscripts_match_plain_formula(self):
        snippet, focused = extract_relevant_snippet("The formula H\u2082O tells us what a molecule contains. Unrelated.", self.WATER)
        self.assertTrue(focused)
        self.assertIn("H\u2082O", snippet)

    def test_key_figures_survive_for_statistics(self):
        for name, number in (("burj", "828"), ("co2", "432"), ("co2", "429")):
            hits = [e for e in FIX[name]["evidence"]
                    if number in e["snippet"][:400] and extract_relevant_snippet(
                        e["snippet"], FIX[name]["claim"]["claim"], FIX[name]["claim"]["claim_type"])[0].count(number)]
            self.assertTrue(hits, (name, number))

    def test_nothing_matching_falls_back_and_says_so(self):
        snippet, focused = extract_relevant_snippet("Completely different words appear on this page.", "Zebra stripes", "other")
        self.assertFalse(focused)
        self.assertTrue(snippet)

    def test_snippet_is_never_longer_than_the_ui_limit(self):
        long = ("The chemical formula of water is H2O " * 40)
        snippet, _ = extract_relevant_snippet(long, self.WATER)
        self.assertLessEqual(len(snippet), 301)

    def test_gather_evidence_returns_focused_snippets_and_keeps_the_raw_text(self):
        raw = FIX["water"]["evidence"][0]
        item = dict(raw, _pool=raw["snippet"])
        with patch("app.services.factcheck.tavily_search", return_value=[item]):
            out = gather_evidence(claim(self.WATER), "q", "tk")
        self.assertEqual(out[0]["snippet"], "Chemical Formula: H2O")
        self.assertIn("Flash Point", out[0]["snippet_raw"])
        self.assertTrue(out[0]["snippet_focused"])
        self.assertNotIn("_pool", out[0])

    def test_date_hint_is_read_before_the_snippet_is_narrowed(self):
        item = dict(ev("https://climate.mit.edu/x", "Academic", snippet="Intro. In February 2026, NOAA announced 429 ppm."),
                    _pool="Intro. In February 2026, NOAA announced 429 ppm. " + "Noise. " * 30)
        with patch("app.services.factcheck.tavily_search", return_value=[item]):
            out = gather_evidence(claim("CO2 is 400 ppm", "statistic"), "q", "tk")
        self.assertEqual(out[0].get("date_in_text"), "February 2026")

    def test_focus_evidence_without_a_pool_uses_the_existing_snippet(self):
        out = focus_evidence([ev("https://a.example/1", snippet="Water has the chemical formula H2O.")], claim(self.WATER))
        self.assertEqual(out[0]["snippet"], "Water has the chemical formula H2O.")


if __name__ == "__main__":
    unittest.main()
