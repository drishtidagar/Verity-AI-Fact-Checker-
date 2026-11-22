# Verity AI — Final Engineering Audit

Date: 22 November 2026  
Scope: the supplied Verity project source archive and the active workspace, including the Streamlit app, service layer, six UI routes, tests, latest saved 13-claim report, sample PDFs, configuration, and deployment documentation.

The attached assessment PDF is product-assessment context. Its assessment deliverables are distinct from this direct request to audit, repair, test, and package the existing application; the PDF does not replace or override the user's project instructions.

## Executive summary

Verity AI is a Python 3.11–3.14 Streamlit application that extracts selectable PDF text with `pypdf`, detects factual claims with Groq, retrieves public web evidence through Tavily, applies rule-based source/evidence checks, persists findings in SQLite, and renders downloadable JSON reports. The six existing routes are Overview, New audit, Audit history, Analytics, Product strategy, and Settings. Their functionality remains intact.

The core findings from the latest report have been addressed in the existing application. The largest data-integrity issue was that `confidence` represented an arbitrary evidence heuristic rather than Groq's returned confidence. Source accounting, numeric/dated corrections, authority attribution, and URL-only domain independence also received regression coverage. The saved report was replayed offline; a new live 13-claim run was not possible because neither provider credential was configured.

## Confirmed issues and fixes

