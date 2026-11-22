# Trap-document test protocol

Purpose: show, with recorded evidence, that Verity (1) catches fabricated statistics, (2) catches outdated
statistics and returns the current fact, and (3) does **not** call an unverifiable claim "false".

## How to run
1. Open **New audit**, download *Trap document v2* from the sample expander (or use `sample_data/Verity_Evaluation_Trap_Sample_v2.pdf`).
2. Set **Max claims to review** to **13** (the document has 13 claims) and run the review.
3. Copy each claim's verdict into the "Observed" column below, mark Pass/Fail, and attach a screenshot of the results page.
4. Re-run once on another day: verdicts for outdated claims depend on live sources, so note any differences.

## Expected outcomes (author's labels - the ground truth for scoring, not a prediction of the app)
| # | Claim (abridged) | Category | Expected verdict | Run 1 - v1.2, audit #2 (21 Nov 2026) | Run 2 - v1.3 (fill in) | Pass? |
|---|---|---|---|---|---|---|
| 1 | Water is H2O | true | VERIFIED | VERIFIED |  ||
| 2 | UN founded 24 Oct 1945 | true | VERIFIED | VERIFIED |  ||
| 3 | Eiffel Tower is in Berlin | fabricated | FALSE | FALSE |  ||
| 4 | Great Wall visible from the Moon | false (myth) | FALSE | FALSE |  ||
| 5 | Adult skeleton has 206 bones | true | VERIFIED | VERIFIED |  ||
| 6 | Burj Khalifa is 1,250 m tall | fabricated statistic | FALSE | FALSE |  ||
| 7 | Amazon rainforest covers ~12 million km2 | fabricated statistic | FALSE | FALSE |  ||
| 8 | World population ~7 billion | outdated | INACCURATE (current figure in corrected fact) | INACCURATE |  ||
| 9 | India's population ~1.2 billion | outdated | INACCURATE (FALSE also defensible) | INACCURATE |  ||
| 10 | Atmospheric CO2 ~400 ppm | outdated | INACCURATE (current level in corrected fact) | INACCURATE |  ||
| 11 | Pluto is the ninth planet | outdated classification | INACCURATE (FALSE also defensible) | AI REVIEW FAILED (Groq 429) - not a verdict |  ||
| 12 | Pacific is the largest ocean | true | VERIFIED | VERIFIED |  ||
| 13 | Acme Industries internal churn 4.1% (FY2023) | unverifiable | INSUFFICIENT EVIDENCE (must NOT be FALSE) | AI REVIEW FAILED (Groq 429) - not a verdict |  ||

## Scoring
- **Fabricated caught:** rows 3, 4, 6, 7 returned FALSE (or INACCURATE with a correct fact).
- **Outdated caught:** rows 8-11 returned INACCURATE/FALSE **and** the corrected fact states the current figure from a cited source.
- **No false alarms:** rows 1, 2, 5, 12 are VERIFIED and row 13 is INSUFFICIENT EVIDENCE.
- Report the rates honestly, including failures. A verdict count is not an accuracy score; this table is.


## Run 1 summary (from the saved v1.2 JSON; not re-run by the reviewer)
- Fabricated (3, 4, 6, 7): 4/4 FALSE. Outdated (8, 9, 10): 3/3 INACCURATE with a corrected fact; row 11 not reviewed.
- True claims (1, 2, 5, 12): 4/4 VERIFIED. Row 13 (unverifiable) **not tested** - the review failed technically.
- 2 of 13 claims were technical failures. Run 2 (v1.3) must show 13/13 reviewed, or use **Retry failed claims** and record that.
