import os
import tempfile
import unittest
from pathlib import Path

os.environ["VERITY_CLAIM_DELAY"] = "0"
os.environ["VERITY_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "ui.db")
os.environ["GROQ_API_KEY"] = "gsk_FAKE_SERVER_SECRET"
os.environ["TAVILY_API_KEY"] = "tvly-FAKE_SERVER_SECRET"

try:
    from streamlit.testing.v1 import AppTest
except Exception:  # pragma: no cover
    AppTest = None

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def all_text(at):
    return " ".join(str(getattr(e, "value", "")) for e in list(at.markdown) + list(at.caption) + list(at.code))


@unittest.skipIf(AppTest is None, "streamlit testing utilities not available")
class UITests(unittest.TestCase):
    def test_all_six_workspace_pages_load(self):
        at = AppTest.from_file(APP, default_timeout=30).run()
        for page in ("Overview", "New audit", "Audit history", "Analytics", "Product strategy", "Settings"):
            at.sidebar.radio[0].set_value(page).run()
            self.assertFalse(at.exception, f"page failed: {page}")

    def test_source_link_policy_rejects_unsafe_schemes_and_credentials(self):
        from app.components.ui import _safe_http_url
        self.assertTrue(_safe_http_url("https://example.gov/source"))
        self.assertTrue(_safe_http_url("http://example.org"))
        for url in ("javascript:alert(1)", "data:text/html,evil", "file:///secret.txt",
                    "https://user:pass@example.org/source", "not a url"):
            with self.subTest(url=url):
                self.assertFalse(_safe_http_url(url))

    def test_server_secrets_are_never_placed_in_a_widget(self):
        at = AppTest.from_file(APP, default_timeout=30).run()
        at.sidebar.radio[0].set_value("Settings").run()
        self.assertFalse(at.exception)
        for ti in at.text_input:
            self.assertNotIn("FAKE_SERVER_SECRET", ti.value)
            self.assertEqual(ti.value, "")
        self.assertNotIn("FAKE_SERVER_SECRET", all_text(at))

    def test_settings_snippet_uses_real_newlines(self):
        at = AppTest.from_file(APP, default_timeout=30).run()
        at.sidebar.radio[0].set_value("Settings").run()
        code = at.code[0].value
        self.assertIn("\n", code)
        self.assertNotIn("\\n", code)

    def test_results_are_shown_on_the_page_after_a_run(self):
        from app.services.database import init_db, save_audit
        init_db()
        audit = {"page_count": 1, "claims_found": 1, "filtered_candidates": 0, "findings": [{
            "claim": {"claim": "The world's population is approximately 7 billion people.", "excerpt": "7 billion", "page": 1, "claim_type": "statistic"},
            "result": {"verdict": "INACCURATE", "confidence": 88, "model_confidence": 88,
                       "confidence_label": "Model-reported confidence: 88/100 (uncalibrated; not a probability)",
                       "explanation": "Evidence shows a larger current figure.",
                       "corrected_fact": "About 8.2 billion people as of 2025.", "evidence_quality": "HIGH",
                       "used_urls": ["https://data.example.org/pop"], "search_query": "q",
                       "evidence": [{"title": "Population", "url": "https://data.example.org/pop", "source_type": "Official / institutional",
                                     "snippet": "World population reached 8.2 billion.", "published_date": "2025-07-01"}]}}]}
        aid = save_audit("trap.pdf", audit, "sess-ui")
        at = AppTest.from_file(APP, default_timeout=30)
        at.session_state["session_id"] = "sess-ui"
        at.session_state["latest_audit"] = aid
        at.run()
        at.sidebar.radio[0].set_value("New audit").run()
        self.assertFalse(at.exception)
        text = all_text(at)
        for needle in ("INACCURATE", "Corrected / up-to-date fact", "8.2 billion", "Official / institutional", "USED", "model confidence: 88/100", "uncalibrated"):
            self.assertIn(needle, text)

    def test_history_hides_other_sessions(self):
        from app.services.database import init_db, save_audit
        init_db()
        empty = {"page_count": 1, "claims_found": 0, "filtered_candidates": 0, "findings": []}
        save_audit("someone_elses.pdf", empty, "other-session")
        at = AppTest.from_file(APP, default_timeout=30)
        at.session_state["session_id"] = "mine"
        at.run()
        at.sidebar.radio[0].set_value("Audit history").run()
        self.assertNotIn("someone_elses.pdf", all_text(at))


if __name__ == "__main__":
    unittest.main()