| Severity | Issue / root cause | Affected files | Fix and verification |
|---|---|---|---|
| High | Confidence was not model confidence. The supplied source archive calculated a hand-weighted score from evidence-quality buckets, domain counts, source labels, and relevance. It discarded the model's score. Technical failure paths also used zero. | `app/services/factcheck.py`, `app/components/ui.py` | Removed the synthetic score path. Strictly validate explicit model values (integer 0–100), preserve `model_confidence`, expose `confidence` only for a factual verdict with counted evidence, otherwise use JSON `null`. UI labels it uncalibrated and distinct from evidence strength. Legacy scores are not rendered as model confidence. Tested valid, missing, null, invalid, out-of-range, serialization, persistence, and UI cases. |
| High | Water source cards did not communicate authority differences clearly; source lists could suggest equal evidentiary weight. | `app/components/ui.py`, `tests/test_latest_report_audit.py` | Kept the verified/Strong result when NOAA and NIST directly support H2O; grouped official/primary sources separately from secondary/contextual and user-generated sources. Empty exclusions remain empty and the explanation does not invent excluded sources. Offline replay and Streamlit UI test cover the grouping. |
| High | Eiffel correction wording attributed the Paris fact only to a secondary source despite direct support from the European Parliament. | `app/services/factcheck.py`, `tests/test_latest_report_audit.py` | Correction tracing now uses counted sources, identifies the European Parliament as an institutional source, and names it in the explanation. Regression asserts the institutional attribution and removes the contradictory secondary-only wording. |
| High | World population results could treat historical sources or projections as current, and secondary-only estimates could look officially verified. | `app/services/factcheck.py`, `app/services/evidence_rules.py`, `tests/test_latest_report_audit.py` | Historical figures and future projections are excluded from current-estimate support with explicit reasons. The result distinguishes current estimates, historical figures, and projections; it says when the retrieved sources do not provide an official 2026 estimate and labels secondary-only corrections as not officially verified. No changing population number is hardcoded. |
| High | Numeric CO₂ evidence could be retrieved but omitted from `used_urls`; measurements with different dates/series risked being conflated. | `app/services/factcheck.py`, `tests/test_latest_report_audit.py` | Numeric measurement extraction associates each value with source, series, date, and units. Relevant NASA/NOAA measurement URLs are counted when their direct assessment supports or contradicts the claim, snippets retain measurement details, and separate series/dates are reported separately rather than as a same-date conflict. Regression cases verify value/source/date/unit attribution and same-date disagreement. |
| High | Pluto's dwarf-planet correction could be described as secondary-only without seeking available institutional evidence. | `app/services/factcheck.py`, `app/services/providers.py`, `tests/test_latest_report_audit.py` | Institutional search coverage includes an IAU result; source tracing preserves NASA/IAU institutional attribution. Tests cover discovery and direct source attribution without hardcoding verdicts into production. |
| Medium | Independence logic could over-count source URLs when an old record omitted its `domain` field; multiple NASA URLs must count as one organization. | `app/services/factcheck.py`, `app/services/evidence_rules.py`, `tests/test_latest_report_audit.py` | Evidence rating now uses the canonical URL/host parser. Added a legacy URL-only regression for two NASA subdomains. Quora and other user-generated sources remain excluded. |
| High | A model could cite an official page with a title-only note and have the note treated as direct location evidence; a model correction could remain visible after all cited sources were excluded. | `app/services/factcheck.py`, `tests/test_latest_report_audit.py` | Counted evidence requires a direct source note lexically grounded in the cited title/snippet, including matching numeric values. If no cited source qualifies, the proposed corrected fact is cleared and the explanation states that no determination can be made. This is a conservative lexical guard, not semantic entailment. |
| High | Sources could be selected by the model without direct per-source support/contradiction, and correction tracing could use retrieved but uncounted sources. | `app/services/factcheck.py` | Counted evidence requires a valid direct source note, relevance above the configured threshold, and non-user-generated classification. Corrected facts are traced only to counted sources. Missing notes exclude the source with a visible reason. Regression coverage verifies all 13 source partitions. |
| Medium | `not_counted` differed between saved JSON and the UI's fallback exclusion list. | `app/components/ui.py`, `app/components/not_counted_ui.py` | JSON `not_counted` is authoritative in the UI; excluded records are deduplicated and cannot overlap `used_urls`. Link rendering validates HTTP(S) URLs and uses safe native Streamlit link buttons. |
| Low | The screenshot's “What this source says (supports)” caption could make an excluded YouTube source note look like accepted evidence or a direct quotation. | `app/components/ui.py`, `tests/test_latest_report_audit.py` | Captions now identify notes as model-reported; excluded rows also say the note was not relied on and state the exclusion reason. The Water UI regression checks this exact case. |
| Medium | A model could leave stale/confident explanation text in an already-`INSUFFICIENT EVIDENCE` result when no source counted; a generic provisional caveat could then repeat or misdescribe the evidence. | `app/services/factcheck.py`, `tests/test_latest_report_audit.py` | Any no-counted-source result now receives the neutral evidence-limitation explanation, independent of the model's initial verdict. One-source findings use the single-domain caveat once; no-source findings are not called provisional. |
| Medium | A URL-only legacy evidence record could make two pages on the same domain appear independent. | `app/services/factcheck.py`, `tests/test_latest_report_audit.py` | Uses `evidence_rules.registrable_domain` for both host and URL inputs. Great Wall coverage asserts the two NASA URLs collapse to one domain and Quora is not counted. |
| Medium | Unexpected application exceptions were interpolated into the user's browser error message. | `app.py`, `tests/test_flow.py` | The UI now shows a generic failure message; logs contain only the exception class, not the exception payload or traceback. Integration test injects a secret-like exception string and asserts that it appears in neither UI nor logs. Provider error responses no longer echo raw response bodies. |
| Medium | PDF text is untrusted and may contain instructions; upload and link handling need clear boundaries. | `app/services/factcheck.py`, `app/components/ui.py`, `.streamlit/config.toml`, `.gitignore` | Extraction prompts explicitly treat PDF content as data and JSON-encode it. Upload size is capped at 20 MB. External links accept only HTTP(S) URLs with a host and no embedded credentials. Environment/Streamlit secrets and local DB files are ignored by Git. |
| Medium | Saved database/report data must keep working as fields evolve. | `app/services/database.py`, `app/components/ui.py`, `tests/test_logic.py`, `tests/test_confidence_contract.py` | Kept the additive report shape and legacy-field fallbacks; regression tests migrate the legacy SQLite table without `session_id`, round-trip current JSON/SQLite confidence values, and render older report fields. |
| Low | README contained a repeated product summary and stale retry wording. | `README.md`, `CHANGES.md`, `Test-results.txt` | README now uses the requested product description, documents confidence semantics, and matches the provider retry policy. Current verification results are recorded separately from historical audit notes. |

