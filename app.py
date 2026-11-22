import io
import logging
import os
import uuid
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from app.config import APP_VERSION, DEFAULT_MODEL, MAX_UPLOAD_MB
from app.services.database import (
    init_db, save_audit, list_audits, get_audit, delete_audit, update_findings, totals, VERDICT_KEYS,
)
from app.services.factcheck import run_audit, retry_failed, FAILED_STATES, MAX_CHUNKS, CHUNK_CHARS
from app.services.providers import ProviderError
from app.components.ui import style, hero, donut, render_report

logger = logging.getLogger(__name__)

load_dotenv()
st.set_page_config(page_title="Verity | Evidence Intelligence", page_icon="\u2726", layout="wide")
style()
init_db()

SAMPLES = [
    ("Trap document v2 (outdated + fabricated + unverifiable)", "sample_data/Verity_Evaluation_Trap_Sample_v2.pdf"),
    ("Trap document v1 (basic true/false facts)", "sample_data/Verity_Evaluation_Trap_Sample.pdf"),
]


# ---------------------------------------------------------------- keys
# Server-side secrets are read only when a provider is called. They are NEVER written into a widget,
# so they are never sent to the browser. A visitor can type their own key for this session only.
def server_secret(name):
    try:
        v = st.secrets.get(name, "")
        if v:
            return str(v)
    except Exception:
        pass
    return os.getenv(name, "")


def get_key(name):
    override = st.session_state.get("override_" + name, "")
    return override or server_secret(name)


def retry_panel(report, key_prefix):
    """Re-run only the claims that failed for technical reasons and save the merged result."""
    n_failed = sum(1 for f in report["findings"] if f["result"].get("verdict") in FAILED_STATES)
    if not n_failed:
        return
    if st.button(f"Retry failed claims ({n_failed})", key=f"{key_prefix}_retry_{report['id']}", type="primary"):
        gk, tk = get_key("GROQ_API_KEY"), get_key("TAVILY_API_KEY")
        if not gk or not tk:
            st.error("Add Groq and Tavily keys in Settings (or ask the app owner to configure server secrets).")
            return
        try:
            with st.spinner(f"Retrying {n_failed} failed claim(s)\u2026"):
                merged = retry_failed(report["findings"], gk, tk,
                                      st.session_state.get("last_model", DEFAULT_MODEL))
            update_findings(report["id"], merged, sid)
        except ProviderError as e:
            st.error(f"{e.provider} problem: {e}")
            return
        st.rerun()


for k in ("override_GROQ_API_KEY", "override_TAVILY_API_KEY"):
    st.session_state.setdefault(k, "")
if "session_id" not in st.session_state:
    st.session_state["session_id"] = uuid.uuid4().hex
sid = st.session_state["session_id"]

with st.sidebar:
    st.markdown("## \u2726 VERITY")
    st.caption("EVIDENCE INTELLIGENCE")
    page = st.radio(
        "WORKSPACE",
        ["Overview", "New audit", "Audit history", "Analytics", "Product strategy", "Settings"],
        label_visibility="collapsed",
    )
    st.divider()
    st.caption("Groq \u00b7 " + ("Key available" if get_key("GROQ_API_KEY") else "Not configured"))
    st.caption("Tavily \u00b7 " + ("Key available" if get_key("TAVILY_API_KEY") else "Not configured"))
    st.caption("v" + APP_VERSION)
    st.caption("History is private to this browser session and may reset when the app restarts.")

rows = list_audits(sid)
counts = totals(rows)
counts = {k: counts.get(k, 0) for k in VERDICT_KEYS}

if page == "Overview":
    hero("VERITY / EVIDENCE INTELLIGENCE", "Know what your content claims.",
         "A review workspace that extracts factual claims from PDFs, checks live sources and keeps evidence attached to every verdict.")
    a, b, c, d = st.columns(4)
    a.metric("Documents audited", len(rows))
    b.metric("Claims reviewed", sum(r["claims_found"] for r in rows))
    c.metric("False claims flagged", counts["FALSE"])
    d.metric("Technical failures", counts["AI REVIEW FAILED"] + counts["SEARCH FAILED"])
    left, right = st.columns([1.15, .85])
    with left:
        st.markdown("### Verdict distribution")
        donut(counts)
    with right:
        st.markdown("### The review workflow")
        st.markdown(
            '<div class="panel"><b>01 \u00b7 Extract</b><p>Identify factual claims and page references.</p>'
            '<b>02 \u00b7 Investigate</b><p>Retrieve live web evidence and source links.</p>'
            '<b>03 \u00b7 Assess</b><p>Explain each verdict; keep uncertainty explicit.</p>'
            '<b>04 \u00b7 Report</b><p>Save an audit trail and export findings.</p></div>',
            unsafe_allow_html=True,
        )
    st.markdown("### Recent audits")
    if rows:
        st.dataframe(
            [{"Document": r["filename"], "Created": r["created_at"][:19], "Claims": r["claims_found"]} for r in rows[:7]],
            width="stretch", hide_index=True,
        )
    else:
        st.info("No audit history yet. Start with New audit \u2014 you can download a sample trap document there.")

