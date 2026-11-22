"""Claim-specific evidence regressions replay saved material without provider calls.

These tests assert evidence attribution and traceability; they do not prescribe the
fact-check verdicts for the Trap PDF.
"""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.factcheck import assess_evidence, entity_terms_from_claim

REPORT = json.loads((Path(__file__).parent / "fixtures" / "v141_trap_report.json").read_text(encoding="utf-8"))
FINAL = json.loads((Path(__file__).parent / "fixtures" / "v142_final_claims.json").read_text(encoding="utf-8"))
CASES = json.loads((Path(__file__).parent / "fixtures" / "v14_live_audit_cases.json").read_text(encoding="utf-8"))


def replay_saved(item):
    old = item["result"]
    response = {key: copy.deepcopy(old.get(key)) for key in
                ("verdict", "explanation", "corrected_fact", "conflicting_values", "evidence_quality", "source_notes")}
    response["used_urls"] = copy.deepcopy(old.get("cited_urls") or old.get("used_urls") or [])
    with patch("app.services.factcheck.groq_json", return_value=response):
        return assess_evidence(item["claim"], copy.deepcopy(old.get("evidence", [])), "fixture", "fixture-model")


def replay_case(case):
    with patch("app.services.factcheck.groq_json", return_value=copy.deepcopy(case["model_response"])):
        return assess_evidence(case["claim"], copy.deepcopy(case["evidence"]), "fixture", "fixture-model")


def saved_claim(fragment):
    return next(x for x in REPORT["findings"] if fragment.lower() in x["claim"]["claim"].lower())


class TrapClaimEvidenceRegressions(unittest.TestCase):
    def test_water_ugc_results_are_excluded_and_explained(self):
        case = copy.deepcopy(CASES["water"])
        youtube = {"title": "User video", "url": "https://youtube.com/watch?v=water", "domain": "youtube.com",
                   "source_type": "Other — review source", "snippet": "Water formula is H2O", "relevance_score": 0.9}
        case["evidence"].append(youtube)
        case["model_response"]["used_urls"].append(youtube["url"])
        result = replay_case(case)
        excluded = [x for x in result["not_counted"] if x["reason"] == "user-generated"]
        self.assertTrue(excluded)
        self.assertTrue(all(x["url"] not in result["used_urls"] for x in excluded))
        self.assertNotIn("all supplied sources", result["explanation"].lower())

    def test_burj_evidence_keeps_828m_with_its_own_entity_row(self):
        result = replay_saved(saved_claim("Burj Khalifa"))
        values = result["source_values"]
        self.assertTrue(any("828" in x["value"] for x in values))
        self.assertFalse(any("381" in x["value"] for x in values))
        self.assertFalse(any("381" in x for x in result["conflicting_values"].split(";")))

    def test_amazon_esa_correction_is_grounded_in_retrieved_source_text(self):
        result = replay_saved({"claim": FINAL["amazon"]["claim"],
                               "result": {**FINAL["amazon"]["model_response"],
                                          "evidence": FINAL["amazon"]["evidence"]}})
        self.assertEqual(result["correction_check"], "supported")
        self.assertTrue(any(x["domain"] == "esa.int" for x in result["correction_sources"]))

    def test_world_population_exposes_current_secondary_estimates_as_unverified(self):
        result = replay_case(CASES["world_population"])
        self.assertTrue(result["correction_sources"])
        self.assertGreaterEqual(len(result["support_summary"]["independent_domains"]), 2)
        self.assertFalse(result["support_summary"]["single_source"])
        self.assertNotIn("Single-source finding", result["explanation"])
        self.assertEqual(result["correction_check"], "secondary_only")
        self.assertFalse(result["correction_selection"]["official"])
        self.assertIn("No official 2026", result["explanation"])

    def test_india_2026_population_is_secondary_when_official_data_is_not_current(self):
        result = replay_saved(saved_claim("India's population"))
        self.assertTrue(result["correction_sources"])
        self.assertTrue(all(x["source_type"] not in {"Government", "Official / institutional", "Academic"}
                            for x in result["correction_sources"]))
        self.assertEqual(result["correction_check"], "secondary_only")
        self.assertEqual(result["correction_selection"]["year"], 2026)
        self.assertIn("No official 2026", result["explanation"])
        self.assertIn("not officially verified", result["explanation"].lower())

    def test_co2_sources_remain_attributed_and_conflicts_exclude_the_pdf_value(self):
        result = replay_saved(saved_claim("concentration of carbon dioxide"))
        self.assertEqual(entity_terms_from_claim(saved_claim("concentration of carbon dioxide")["claim"]["claim"]),
                         ["carbon dioxide", "CO2", "CO₂"])
        self.assertTrue(result["used_urls"])
        self.assertTrue(all(x.get("url") for x in result["source_values"]))
        self.assertFalse(any("400" in x for x in result["conflicting_values"].split(";")))

    def test_pacific_ocean_claim_does_not_get_a_numeric_conflict(self):
        item = saved_claim("Pacific Ocean")
        result = replay_saved(item)
        self.assertEqual(entity_terms_from_claim(item["claim"]["claim"]), ["Pacific Ocean"])
        self.assertFalse(result["conflicting_values"])
        self.assertTrue(all(x.get("url") for x in result["source_notes"]))

    def test_all_trap_findings_keep_a_traceable_result_shape(self):
        for item in REPORT["findings"]:
            result = replay_saved(item)
            self.assertIn(result["verdict"], {"VERIFIED", "INACCURATE", "FALSE", "INSUFFICIENT EVIDENCE"})
            self.assertTrue(set(result["used_urls"]).issubset({e.get("url") for e in item["result"].get("evidence", [])}))
            excluded = {x["url"] for x in result["not_counted"]}
            self.assertTrue(set(result["used_urls"]).isdisjoint(excluded))


if __name__ == "__main__":
    unittest.main()
