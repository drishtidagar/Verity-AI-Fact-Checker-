import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["VERITY_CLAIM_DELAY"] = "0"
os.environ["VERITY_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "v142_pipeline.db")

from app.services.factcheck import assess_evidence

FIX = json.loads((Path(__file__).parent / "fixtures" / "v14_live_audit_cases.json").read_text(encoding="utf-8"))


class IntegratedPipelineRegressionTests(unittest.TestCase):
    def _assess(self, name):
        case = FIX[name]
        with patch("app.services.factcheck.groq_json", return_value=case["model_response"]):
            return assess_evidence(case["claim"], case["evidence"], "test-key", "test-model")

    def test_burj_official_828m_is_found_in_retrieved_entity_row(self):
        result = self._assess("burj")
        self.assertEqual(result["correction_check"], "supported")
        self.assertTrue(any("ctbuh.org" in x.get("domain", "") for x in result["correction_sources"]))
        self.assertEqual(result["conflicting_values"], "")

    def test_brainly_and_social_sources_are_separately_accounted_for(self):
        result = self._assess("skeleton")
        all_excluded = {x["domain"]: x["reason"] for x in result["retrieved_not_counted"]}
        self.assertEqual(all_excluded.get("brainly.com"), "user-generated")
        self.assertNotIn("https://brainly.com/question/46078821", result["used_urls"])

    def test_co2_uses_dated_official_measurement_and_separates_time_series(self):
        result = self._assess("co2")
        self.assertFalse(result["conflicting_values"])
        self.assertEqual(result["correction_check"], "supported")
        self.assertIn("426 ppm", result["corrected_fact"])
        self.assertTrue(any("nasa.gov" in x["domain"] for x in result["correction_sources"]))
        self.assertTrue(all(x["url"] in result["used_urls"] for x in result["correction_sources"]))

    def test_world_population_secondary_sources_are_not_called_official(self):
        result = self._assess("world_population")
        self.assertFalse(result["support_summary"]["single_source"])
        self.assertGreaterEqual(len(result["support_summary"]["independent_domains"]), 2)
        self.assertNotIn("Single-source finding", result["explanation"])
        self.assertIn("No official 2026", result["explanation"])
        self.assertIn("not officially verified", result["explanation"])

    def test_not_counted_is_canonical_and_contains_brainly(self):
        result = self._assess("skeleton")
        by_url = {x["url"]: x for x in result["not_counted"]}
        self.assertIn("https://brainly.com/question/46078821", by_url)
        self.assertEqual(by_url["https://brainly.com/question/46078821"]["reason"], "user-generated")
        self.assertEqual(len(by_url), len(result["not_counted"]))

    def test_user_generated_sources_are_in_not_counted_even_if_retrieved_not_cited(self):
        result = self._assess("skeleton")
        ugc = [x for x in result["not_counted"] if x["reason"] == "user-generated"]
        self.assertTrue(ugc)
        self.assertTrue(all(x.get("url") for x in ugc))

    def test_explanation_source_scope_is_plural_only_when_domains_are_independent(self):
        result = self._assess("world_population")
        self.assertFalse(result["support_summary"]["single_source"])
        self.assertIn("secondary sources", result["explanation"])
        self.assertNotIn("Single-source finding", result["explanation"])

    def test_water_source_scope_rewrites_unverified_plural_wording(self):
        result = self._assess("water")
        self.assertNotIn("all supplied sources", result["explanation"].lower())


if __name__ == "__main__":
    unittest.main()