elif page == "New audit":
    hero("WORKSPACE / NEW AUDIT", "Review a document before it ships.",
         "Upload a text-based PDF. Verity extracts factual claims, searches live sources and records evidence-backed findings.")
    x, y = st.columns(2)
    with x:
        model = st.selectbox("Groq model", ["openai/gpt-oss-20b", "openai/gpt-oss-120b"], index=0)
    with y:
        max_claims = st.slider("Max claims to review", 1, 20, 10,
                               help="Each claim costs one web search and one model call. Set this at or above the number of claims in your document.")

    with st.expander("No document handy? Download a sample trap document"):
        for label, path in SAMPLES:
            fp = Path(path)
            if fp.exists():
                st.download_button(label, fp.read_bytes(), fp.name, "application/pdf", key="sample_" + fp.name)

    upload = st.file_uploader("Drop your PDF here", type=["pdf"])
    if upload:
        st.success(f"{upload.name} \u00b7 {upload.size/1024:.1f} KB")
        if upload.size > MAX_UPLOAD_MB * 1024 * 1024:
            st.error(f"Maximum upload size is {MAX_UPLOAD_MB} MB.")
        elif st.button("Run evidence review", type="primary", width="stretch"):
            gk, tk = get_key("GROQ_API_KEY"), get_key("TAVILY_API_KEY")
            if not gk or not tk:
                st.error("Add Groq and Tavily keys in Settings (or ask the app owner to configure server secrets).")
            else:
                bar = st.progress(0)
                msg = st.empty()
                msg.caption("Extracting claims from the PDF\u2026")

                def progress(i, n):
                    bar.progress(i / n if n else 1.0)
                    msg.caption(f"Verified {i} of {n} claims\u2026")

                try:
                    st.session_state["last_model"] = model
                    audit = run_audit(io.BytesIO(upload.getvalue()), gk, tk, model, max_claims, progress)
                    if audit["claims_found"] == 0:
                        msg.empty()
                        st.warning("No verifiable factual claims were found in this document "
                                   f"({audit['filtered_candidates']} candidate(s) filtered as instructions or duplicates).")
                    else:
                        aid = save_audit(upload.name, audit, sid)
                        st.session_state["latest_audit"] = aid
                        skipped = audit.get("skipped_chunks", 0)
                        st.session_state["latest_notice"] = (
                            f"This document is longer than Verity reviews in one run: only the first {MAX_CHUNKS * CHUNK_CHARS:,} "
                            f"characters were read and {skipped} later section(s) were NOT checked. Split the PDF to review the rest."
                            if skipped else ""
                        )
                        msg.empty()
                        bar.empty()
                        st.success(f"Review complete \u00b7 audit #{aid} saved to your history.")
                except ValueError as e:
                    st.error(str(e))
                except ProviderError as e:
                    st.error(f"{e.provider} problem: {e}")
                except Exception as e:  # noqa: BLE001
                    # Keep provider payloads, paths, and user document text out of the browser.
                    # Log only the exception class: exception messages can contain secrets or document text.
                    logger.error("Unexpected PDF review failure (type=%s)", type(e).__name__)
                    st.error("Unexpected error while reviewing the document. Check the server logs for details.")
    st.caption("Cost: one extraction call per ~9,000 characters, then one or two searches and one assessment call per claim, "
               "with a short pause between claims. Provider quotas still apply.")

    latest = st.session_state.get("latest_audit")
    if latest:
        report = get_audit(latest, sid)
        if report:
            st.divider()
            st.markdown("### Latest results")
            if st.session_state.get("latest_notice"):
                st.warning(st.session_state["latest_notice"])
            render_report(report, key_prefix="latest")
            retry_panel(report, "latest")

elif page == "Audit history":
    hero("WORKSPACE / HISTORY", "Every review, traceable.", "Reopen claim-level evidence and download previous audit reports.")
    query = st.text_input("Search document names")
    for r in [x for x in rows if query.lower() in x["filename"].lower()]:
        with st.container(border=True):
            l, m, n = st.columns([3, 1, 1])
            l.markdown(f"**{r['filename']}**")
            l.caption(f"Audit #{r['id']} \u00b7 {r['created_at'][:19]}")
            m.metric("Claims", r["claims_found"])
            if n.button("Open", key=f"open{r['id']}"):
                st.session_state["open_audit"] = r["id"]
            if n.button("Delete", key=f"del{r['id']}"):
                st.session_state["confirm_delete"] = r["id"]
    if not rows:
        st.info("No audits in this session yet.")
    if st.session_state.get("confirm_delete"):
        aid = st.session_state["confirm_delete"]
        st.warning(f"Delete audit #{aid}?")
        u, v = st.columns(2)
        if u.button("Confirm delete"):
            delete_audit(aid, sid)
            st.session_state.pop("confirm_delete", None)
            if st.session_state.get("open_audit") == aid:
                st.session_state.pop("open_audit", None)
            if st.session_state.get("latest_audit") == aid:
                st.session_state.pop("latest_audit", None)
            st.rerun()
        if v.button("Cancel"):
            st.session_state.pop("confirm_delete", None)
            st.rerun()
    aid = st.session_state.get("open_audit")
    if aid:
        report = get_audit(aid, sid)
        if report:
            st.divider()
            render_report(report, key_prefix="hist")
            retry_panel(report, "hist")

