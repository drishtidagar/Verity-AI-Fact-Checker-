"""Confidence is a model report; evidence strength is rated separately."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.components.ui import _confidence_text
from app.services.database import get_audit, init_db, save_audit
from app.services.factcheck import assess_evidence, validate_model_confidence


class ConfidenceContractTests(unittest.TestCase):
    SOURCE = {
        "title": "Official fact sheet",
        "url": "https://agency.gov/fact-sheet",
        "domain": "agency.gov",
        "source_type": "Government",
        "snippet": "The documented fact is true.",
        "relevance_score": 0.9,
    }
    CLAIM = {"claim": "The documented fact is true.", "excerpt": "", "page": 1, "claim_type": "other"}

    def assess(self, response, evidence=None):
        evidence = evidence if evidence is not None else [dict(self.SOURCE)]
        response = dict(response)
        response.setdefault("used_urls", [e["url"] for e in evidence])
        response.setdefault("source_notes", [
            {"url": e["url"], "says": "The documented fact is true.", "stance": "supports"}
            for e in evidence
        ])
        with patch("app.services.factcheck.groq_json", return_value=response):
            return assess_evidence(self.CLAIM, evidence, "offline-key", "offline-model")

    def test_valid_integer_confidence_values_are_preserved(self):
        for raw, expected in ((0, 0), (1, 1), (73, 73), (100, 100), ("85", 85)):
            with self.subTest(raw=raw):
                self.assertEqual(validate_model_confidence(raw), expected)

    def test_missing_null_invalid_and_out_of_range_confidence_are_unavailable(self):
        for raw in (None, "", "high", True, False, -1, 101, 0.5, float("nan"), float("inf")):
            with self.subTest(raw=raw):
                self.assertIsNone(validate_model_confidence(raw))

    def test_missing_and_invalid_confidence_are_null_in_assessment_result(self):
        for response in ({"verdict": "VERIFIED"}, {"verdict": "VERIFIED", "confidence": None},
                         {"verdict": "VERIFIED", "confidence": "uncertain"},
                         {"verdict": "VERIFIED", "confidence": 101}):
            with self.subTest(response=response):
                result = self.assess(response)
                self.assertIsNone(result["confidence"])
                self.assertIsNone(result["model_confidence"])
                self.assertIn("unavailable", result["confidence_label"].lower())

    def test_explicit_zero_is_preserved_but_no_evidence_does_not_get_a_score(self):
        explicit_zero = self.assess({"verdict": "VERIFIED", "confidence": 0})
        self.assertEqual(explicit_zero["confidence"], 0)
        self.assertEqual(explicit_zero["model_confidence"], 0)
        self.assertEqual(explicit_zero["evidence_confidence"], None)

        no_evidence = self.assess({"verdict": "FALSE", "confidence": 99, "used_urls": []}, evidence=[])
        self.assertEqual(no_evidence["verdict"], "INSUFFICIENT EVIDENCE")
        self.assertIsNone(no_evidence["confidence"])
        self.assertEqual(no_evidence["model_confidence"], 99)

    def test_different_model_scores_remain_distinct_and_evidence_is_separate(self):
        high = self.assess({"verdict": "VERIFIED", "confidence": 88, "evidence_quality": "HIGH"})
        cautious = self.assess({"verdict": "VERIFIED", "confidence": 54, "evidence_quality": "MEDIUM"})
        self.assertEqual((high["confidence"], cautious["confidence"]), (88, 54))
        self.assertEqual((high["model_confidence"], cautious["model_confidence"]), (88, 54))
        self.assertIsNone(high["evidence_confidence"])
        self.assertIsNone(cautious["evidence_confidence"])
        self.assertEqual(high["evidence_rating"], cautious["evidence_rating"])

    def test_confidence_round_trips_through_json_and_sqlite(self):
        result = self.assess({"verdict": "VERIFIED", "confidence": 84})
        exported = json.loads(json.dumps({"confidence": result["confidence"],
                                          "model_confidence": result["model_confidence"],
                                          "evidence_confidence": result["evidence_confidence"]}))
        self.assertEqual(exported, {"confidence": 84, "model_confidence": 84, "evidence_confidence": None})

        with tempfile.TemporaryDirectory() as tmp, patch("app.services.database.DB_PATH", str(Path(tmp) / "audit.db")):
            init_db()
            audit = {"page_count": 1, "claims_found": 1, "filtered_candidates": 0,
                     "findings": [{"claim": self.CLAIM, "result": result}]}
            audit_id = save_audit("confidence.pdf", audit, "confidence-session")
            loaded = get_audit(audit_id, "confidence-session")
            self.assertEqual(loaded["findings"][0]["result"]["confidence"], 84)
            self.assertIsNone(loaded["findings"][0]["result"]["evidence_confidence"])

    def test_ui_distinguishes_model_score_from_legacy_and_missing_values(self):
        self.assertEqual(_confidence_text({"confidence": 84, "model_confidence": 84}),
                         "model confidence: 84/100")
        self.assertEqual(_confidence_text({"confidence": None, "model_confidence": None}),
                         "model confidence: unavailable")
        self.assertEqual(_confidence_text({"confidence": 87,
                                           "confidence_label": "Legacy heuristic score; not calibrated"}),
                         "model confidence: unavailable (legacy score)")


if __name__ == "__main__":
    unittest.main()
