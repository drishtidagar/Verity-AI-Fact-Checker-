"""Regression tests for the four open v1.4.1 trap-PDF issues. Fixtures are the REAL saved report
(tests/fixtures/v141_trap_report.json, 13 claims), not synthetic data."""
import copy
import json
import unittest
from pathlib import Path

from app.services import evidence_rules as R

REPORT = json.loads((Path(__file__).parent / "fixtures" / "v141_trap_report.json").read_text(encoding="utf-8"))
F = REPORT["findings"]


def res(n):
    return copy.deepcopy(F[n - 1]["result"])


class Issue1SkeletonNotCounted(unittest.TestCase):
    def test_brainly_is_recorded_as_user_generated(self):
        r = res(5)
        self.assertNotIn("https://brainly.com/question/46078821", r["used_urls"])
        self.assertEqual(r["not_counted"], [])                      # the v1.4.1 defect, documented
        nc = {n["domain"]: n for n in R.build_not_counted(r["evidence"], r["used_urls"])}
        self.assertEqual(nc["brainly.com"]["reason"], "user-generated")
        self.assertEqual(nc["cordis.europa.eu"]["reason"], "low relevance")
        self.assertEqual(nc["en.wikipedia.org"]["reason"], "not cited by the assessment")

    def test_every_user_generated_source_in_the_report_is_recorded(self):
        found = []
        for n in range(1, 14):
            r = res(n)
            for x in R.build_not_counted(r["evidence"], r["used_urls"]):
                if x["reason"] == "user-generated":
                    found.append((n, x["domain"]))
        self.assertEqual(sorted(found), sorted([(3, "www.facebook.com"), (3, "www.instagram.com"), (3, "www.facebook.com"),
                                                (5, "brainly.com"), (11, "www.instagram.com")]))

    def test_every_retrieved_source_is_either_used_or_explained(self):
        for n in range(1, 14):
            r = res(n)
            nc = {x["url"] for x in R.build_not_counted(r["evidence"], r["used_urls"])}
            for e in r["evidence"]:
                self.assertTrue(e["url"] in r["used_urls"] or e["url"] in nc, f"claim {n}: {e['url']} unaccounted for")

    def test_ui_panel_is_separate_and_lists_the_reason(self):
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError:
            self.skipTest("Streamlit testing utilities are not installed in this test environment")
        r = res(5)
        nc = R.build_not_counted(r["evidence"], r["used_urls"])

        def script():
            import streamlit as st
            from app.components.not_counted_ui import render_not_counted
            st.markdown("SOURCES LIST")
            render_not_counted(st.session_state["nc"])

        at = AppTest.from_function(script, default_timeout=20)
        at.session_state["nc"] = nc
        at.run()
        self.assertFalse(at.exception)
        self.assertEqual(at.expander[0].label, "Not counted as evidence (3)")
        body = " ".join(m.value for m in at.markdown)
        self.assertIn("User-generated", body)
        self.assertIn("brainly.com", body)


class Issue2BurjKhalifa(unittest.TestCase):
    ENT = ["Burj Khalifa"]

    def test_old_output_was_wrongly_secondary_only(self):
        self.assertEqual(res(6)["correction_check"], "secondary_only")           # v1.4.1 defect
        self.assertFalse(res(6)["correction_values"][0]["official"])

    def test_828_m_is_confirmed_by_the_official_ctbuh_rows(self):
        r = res(6)
        m = R.correction_matches("828 m", r["evidence"], self.ENT)
        self.assertEqual(R.correction_check("828 m", r["evidence"], self.ENT), "supported")
        self.assertEqual(len(m["official"]), 2)                                   # global.ctbuh.org and www.ctbuh.org
        self.assertTrue(all(x["domain"] == "ctbuh.org" for x in m["official"]))
        self.assertTrue(all("Burj Khalifa" in x["row"] for x in m["official"]))   # matched inside Burj Khalifa's own row

    def test_focused_snippet_that_stitched_another_row_is_detected(self):
        ev = next(e for e in res(6)["evidence"] if "featured-buildings" in e["url"])
        self.assertEqual(ev["snippet"], "Burj Khalifa 381 m / 1,250 ft")           # what the model was shown
        bad = R.snippet_cross_row_numbers(ev["snippet"], ev["snippet_raw"], self.ENT)
        self.assertEqual(bad, ["381 m", "1,250 ft"])

    def test_unrelated_table_rows_are_not_conflicting_values(self):
        r = res(6)
        vals = R.entity_row_values(r["evidence"], self.ENT)
        self.assertTrue(vals)
        self.assertTrue(all(abs(v["value"] - 828) < 3 for v in vals), [v["display"] for v in vals])
        self.assertFalse(any(abs(v["value"] - 381) < 1 for v in vals))
        self.assertEqual(R.find_conflicts(vals), [])

    def test_glued_table_rows_do_not_leak_between_buildings(self):
        raw = "| | 1 | Burj Khalifa |  | 828 m / 2,717  ft | | | 2 | Canton Tower |  | 604 m / 1,982  ft | | | 3 | Ping An |  | 599.1 m |"
        ev = [{"url": "https://x.ctbuh.org/a", "source_type": "Official / institutional", "snippet_raw": raw, "snippet": ""}]
        vals = R.entity_row_values(ev, self.ENT)
        self.assertEqual([round(v["value"]) for v in vals], [828])

    def test_a_genuine_conflict_is_still_reported(self):
        ev = [{"url": "https://a.org/1", "source_type": "Other", "snippet_raw": "The Burj Khalifa is 828 m tall.", "snippet": ""},
              {"url": "https://b.org/1", "source_type": "Other", "snippet_raw": "The Burj Khalifa is 700 m tall.", "snippet": ""}]
        self.assertTrue(R.find_conflicts(R.entity_row_values(ev, self.ENT)))

    def test_subdomains_count_as_one_independent_domain(self):
        self.assertEqual(R.registrable_domain("https://global.ctbuh.org/x"), R.registrable_domain("https://www.ctbuh.org/y"))
        s = R.source_support_summary(res(6))
        self.assertEqual(s["independent_domains"], ["ctbuh.org", "matadornetwork.com"])
        self.assertFalse(s["single_source"])

    def test_units_are_normalised(self):
        q = dict((raw, v) for v, _, raw in R.parse_quantities("381 m / 1,250 ft"))
        self.assertAlmostEqual(q["381 m"], q["1,250 ft"], delta=1)