## Confidence bug: root cause and current meaning

The supplied source archive contains `calculate_evidence_confidence()`: it assigned fixed points for LOW/MEDIUM/HIGH evidence, added points for the number of source domains and selected source categories, adjusted for relevance, and returned a bounded score. This was not a calibrated probability and did not preserve the Groq response's confidence. The no-evidence branch returned 15, while technical failure objects used 0. The saved 13-claim JSON contains legacy values from 15 to 87 and labels them as heuristic scores; therefore its data does not reproduce the reported all-zero screen. The exact earlier screen could not be replayed without its original run payload or screenshot data.

The fix removes evidence-derived percentages. `confidence` now means only a validated model-reported score. It is `null` if the model omits it or returns an invalid score, and also unavailable when the evidence does not permit a factual verdict. Evidence strength remains a separate rule-based rating. Model scores are uncalibrated and must not be read as probability estimates.

## Evidence/source methodology

1. The evaluator requests per-source notes and counts only sources directly described as supporting or contradicting the claim.
2. User-generated sources are excluded. Low-relevance results and sources without direct assessment remain visible under `not_counted` with reasons. When a source note is supplied, the note's claim-relevant words and numbers must overlap the cited title/snippet; this is a lexical safeguard, not proof of entailment.
3. Source category is descriptive (government, academic, institutional, established publisher, secondary/reference, etc.); domain reputation alone does not make a result relevant or direct evidence.
4. URLs are deduplicated/canonicalized by registrable domain for independence; multiple URLs/subdomains from one organization count once.
5. Numeric corrections are traced against counted source text. Secondary-only numeric corrections are not labelled officially verified. Time-sensitive facts require a visible year/date; historical data and projections are not treated as current observations.
6. CO₂ observations retain units, dates, measurement series, and source URL. Different measurement periods/series are reported distinctly; source conflicts require comparable observations.
7. Evidence rating is separate from confidence. Strong requires an official/primary source and all applicable checklist conditions to pass; Moderate reflects qualified evidence; Weak reflects limited evidence. The rating does not establish truth by itself.

## Files changed

The final source ZIP includes the complete project and sample Trap PDFs. This audit updated README/changelog/test-result documentation, application error handling, evidence and confidence logic, source presentation, URL validation, ignore/deployment configuration, and regression tests. The output archive excludes local databases, secrets, caches, and duplicate workspace copies. The workspace-only `tools/apply_confidence_fix.py` was also excluded: it is a one-off patcher absent from the supplied source archive, contains an absolute path outside the project, and implements the retired heuristic approach.

## Verification and compatibility

See `../Test-results.txt` for exact commands and results. Offline replay uses saved report data and mocked provider responses; it is not a live API rerun or a new full Trap PDF assessment. Legacy SQLite migration and older report rendering are covered by automated tests. The six Streamlit pages are exercised with `AppTest`.

### Latest uploaded report and Water screenshot (22 Nov 2026)

The newly uploaded 13-claim JSON is a separate run from the earlier saved report summarized below. Its source partitions and every counted note are replayed offline by `tests/test_latest_report_audit.py`. The Water screenshot's authority groups remain distinct (two primary/official, two secondary/contextual, one user-generated); the YouTube note is labeled model-reported and explicitly marked not relied on. Water remains VERIFIED / Strong with NOAA and NIST counted as official sources.

The attached Eiffel Tower run cites a European Commission coin page with the model note “The Eiffel Tower,” which does not establish the claim's location in Paris. The UN tag page is low relevance and the Brainly pages are user-generated. In this report replay, none qualifies as direct evidence, so the verdict is downgraded to INSUFFICIENT EVIDENCE and the unsupported Paris correction is withheld. This is distinct from the earlier report fixture that contains a directly relevant European Parliament source; that separate regression still verifies its institutional attribution.

The attached Burj Khalifa explanation called 828 m “most recent and authoritative” while also saying no institutional source confirmed it. The replay now attributes that figure to matadornetwork.com and says it is not officially verified. Across the other ten claims, the replay retains source-grounded explanations, keeps historical estimates and projections separate, and attributes NASA/NOAA observations by date and series. The Acme internal metric remains insufficient rather than being treated as false.

