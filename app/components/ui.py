
import html
import json
from urllib.parse import urlsplit

import streamlit as st
import plotly.express as px
import pandas as pd
from app.components.not_counted_ui import render_not_counted

VERDICT_COLORS = {
    "VERIFIED": "#36c99a",
    "INACCURATE": "#f2b65c",
    "FALSE": "#ef7181",
    "INSUFFICIENT EVIDENCE": "#8494ad",
    "AI REVIEW FAILED": "#e3c56a",
    "SEARCH FAILED": "#a08be8",
}
VERDICT_HELP = {
    "VERIFIED": "Evidence directly supports the claim.",
    "INACCURATE": "Outdated or materially imprecise - see the corrected fact.",
    "FALSE": "Credible evidence directly contradicts the claim.",
    "INSUFFICIENT EVIDENCE": "Not enough reliable evidence either way. This is NOT a finding that the claim is false.",
    "AI REVIEW FAILED": "Technical state: the model call failed. Sources were still saved. Not a factual verdict.",
    "SEARCH FAILED": "Technical state: web search failed. Not a factual verdict.",
}
OFFICIAL_SOURCE_TYPES = {"Government", "Academic", "Official / institutional"}


def _safe_http_url(value):
    """Only render retrieved http(s) pages as clickable links."""
    try:
        parsed = urlsplit(str(value or ""))
        return (
            parsed.scheme.lower() in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


def _source_note_caption(note, exclusion_reason=None):
    """Label model-supplied source notes without presenting them as source quotations."""
    stance = str(note.get("stance") or "context").lower()
    if stance not in {"supports", "contradicts", "context"}:
        stance = "context"
    label = f"Model-reported source note ({stance}"
    if exclusion_reason:
        label += f"; not relied on, not counted: {exclusion_reason}"
    return f"{label}): {note.get('says', '')}"


def _report_not_counted(result, used_urls):
    """Read canonical exclusions first and keep the UI consistent with the JSON report."""
    if isinstance(result.get("not_counted"), list):
        rows = result["not_counted"]
    else:
        rows = result.get("retrieved_not_counted") or result.get("cited_not_counted") or []

    by_url = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("url") or row["url"] in used_urls:
            continue
        old = by_url.get(row["url"])
        if old is None or (
            old.get("reason") == "not cited by the assessment"
            and row.get("reason") != "not cited by the assessment"
        ):
            by_url[row["url"]] = dict(row)
    return list(by_url.values())


def style():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@600;700;800&display=swap');

        /* Main application background */
        .stApp,
        [data-testid="stAppViewContainer"] {
            background: #0b1020 !important;
            color: #ffffff !important;
            font-family: 'DM Sans', sans-serif !important;
        }

        .block-container {
            max-width: 1420px;
            padding-top: 1.6rem;
        }

        /* Top Streamlit header */
        header[data-testid="stHeader"],
        [data-testid="stHeader"],
        .stAppHeader {
            background: #0b1020 !important;
            color: #ffffff !important;
        }

        [data-testid="stToolbar"] {
            background: #0b1020 !important;
        }

        [data-testid="stDecoration"] {
            background: #6366f1 !important;
        }

        /* Headings */
        h1, h2, h3, h4, h5, h6 {
            color: #ffffff !important;
            font-family: 'Manrope', sans-serif !important;
            letter-spacing: -0.03em;
        }
        /* Streamlit top-right toolbar: make all icons and text white */
[data-testid="stHeader"] button,
[data-testid="stHeader"] [role="button"],
[data-testid="stToolbar"] button,
[data-testid="stToolbar"] [role="button"] {
    color: #ffffff !important;
}

/* Toolbar SVG icons: GitHub, Star, Edit, Menu */
[data-testid="stHeader"] svg,
[data-testid="stToolbar"] svg {
    color: #ffffff !important;
    fill: #ffffff !important;
    stroke: #ffffff !important;
}

/* SVG paths */
[data-testid="stHeader"] svg path,
[data-testid="stToolbar"] svg path {
    fill: #ffffff !important;
    stroke: #ffffff !important;
}

/* Share text and toolbar labels */
[data-testid="stHeader"] span,
[data-testid="stToolbar"] span {
    color: #ffffff !important;
}
        /* General text */
        p, li, label, span, small,
        [data-testid="stMarkdownContainer"],
        [data-testid="stMarkdownContainer"] p {
            color: #f1f5f9;
        }

        /* Sidebar */
        [data-testid="stSidebar"] {
            background: #0d1426 !important;
            border-right: 1px solid #263550 !important;
        }

        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            color: #ffffff !important;
        }

        /* Hero section */
        .hero {
            padding: 26px 30px;
            border-radius: 18px;
            background: linear-gradient(
                115deg,
                #1e1b4b,
                #312e81 58%,
                #4338ca
            );
            border: 1px solid #6366f1;
            margin-bottom: 18px;
        }

        .kicker {
            font-size: 11px;
            letter-spacing: 0.15em;
            color: #c7d2fe !important;
            font-weight: 700;
        }

        .hero h1 {
            font-size: 32px;
            color: #ffffff !important;
            margin: 8px 0;
        }

        .hero p {
            color: #e2e8f0 !important;
            font-size: 14px;
        }

        /* Metric cards */
        div[data-testid="stMetric"] {
            background: #111a2d !important;
            border: 1px solid #263550 !important;
            border-radius: 14px;
            padding: 14px;
        }

        div[data-testid="stMetricLabel"],
        div[data-testid="stMetricLabel"] p {
            color: #cbd5e1 !important;
            font-size: 13px;
        }

        div[data-testid="stMetricValue"],
        div[data-testid="stMetricValue"] * {
            color: #ffffff !important;
        }

        div[data-testid="stMetricDelta"],
        div[data-testid="stMetricDelta"] * {
            color: #cbd5e1 !important;
        }

        /* Panels */
        .panel {
            background: #111a2d;
            border: 1px solid #263550;
            border-radius: 14px;
            padding: 18px;
            color: #ffffff !important;
        }

        /* Buttons */
        .stButton > button {
            color: #ffffff !important;
            border: 1px solid #526b96 !important;
            border-radius: 10px;
            font-weight: 600;
            background: #17243d !important;
        }

        .stButton > button[kind="primary"] {
            background: linear-gradient(
                90deg, #617df0, #8265d9
            ) !important;
            border: 0 !important;
            border-radius: 10px;
            color: #ffffff !important;
            font-weight: 700;
        }

        /* PDF uploader */
        div[data-testid="stFileUploader"] {
            background: #111a2d !important;
            border: 1px dashed #6366f1 !important;
            border-radius: 14px;
            color: #ffffff !important;
            padding: 8px;
        }

        div[data-testid="stFileUploader"] section {
            background: #111a2d !important;
        }

        div[data-testid="stFileUploaderDropzone"] {
            background: #17243d !important;
            border: 1px dashed #6366f1 !important;
            border-radius: 12px !important;
        }

        div[data-testid="stFileUploader"] * {
            color: #ffffff !important;
        }

        /* PDF uploader button: dark readable text */
        div[data-testid="stFileUploaderDropzone"] button {
            background: #eaf2ff !important;
            color: #172554 !important;
            border: 1px solid #b8cced !important;
        }

        div[data-testid="stFileUploaderDropzone"] button * {
            color: #172554 !important;
        }

        /* Inputs */
        input, textarea {
            color: #ffffff !important;
            background-color: #111a2d !important;
        }

        [data-baseweb="select"] * {
            color: #ffffff !important;
        }

        /* Expanders */
        [data-testid="stExpander"] {
            background: #111a2d !important;
            border: 1px solid #263550 !important;
            border-radius: 12px;
            color: #ffffff !important;
        }

        [data-testid="stExpander"] summary,
        [data-testid="stExpander"] summary p {
            color: #ffffff !important;
        }

        /* Tabs */
        button[data-baseweb="tab"] {
            color: #cbd5e1 !important;
        }

        button[data-baseweb="tab"][aria-selected="true"] {
            color: #ffffff !important;
        }

        /* Captions */
        [data-testid="stCaptionContainer"],
        [data-testid="stCaptionContainer"] * {
            color: #cbd5e1 !important;
        }

        /* Links */
        a {
            color: #93b4ff !important;
        }

        /* Alerts: dark readable text on light information boxes */
        [data-testid="stAlert"] {
            background: #eaf2ff !important;
            border: 1px solid #b8cced !important;
            border-radius: 12px !important;
        }

        [data-testid="stAlert"] p,
        [data-testid="stAlert"] span,
        [data-testid="stAlert"] div,
        [data-testid="stAlert"] [data-testid="stMarkdownContainer"],
        [data-testid="stAlert"] [data-testid="stMarkdownContainer"] * {
            color: #172554 !important;
        }

        /* Dataframes */
        [data-testid="stDataFrame"] {
            color: #ffffff !important;
        }

        /* Dividers */
        hr {
            border-color: #263550 !important;
        }

        /* Verdict badges and finding cards */
        .vbadge {
            display: inline-block;
            padding: 3px 12px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 800;
            letter-spacing: 0.06em;
            color: #0b1020 !important;
        }

        .vmeta {
            color: #cbd5e1 !important;
            font-size: 12px;
            margin-left: 10px;
        }

        .vclaim {
            font-size: 16px;
            font-weight: 600;
            margin: 10px 0 4px 0;
            color: #ffffff !important;
        }

        .vhelp {
            color: #aab6cc !important;
            font-size: 12px;
            margin-bottom: 8px;
        }

        .vfix {
            background: #10251f;
            border: 1px solid #36c99a55;
            border-left: 4px solid #36c99a;
            border-radius: 10px;
            padding: 10px 14px;
            margin: 8px 0;
            color: #e6fff6 !important;
        }

        .vsrc {
            margin: 6px 0 2px 0;
            font-size: 13px;
        }

        .vtag {
            font-size: 10px;
            font-weight: 800;
            letter-spacing: 0.08em;
            color: #0b1020 !important;
            background: #93b4ff;
            border-radius: 6px;
            padding: 1px 6px;
            margin-left: 6px;
        }

        .vsnip {
            color: #aab6cc !important;
            font-size: 12px;
            margin: 0 0 6px 14px;
        }

        .vtag-nc {
            background: #64748b !important;
            color: #ffffff !important;
        }

        </style>
        """,
        unsafe_allow_html=True
    )


def hero(section, title, desc):
    st.markdown(
        f"""
        <div class="hero">
            <div class="kicker">{section}</div>
            <h1>{title}</h1>
            <p>{desc}</p>
        </div>
        """,
        unsafe_allow_html=True
    )


def donut(counts):
    data = [(k, v) for k, v in counts.items() if v]

    if not data:
        st.info(
            "No saved audits yet. Run your first PDF review "
            "to populate this chart."
        )
        return

    df = pd.DataFrame(data, columns=["Verdict", "Claims"])

    fig = px.pie(
        df,
        names="Verdict",
        values="Claims",
        hole=0.68,
        color="Verdict",
        color_discrete_map=VERDICT_COLORS
    )

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(
            color="#ffffff",
            size=12
        ),
        legend=dict(
            title_text="",
            font=dict(
                color="#ffffff",
                size=12
            ),
            bgcolor="rgba(0,0,0,0)"
        ),
        height=300,
        margin=dict(l=5, r=5, t=5, b=5)
    )

    fig.update_traces(
        textfont=dict(color="#0b1020")
    )

    st.plotly_chart(fig, width="stretch")


def _badge(verdict):
    color = VERDICT_COLORS.get(verdict, "#8494ad")
    return f'<span class="vbadge" style="background:{color}">{html.escape(verdict)}</span>'


def _rating_text(r):
    """Short evidence-strength label, separate from the model's confidence."""
    if r.get("evidence_rating"):
        return f"evidence: {html.escape(str(r['evidence_rating']))}"
    return "evidence: not rated"


