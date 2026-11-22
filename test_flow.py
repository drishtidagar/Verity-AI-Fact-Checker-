import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["VERITY_CLAIM_DELAY"] = "0"
os.environ["VERITY_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "flow.db")
os.environ["GROQ_API_KEY"] = "gsk_FAKE"
os.environ["TAVILY_API_KEY"] = "tvly-FAKE"

try:
    from streamlit.testing.v1 import AppTest
    STREAMLIT_TESTING = True
except ImportError:
    AppTest = None
    STREAMLIT_TESTING = False

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "app.py")
PDF = ROOT / "sample_data" / "Verity_Evaluation_Trap_Sample_v2.pdf"


def fake_groq(prompt, key, model, system, max_tokens=0):
    if "Extract up to" in prompt:
        return {"claims": [
            {"claim": "The Eiffel Tower is located in Berlin, Germany.", "excerpt": "3. The Eiffel Tower", "page": 1, "claim_type": "other"},
            {"claim": "The world's population is approximately 7 billion people.", "excerpt": "8.", "page": 1, "claim_type": "statistic"},
            {"claim": "Acme Industries recorded an internal churn rate of 4.1% in FY2023.", "excerpt": "13.", "page": 1, "claim_type": "financial"}]}
    claim_line = prompt.split("CLAIM:", 1)[-1].splitlines()[0].lower()
    if "eiffel" in claim_line:
        url = "https://www.europarl.europa.eu/news/eiffel"
        return {"verdict": "FALSE", "confidence": 97, "explanation": "The source places it in Paris.",
                "corrected_fact": "The Eiffel Tower is in Paris, France.", "evidence_quality": "HIGH",
                "used_urls": [url], "source_notes": [{"url": url, "says": "The Eiffel Tower is in Paris.",
                                                        "stance": "contradicts"}]}
    if "population" in claim_line:
        url = "https://www.worldometers.info/world-population"
        return {"verdict": "INACCURATE", "confidence": 90, "explanation": "A newer figure was found.",
                "corrected_fact": "About 8.2 billion (2025).", "evidence_quality": "HIGH",
                "used_urls": [url], "source_notes": [{"url": url, "says": "The figure was about 8.2 billion in 2025.",
                                                        "stance": "contradicts"}]}
    return {"verdict": "INSUFFICIENT EVIDENCE", "confidence": 30, "explanation": "No public source.", "corrected_fact": "", "evidence_quality": "LOW", "used_urls": []}


def fake_search(query, key, n=3, **kwargs):
    if "eiffel" in query.lower():
        return [{"title": "European Parliament", "url": "https://www.europarl.europa.eu/news/eiffel",
                 "domain": "www.europarl.europa.eu", "source_type": "Official / institutional",
                 "snippet": "The Eiffel Tower is in Paris.", "published_date": ""}]
    if "population" in query.lower():
        return [{"title": "World population estimate", "url": "https://www.worldometers.info/world-population",
                 "domain": "www.worldometers.info", "source_type": "Reference / secondary",
                 "snippet": "The world population was about 8.2 billion in 2025.", "published_date": "2025-06-01"}]
    return [{"title": "Source", "url": "https://e.example/1", "domain": "e.example", "source_type": "Other — review source",
             "snippet": "Relevant snippet text.", "published_date": "2025-06-01"}]


@unittest.skipUnless(STREAMLIT_TESTING, "Streamlit testing utilities are not installed in this test environment")
class FlowTest(unittest.TestCase):
    def test_upload_run_and_see_results_without_leaving_the_page(self):
        with patch("app.services.factcheck.groq_json", side_effect=fake_groq), \
                patch("app.services.factcheck.tavily_search", side_effect=fake_search):
            at = AppTest.from_file(APP, default_timeout=60).run()
            at.sidebar.radio[0].set_value("New audit").run()
            at.file_uploader[0].set_value(("trap.pdf", PDF.read_bytes(), "application/pdf"))
            at.run()
            self.assertFalse(at.exception)
            run_btn = [b for b in at.button if "Run evidence review" in b.label]
            self.assertTrue(run_btn, "Run button should appear after upload")
            run_btn[0].click().run()
            self.assertFalse(at.exception)
        text = " ".join(str(getattr(e, "value", "")) for e in list(at.markdown) + list(at.caption) + list(at.success) + list(at.error))
        for needle in ("Review complete", "Latest results", "FALSE", "INSUFFICIENT EVIDENCE",
                       "The Eiffel Tower is in Paris, France.", "No official current population estimate"):
            self.assertIn(needle, text)
        # three claims reviewed, and the unverifiable internal metric is not marked FALSE
        self.assertEqual(text.count(">FALSE<"), 1)

    def test_unexpected_review_error_does_not_echo_exception_or_secret_to_ui(self):
        with patch("app.services.factcheck.run_audit", side_effect=RuntimeError("gsk_private_document_secret")):
            at = AppTest.from_file(APP, default_timeout=60).run()
            at.sidebar.radio[0].set_value("New audit").run()
            at.file_uploader[0].set_value(("trap.pdf", PDF.read_bytes(), "application/pdf"))
            at.run()
            run_btn = [button for button in at.button if "Run evidence review" in button.label]
            self.assertTrue(run_btn)
            with self.assertLogs(level="ERROR") as captured:
                run_btn[0].click().run()
            self.assertFalse(at.exception)
        messages = " ".join(str(item.value) for item in list(at.error) + list(at.markdown))
        self.assertNotIn("gsk_private_document_secret", "\n".join(captured.output))
        self.assertIn("Check the server logs", messages)
        self.assertNotIn("gsk_private_document_secret", messages)


if __name__ == "__main__":
    unittest.main()
