# Verity AI — AI-powered PDF Fact Checker and Evidence Intelligence

Verity AI extracts factual claims from PDFs, retrieves live public web evidence with Tavily, evaluates each claim with Groq, and keeps the evidence trail in an audit history with JSON export.

## What it does
| Step | Behaviour |
|---|---|
| Extract | `pypdf` text extraction; documents are processed in ~9,000-character chunks, **up to 6 chunks (~54,000 characters) per run** - if a document is longer the app warns that the remaining sections were NOT reviewed; duplicates and document *instructions* are filtered out |
| Investigate | One Tavily search per claim (3 results). If none of them is an official/institutional source, **one extra search restricted to official domains** (UN, World Bank, NASA, NOAA, .gov ...) is added. For statistics and financial figures the query asks for the **latest** figure |
| Assess | The model sees today's date, source types, publish dates (or a date it can read from the title/snippet, because Tavily rarely returns publish dates for general searches) and snippets, and must answer from that evidence only, attribute each figure to the source that states it, and report conflicting values |
| Report | Verdict badge, **evidence rating (Strong / Moderate / Weak) with a visible checklist**, page + PDF excerpt, explanation, **corrected / up-to-date fact** (flagged if its figure is not in the cited text), what each source says, every source (type, date, snippet, link) with the sources used marked, JSON download, **Retry failed claims** |