elif page == "Analytics":
    hero("WORKSPACE / ANALYTICS", "Measure review outcomes.", "Metrics are calculated only from this session's saved audits. No synthetic activity is included.")
    a, b, c = st.columns(3)
    a.metric("Audits", len(rows))
    b.metric("Claims", sum(r["claims_found"] for r in rows))
    c.metric("False verdicts", counts["FALSE"])
    st.markdown("### Verdict mix")
    donut(counts)
    st.caption("A verdict count is not a model-accuracy score. Accuracy requires labelled ground-truth examples and human review "
               "(see docs/TRAP_TEST.md for the labelled trap-document protocol).")

elif page == "Product strategy":
    hero("PRODUCT / STRATEGY","From detection to defensible action.","Verity supports content, brand and product teams that need an evidence trail before approving claims.")
    st.markdown("""
### Problem and users
Marketing and business PDFs may contain stale statistics, unsupported statements or factual errors. Manual verification is slow. Primary users are content reviewers, product marketers, brand teams and agency strategists.

### Product principles
- Evidence before verdict; every claim links to retrieved sources.
- Uncertainty is valid; missing evidence is not automatically false.
- Explainability: preserve claim, page, source and rationale.
- Human-in-the-loop: reviewers own the final editorial decision.
- Cost-aware processing: configurable small claim limits and explicit provider errors.

### Success metrics
| Metric | Definition |
|---|---|
| Claim extraction yield | Relevant factual claims / extracted candidates |
| Evidence coverage | Claims with relevant evidence / claims reviewed |
| Review completion rate | Audits with terminal status / audits started |
| Median time to review | Time from upload to report |
| Human correction acceptance | Suggested corrections accepted / reviewed |

### Roadmap
**0–3 months:** labelled evaluation set, reviewer feedback, source allowlists, caching, pilot with a small content team.

**3–6 months:** shared workspaces, review assignments, approved-claim library, recurring re-checks and Google Drive/CMS integrations.

**6–12 months:** enterprise SSO, multilingual review, private source allowlists, API/webhooks and managed storage.

### Monetization hypotheses
Free evaluation tier → Team workspace subscription → Business integrations and policy controls → Enterprise governance, SSO, API and deployment options. Pricing requires willingness-to-pay validation; no price point is claimed as validated.
""")

elif page == "Settings":
    hero("WORKSPACE / SETTINGS", "Connect your evidence providers.",
         "Optional: use your own keys for this browser session only. For deployment, store keys in Streamlit Secrets.")
    srv_g, srv_t = bool(server_secret("GROQ_API_KEY")), bool(server_secret("TAVILY_API_KEY"))
    ok, missing = "\u2705 configured", "\u274c not set"
    groq_state = ok if srv_g else missing
    tavily_state = ok if srv_t else missing
    st.markdown(f"**Server secrets:** Groq {groq_state} \u00b7 Tavily {tavily_state}")
    st.caption("Secret values are never displayed or sent to your browser.")
    with st.form("keys", clear_on_submit=True):
        g = st.text_input("Groq API key (session override)", value="", type="password", placeholder="Leave empty to use the server secret")
        t = st.text_input("Tavily API key (session override)", value="", type="password", placeholder="Leave empty to use the server secret")
        if st.form_submit_button("Use for this session", type="primary"):
            if g.strip():
                st.session_state["override_GROQ_API_KEY"] = g.strip()
            if t.strip():
                st.session_state["override_TAVILY_API_KEY"] = t.strip()
            st.success("Session keys saved. They are kept in memory only for this browser session.")
    if st.session_state["override_GROQ_API_KEY"] or st.session_state["override_TAVILY_API_KEY"]:
        if st.button("Clear session keys"):
            st.session_state["override_GROQ_API_KEY"] = ""
            st.session_state["override_TAVILY_API_KEY"] = ""
            st.rerun()
    st.markdown("**Streamlit Cloud Secrets**")
    st.code('GROQ_API_KEY = "your-key"\nTAVILY_API_KEY = "your-key"', language="toml")
    st.markdown("- [Groq Console](https://console.groq.com/keys)\n- [Tavily Dashboard](https://app.tavily.com/)")
    st.warning("Never commit .env or API keys. Free-tier access and limits are controlled by providers and can change.")