class Issue3IndiaPopulation(unittest.TestCase):
    ENT = ["India"]
    CAND = "1,476,625,576"

    def test_secondary_only_is_the_correct_label_for_this_number(self):
        r = res(9)
        m = R.correction_matches(self.CAND, r["evidence"], self.ENT)
        self.assertEqual(m["official"], [])                                       # no institutional source states it
        self.assertEqual([x["domain"] for x in m["secondary"]], ["worldometers.info"])
        self.assertEqual(R.correction_check(self.CAND, r["evidence"], self.ENT), "secondary_only")

    def test_the_only_institutional_figure_is_a_different_dated_value(self):
        c = R.choose_correction(self.CAND, res(9)["evidence"], self.ENT)
        self.assertEqual(c["mode"], "official_first")
        self.assertEqual(c["value"], "1,425,775,850")
        self.assertEqual(c["sources"][0]["date"], "April 2023")
        self.assertIn("secondary source", c["note"])
        self.assertEqual(c["secondary_estimate"]["value"], self.CAND)

    def test_matching_is_not_broken_when_an_institution_does_state_the_number(self):
        r = res(9)
        for e in r["evidence"]:
            if e["domain"] == "www.un.org":
                e["snippet_raw"] = "India's population is estimated at 1,476,625,576 people in 2026."
        self.assertEqual(R.correction_check(self.CAND, r["evidence"], self.ENT), "supported")
        self.assertEqual(R.choose_correction(self.CAND, r["evidence"], self.ENT)["mode"], "confirmed")

    def test_two_un_subdomains_are_one_institution(self):
        self.assertEqual(R.registrable_domain("https://desapublications.un.org/x"), R.registrable_domain("https://www.un.org/y"))


class Issue4WorldPopulationSingleSource(unittest.TestCase):
    ENT = ["world population", "world's population"]

    def test_single_official_domain_is_reported_as_such(self):
        r = res(8)
        s = R.source_support_summary(r)
        self.assertEqual(s["cited_pages"], 1)
        self.assertEqual(s["independent_domains"], ["census.gov"])
        self.assertEqual(s["official_domains"], ["census.gov"])
        self.assertTrue(s["single_source"])
        self.assertIn("provisional", s["note"])

    def test_correction_itself_is_confirmed_by_the_official_source(self):
        self.assertEqual(R.correction_check("8.2 billion", res(8)["evidence"], self.ENT), "supported")

    def test_plural_wording_with_one_domain_is_flagged(self):
        r = res(8)
        n = len(R.source_support_summary(r)["independent_domains"])
        self.assertIn("estimates", r["explanation"])                              # the v1.4.1 wording
        self.assertTrue(R.explanation_overstates_sources(r["explanation"], n))
        honest = "The U.S. Census Bureau projects the world population at about 8.2 billion in July 2026."
        self.assertFalse(R.explanation_overstates_sources(honest, n))

    def test_plural_wording_is_fine_when_three_domains_back_it(self):
        r = res(9)
        n = len(R.source_support_summary(r)["independent_domains"])
        self.assertEqual(n, 3)
        self.assertFalse(R.explanation_overstates_sources(r["explanation"], n))

    def test_rating_limits_state_why_it_is_not_strong(self):
        limits = R.rating_limits(res(8))
        self.assertIn("At least 2 independent, relevant, non-user-generated domains", limits)
        self.assertTrue(any("Single-source finding" in x for x in limits))
        self.assertEqual(res(8)["evidence_rating"], "Moderate")


class NoFalsePositives(unittest.TestCase):
    """Found by replaying all 13 claims: the first draft flagged ordinary prose and mis-parsed ppm."""

    def test_prose_snippets_are_never_called_stitched(self):
        for n, ent in ((8, ["world population"]), (9, ["India"])):
            for e in res(n)["evidence"]:
                self.assertEqual(R.snippet_cross_row_numbers(e["snippet"], e["snippet_raw"], ent), [], (n, e["url"]))

    def test_parts_per_million_is_parsed_like_ppm(self):
        a = R.parse_quantities("429 parts per million")[0]
        b = R.parse_quantities("429 ppm")[0]
        self.assertEqual((a[0], a[1]), (b[0], b[1]))
        self.assertEqual(a[1], "ppm")

    def test_verbs_and_singular_sources_are_not_flagged(self):
        self.assertFalse(R.explanation_overstates_sources(res(10)["explanation"], 1))   # "...source reports 429 ppm"
        self.assertFalse(R.explanation_overstates_sources("The Census Bureau estimates 8.2 billion.", 1))
        self.assertTrue(R.explanation_overstates_sources("Several sources agree.", 1))

    def test_co2_correction_is_not_regressed(self):
        r = res(10)
        ent = ["carbon dioxide", "CO2", "CO\u2082"]
        self.assertEqual(r["correction_check"], "supported")                       # what v1.4.1 reported
        self.assertEqual(R.correction_check(r["corrected_fact"], r["evidence"], ent), "supported")


if __name__ == "__main__":
    unittest.main()