## Verdict policy
- **VERIFIED** — evidence directly supports the claim.
- **INACCURATE** — outdated or materially imprecise; the current fact is shown as *Corrected / up-to-date fact*.
- **FALSE** — credible evidence directly contradicts the claim.
- **INSUFFICIENT EVIDENCE** — missing, weak, unrelated or ambiguous evidence, or private data (e.g. one company's internal metric). Verity deliberately does **not** equate absence of evidence with falsity.
- **AI REVIEW FAILED / SEARCH FAILED** — technical states, never factual verdicts; retrieved sources are still saved.

## Security
- API keys come from Streamlit Secrets / environment variables and are read server-side only. They are **never placed in a page widget**, so they are never sent to the browser. Visitors may type their own keys for their session only.
- Audit history is scoped to the visiting browser session.
- Do not upload confidential documents; there is no authentication.

## Setup (Windows PowerShell)
Python 3.11–3.14.
```powershell
py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```
Edit `.env` with your Groq and Tavily keys, then:
```powershell
python -m streamlit run app.py
```

## Deploy (Streamlit Community Cloud)
Entry point `app.py`. In app settings → Secrets:
```toml
GROQ_API_KEY = "your-groq-key"
TAVILY_API_KEY = "your-tavily-key"
```
Never commit `.env`, `.streamlit/secrets.toml` or `app/data/` (all in `.gitignore`).

## Testing
```powershell
python -m unittest discover -s tests -v
```
Current verification details, including exact test count, compile and startup checks, compatibility checks, and live API availability, are in `Test-results.txt` and `docs/FINAL_ENGINEERING_AUDIT.md`. Automated tests and saved report replays mock Groq and Tavily; they do not spend live API credits.
**Trap-document test:** follow `docs/TRAP_TEST.md` using `sample_data/Verity_Evaluation_Trap_Sample_v2.pdf`
(13 claims: true, fabricated, outdated and unverifiable). Record the observed verdicts in that file.

## Evidence safeguards (v1.4.4)
- Every retrieved result is retained. Counted sources, model-cited sources and retrieved-but-not-counted sources are tracked separately.
- Facebook, Instagram, Brainly and other known user-generated domains cannot contribute to evidence strength; exclusions are shown with reasons.
- Table values are associated with their own entity row. A value from an adjacent building row is not treated as a Burj Khalifa value.
- Corrected values are traced to source content; secondary-only values are not labelled officially verified. A correction is withheld if no selected source qualifies as evidence.
- Model-reported per-source notes are checked against the cited title and snippet, including numeric values. They are labeled as model notes in the UI, not presented as source quotations. This lexical guard is conservative and is not a semantic proof.
- Source conflicts are checked across source values, not by comparing an outdated PDF claim to its correction. Different units/definitions need human review.
- Single-domain support is explicitly described as provisional; explanations that overstate the number of sources are flagged with a limitation.

## Limits
Text-based PDFs only (scanned PDFs need OCR). Source labels are heuristic. Search snippets can be incomplete or
stale; Tavily returns publish dates only for some results. Model output is probabilistic — human review is required.
SQLite storage is local and may reset when a hosted app restarts. Provider quotas and free-tier limits apply
 (one model assessment per claim, one or two searches depending on official-source coverage, and up to three retries for transient provider failures).


## Evidence rating (v1.3, tightened in v1.4)
The rating describes the *evidence*, not the probability that the verdict is right, and it is not the model's confidence.
- **Which sources count (v1.4).** Only *counted* sources are rated. Not counted: user-generated pages (Q&A sites, social media), sources whose Tavily relevance score is below 0.3 (an off-topic official domain proves nothing), and - when the model supplied per-source notes - sources not noted as directly supporting or contradicting the claim. Not-counted sources stay visible in the report with the reason.
- **Strong** - a counted primary/official source (government, academic, UN/World Bank-type institution) **and every line of the checklist passes**: at least 2 independent counted domains (two sub-domains of one site are one domain), no conflicting values, any corrected figure found in the cited text **and in an official source**, and a visible date for statistics. Strong is never shown next to a failed check (v1.4.1).
- **Moderate** - an official source with one of those problems, or two or more independent counted domains.
- **Weak** - nothing counted, a single secondary source, an ungrounded correction, or little independent support.
- A definitive verdict that rests **only on user-generated pages** is downgraded to INSUFFICIENT EVIDENCE.
- **Used sources (v1.4.1).** `used_urls` lists only counted sources. What the model selected is kept as `cited_urls`; every cited source that did not count is in `not_counted` with the reason.
- **Corrected figures (v1.4.1).** Each number is traced source by source (`correction_values`). `correction_check` is `supported` (every number is in an official source), `secondary_only` (in a cited text, but only Wikipedia / reference / blog sources - not fully verified, warning shown), `not_found`, or `n/a`.
- **Source disagreement (v1.4.1).** Verity compares the figures the counted sources themselves report (`source_values`): two sources giving different values within 10 % of the corrected figure are reported as a conflict with their dates, even if the model did not notice. The original claim's own number is never one side of a conflict. This works only when a corrected figure exists.
- **Snippets (v1.4.1).** Each source shows the one or two sentences / fields most related to the claim (`snippet`); the raw first 500 characters are kept as `snippet_raw`.
- **Conflicts (v1.4).** A reported conflict is kept only if it is a disagreement between supplied sources: the claim's own value and the corrected value are never a conflict, and numeric conflicts must be two different values found in two different counted sources. What the model reported but the code did not accept is kept in `conflict_ignored` in the JSON. The code still cannot see conflicts the model does not report.
- The corrected-figure check confirms the number exists in a cited source's text to the precision it is written (`correction_sources` in the JSON lists where). If it appears only in secondary sources (Wikipedia, reference sites) a warning is shown and the rating cannot be Strong. It cannot confirm that an explanation names the right organisation for that number.

## Confidence semantics
`confidence` is reserved for a valid model-reported integer from 0 to 100 and is explicitly labelled uncalibrated, not a probability. It is kept separate from `evidence_rating` and is unavailable (`null`) when missing, malformed, out of range, or when the evidence does not support a factual verdict. Verity does not infer a probability from source counts or evidence quality. Old reports may contain a legacy heuristic score; the UI labels that value as legacy and does not present it as model confidence.

## Reliability
Provider calls use exponential backoff (up to 3 retries on transient network, 429, or 5xx errors; honour `Retry-After`, capped at 45 s per wait). Claims are paced (`VERITY_CLAIM_DELAY`, default 1 s). A rejected API key (401/403) stops the audit immediately. A claim that still fails is saved as **AI REVIEW FAILED / SEARCH FAILED** (a technical state, never a verdict) with its sources, and **Retry failed claims** re-runs only those claims. A claim normally uses one Tavily search and one model assessment; an official-domain fallback search can add a search when the first results lack institutional evidence.
