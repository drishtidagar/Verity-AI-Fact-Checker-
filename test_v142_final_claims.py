"""Integrated regression tests using the latest saved 13-claim live audit evidence."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["VERITY_CLAIM_DELAY"] = "0"
os.environ["VERITY_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "v142_final.db")

from app.services.factcheck import assess_evidence, entity_terms_from_claim
from app.services import evidence_rules as R

FIX = json.loads((Path(__file__).parent / "fixtures" / "v142_final_claims.json").read_text(encoding="utf-8"))


class FinalThreeClaimRegressionTests(unittest.TestCase):
    def _run(self, name):
        case = FIX[name]
        with patch("app.services.factcheck.groq_json", return_value=case["model_response"]):
            return assess_evidence(case["claim"], case["evidence"], "fixture-key", "fixture-model")

    def test_entity_extraction_keeps_subject_not_units(self):
        self.assertEqual(entity_terms_from_claim("The Burj Khalifa is 1,250 metres tall"), ["Burj Khalifa"])
        self.assertEqual(entity_terms_from_claim("The Amazon rainforest covers about 12 million square kilometres"), ["Amazon rainforest", "Amazon"])
        self.assertEqual(entity_terms_from_claim("The world's population is approximately 7 billion people"),
                         ["world population", "world's population", "global population"])

    def test_burj_828m_is_official_and_381m_is_not_a_conflict(self):
        result = self._run("burj")
        self.assertEqual(result["corrected_fact"], "828 m")
        self.assertEqual(result["correction_check"], "supported")
        self.assertTrue(any("ctbuh.org" in x["domain"] for x in result["correction_sources"]))
        self.assertNotIn("381", result["conflicting_values"])

    def test_amazon_six_million_spelled_out_matches_esa(self):
        result = self._run("amazon")
        self.assertEqual(result["correction_check"], "supported")
        self.assertTrue(any(x["domain"] == "esa.int" for x in result["correction_sources"]))

    def test_world_population_does_not_reuse_an_old_official_projection_as_current(self):
        result = self._run("world_population")
        self.assertEqual(result["correction_check"], "secondary_only")
        self.assertFalse(result["correction_selection"]["official"])
        self.assertTrue(result["correction_sources"])
        self.assertTrue(all(x["source_type"] not in R.OFFICIAL_TYPES for x in result["correction_sources"]))
        self.assertIn("No official 2026", result["explanation"])
        self.assertIn("not officially verified", result["explanation"].lower())
        self.assertNotIn("Institutional figure:", result["explanation"])


if __name__ == "__main__":
    unittest.main()