def _confidence_text(r):
    """Display only a validated model score; legacy heuristic values are not model confidence."""
    if "model_confidence" in r:
        score = r.get("confidence")
        if isinstance(score, int) and not isinstance(score, bool) and 0 <= score <= 100:
            return f"model confidence: {score}/100"
        return "model confidence: unavailable"
    label = str(r.get("confidence_label", "")).lower()
    if "legacy" in label or "heuristic" in label:
        return "model confidence: unavailable (legacy score)"
    return "model confidence: unavailable"


def _render_rating(r):
    checks = r.get("evidence_checks") or []
    if r.get("evidence_rating") in (None, "Not rated") or not checks:
        return

    with st.expander(f"Why is the evidence rated {r['evidence_rating']}?"):
        for c in checks:
            mark = {True: "\u2705", False: "\u274c", None: "\u2796"}[c.get("ok")]
            st.markdown(f"{mark} {c['label']}")

        st.caption(
            "Rule-based rating of the cited sources. It is not a probability and not the model's confidence. "
            "Strong = a relevant official source, no conflicts, correction found in an official source. "
            "Off-topic and user-generated sources are not counted."
        )


def render_report(report, key_prefix="rep"):
    """Full, evidence-first view of one saved audit. Used right after a run and from Audit history."""
    findings = report["findings"]
    st.subheader(report["filename"])

    st.caption(
        f"Audit #{report['id']} · {report['created_at'][:19]} UTC · {report['page_count']} page(s) · "
        f"{report['claims_found']} claim(s) reviewed · {report['filtered_candidates']} candidate(s) filtered out"
    )

    counts = report.get("summary", {})
    failed = counts.get("AI REVIEW FAILED", 0) + counts.get("SEARCH FAILED", 0)

    if failed:
        st.warning(
            f"{failed} claim(s) could not be reviewed because of a technical failure (for example a provider "
            "rate limit). These are NOT factual verdicts. Use “Retry failed claims” below the report "
            "to re-run only those claims; completed findings are kept."
        )

    shown = [(k, v) for k, v in counts.items() if v]

    if shown:
        cols = st.columns(len(shown))
        for col, (k, v) in zip(cols, shown):
            col.metric(k.title(), v)

    st.download_button(
        "Download JSON report",
        json.dumps(report, indent=2, ensure_ascii=False),
        f"verity_{report['id']}.json",
        "application/json",
        key=f"{key_prefix}_dl_{report['id']}",
    )

    for i, item in enumerate(findings, 1):
        claim, r = item["claim"], item["result"]
        verdict = r.get("verdict", "INSUFFICIENT EVIDENCE")
        evidence = r.get("evidence", [])
        used = set(r.get("used_urls", []))
        notes = {
            n["url"]: n
            for n in r.get("source_notes", [])
            if isinstance(n, dict) and n.get("url")
        }

        # Audits saved before v1.4 have no canonical exclusion list; use available legacy fields.
        all_not_counted = _report_not_counted(r, used)
        not_counted = {
            x["url"]: x.get("reason", "")
            for x in all_not_counted
            if isinstance(x, dict) and x.get("url")
        }

        for e in evidence:
            if e["url"] in used and e.get("source_type") == "User-generated":
                not_counted.setdefault(e["url"], "user-generated")

        with st.container(border=True):
            st.markdown(
                f'{_badge(verdict)}<span class="vmeta">#{i} · page {claim.get("page", 1)} · '
                f'{html.escape(str(claim.get("claim_type", "other")))} · {_rating_text(r)} · '
                f'{_confidence_text(r)}</span>'
                f'<div class="vclaim">{html.escape(claim["claim"])}</div>'
                f'<div class="vhelp">{html.escape(VERDICT_HELP.get(verdict, ""))}</div>',
                unsafe_allow_html=True,
            )

            _render_rating(r)

            st.caption(
                "Model-reported confidence is uncalibrated and is not a probability. "
                "Evidence strength is assessed separately; older heuristic scores are shown as unavailable."
            )

            if claim.get("excerpt"):
                st.caption(f"From the PDF: “{claim['excerpt']}”")

            if r.get("explanation"):
                st.write(r["explanation"])

            if r.get("downgrade_reason"):
                st.info("Verdict set to INSUFFICIENT EVIDENCE: " + r["downgrade_reason"])

            if r.get("conflicting_values"):
                st.info("Sources report different values: " + r["conflicting_values"])

            if r.get("correction_warning"):
                st.warning(r["correction_warning"])

            if r.get("corrected_fact"):
                st.markdown(
                    f'<div class="vfix"><b>Corrected / up-to-date fact</b><br>{html.escape(r["corrected_fact"])}</div>',
                    unsafe_allow_html=True,
                )

                # v1.4.1: which source(s) actually contain each corrected figure
                trace_lines = []
                for v in r.get("correction_values", []):
                    holders = ", ".join(
                        f'{h["domain"]} ({h["source_type"]})'
                        for h in v.get("found_in", [])
                    )
                    trace_lines.append(
                        f'{v["value"]}: ' + (holders or "not found in any counted source")
                    )

                if trace_lines:
                    st.caption("Figure traced to — " + " | ".join(trace_lines))

            if evidence:
                primary = [
                    e for e in evidence
                    if e.get("source_type") in OFFICIAL_SOURCE_TYPES
                ]
                user_generated = [
                    e for e in evidence
                    if e.get("source_type") == "User-generated"
                ]
                secondary = [
                    e for e in evidence
                    if e not in primary and e not in user_generated
                ]

                groups = [
                    ("Primary / official sources", primary),
                    ("Secondary / contextual sources", secondary),
                    ("User-generated sources", user_generated),
                ]

                for group_title, group in groups:
                    if not group:
                        continue

                    st.markdown(f"**{group_title} ({len(group)})**")

                    for e in group:
                        title = html.escape(e.get("title") or e["url"])

                        if e["url"] in not_counted:
                            tag = (
                                f'<span class="vtag vtag-nc">NOT COUNTED: '
                                f'{html.escape(not_counted[e["url"]])}</span>'
                            )
                        elif e["url"] in used:
                            tag = '<span class="vtag">USED</span>'
                        else:
                            tag = ""

                        when = e.get("published_date", "")[:10] or (
                            f"date in text: {e['date_in_text']}"
                            if e.get("date_in_text") else ""
                        )
                        meta = " · ".join(
                            x for x in [e.get("source_type", ""), when] if x
                        )
                        url = str(e.get("url") or "")

                        if _safe_http_url(url):
                            link = (
                                f'<a href="{html.escape(url, quote=True)}" target="_blank" '
                                f'rel="noopener noreferrer">{title}</a>'
                            )
                        else:
                            link = title

                        st.markdown(
                            f'<div class="vsrc">{link}{tag}'
                            f' <span class="vmeta">{html.escape(meta)}</span></div>'
                            f'<div class="vsnip">{html.escape(e.get("snippet", "")[:300])}</div>',
                            unsafe_allow_html=True,
                        )

                        note = notes.get(e["url"])
                        if note and note.get("says"):
                            st.caption(
                                _source_note_caption(note, not_counted.get(e["url"]))
                            )

                source_values = r.get("source_values") or []

                if source_values:
                    st.markdown("**Values by source**")
                    for value in source_values:
                        detail = ", ".join(
                            str(value.get(k))
                            for k in ("series", "date", "unit")
                            if value.get(k)
                        )
                        st.caption(
                            f'{value.get("value", "")} — {value.get("domain", "")} {detail}'.strip()
                        )

                if r.get("search_query"):
                    st.caption(f"Search query: {r['search_query']}")

                render_not_counted(
                    all_not_counted,
                    key_prefix=f"{key_prefix}_{i}_nc"
                )

            else:
                st.caption("No sources were retrieved for this claim.")