The new offline regressions also verify: old UNFPA population pages are not treated as 2026 estimates; NASA/NOAA CO₂ values retain their own date, unit and series; Pluto can obtain institutional IAU evidence; two NASA URLs count as one independent domain for Great Wall; and JSON/UI `not_counted` partitions stay aligned. These tests replay saved evidence and do not validate current search availability.

### 13-claim verdict comparison — saved-report replay only

The labels below are compared with the expected outcomes recorded in `TRAP_TEST.md`. The replay reuses the saved report's claims, model answers, and search evidence while rerunning current evidence logic; it does not extract the PDF again or call Groq/Tavily. `confidence` is unavailable in these rows because the saved values were legacy heuristics and were deliberately not replayed as model confidence.

| # | Expected label | Replay verdict | Evidence rating | Corrected fact from replay | Comparison |
|---:|---|---|---|---|---|
| 1 Water | VERIFIED | VERIFIED | Strong | — | Label match (offline only) |
| 2 UN founding date | VERIFIED | VERIFIED | Strong | — | Label match (offline only) |
| 3 Eiffel Tower in Berlin | FALSE | FALSE | Moderate | The Eiffel Tower is located in Paris, France. | Label match (offline only) |
| 4 Great Wall visible from Moon | FALSE | FALSE | Strong | — | Label match (offline only) |
| 5 Adult skeleton has 206 bones | VERIFIED | VERIFIED | Moderate | — | Label match (offline only) |
| 6 Burj Khalifa is 1,250 m | FALSE | FALSE | Strong | 828.00 metres | Label match (offline only) |
| 7 Amazon rainforest is 12 million km² | FALSE | FALSE | Moderate | — | Label match (offline only) |
| 8 World population is 7 billion | INACCURATE | INACCURATE | Moderate | 8.3 billion (secondary-only; no official 2026 estimate in retrieved evidence) | Label match (offline only) |
| 9 India population is 1.2 billion | INACCURATE (FALSE also defensible) | INACCURATE | Moderate | 1,481,124,730 (secondary-only; no official 2026 estimate in retrieved evidence) | Label match (offline only) |
| 10 Atmospheric CO₂ is 400 ppm | INACCURATE | INACCURATE | Strong | NASA: 426 ppm (September 2026); NOAA: 427.62 ppm (June 2026), separate series/dates | Label match (offline only) |
| 11 Pluto is the ninth planet | INACCURATE (FALSE also defensible) | INACCURATE | Moderate | Pluto is classified as a dwarf planet. | Label match (offline only) |
| 12 Pacific is the largest ocean | VERIFIED | VERIFIED | Strong | — | Label match (offline only) |
| 13 Acme internal churn metric | INSUFFICIENT EVIDENCE | INSUFFICIENT EVIDENCE | Not rated | — | Label match (offline only) |

These comparisons are not counted as live or end-to-end PDF passes. Rows 8–11 are time-sensitive or classification-sensitive and remain subject to human review; World/India values are explicitly not officially verified in the replay.

## Limitations and remaining risks

- Groq and Tavily live calls were not tested because `GROQ_API_KEY` and `TAVILY_API_KEY` were absent. Provider mocks do not prove current API/model availability, billing behavior, or search quality.
- The exact prior all-zero UI output was not supplied as a reproducible payload; the source-code root cause of mislabeled heuristic confidence is confirmed, but the historical screen itself was not reproduced.
- Source labels and topical relevance are heuristic; search snippets can be stale/incomplete. Human review remains necessary, especially for conflicting measurements and time-sensitive population estimates.
- The app handles selectable text PDFs only; scanned PDFs need OCR. Uploads are limited to 20 MB and the extractor caps the reviewed text at six chunks.
- Session-scoped history is not authentication. The default SQLite database is local and may be ephemeral on Streamlit Cloud. Do not deploy with confidential document expectations without authentication, storage, retention, and privacy controls.
- `pip check` validates dependency consistency, not known-vulnerability status. `pip-audit` was not installed, so a dependency CVE scan was not performed.
