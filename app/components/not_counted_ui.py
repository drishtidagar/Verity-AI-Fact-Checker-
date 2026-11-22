import html
from urllib.parse import urlsplit

import streamlit as st

REASON_ORDER = ["user-generated", "low relevance", "outdated for claim", "projection not current",
                "no direct support stated", "not cited by the assessment"]
REASON_HELP = {
    "user-generated": "Forums, Q&A and social posts are never counted as evidence.",
    "low relevance": "Retrieved, but too weakly related to the claim to rely on.",
    "outdated for claim": "The source reports a historical figure, not a current estimate.",
    "projection not current": "The source gives a projection, not a current measurement or estimate.",
    "no direct support stated": "The source was cited but did not directly support or contradict the claim.",
    "not cited by the assessment": "Relevant, but not used for this verdict.",
}


def render_not_counted(not_counted, key_prefix="nc"):
    """Separate 'Not counted as evidence' panel, shown after the Sources list."""
    if not not_counted:
        return
    with st.expander(f"Not counted as evidence ({len(not_counted)})"):
        st.caption("Retrieved during the search but excluded from the verdict, with the reason.")
        link_index = 0
        for reason in REASON_ORDER + sorted({n["reason"] for n in not_counted} - set(REASON_ORDER)):
            items = [n for n in not_counted if n["reason"] == reason]
            if not items:
                continue
            st.markdown(f"**{reason.capitalize()}** — {REASON_HELP.get(reason, '')}")
            for n in items:
                domain = html.escape(str(n.get("domain") or "Unknown source"))
                source_type = html.escape(str(n.get("source_type") or "Unclassified"))
                st.markdown(f"- {domain} · {source_type}")
                try:
                    parsed = urlsplit(str(n.get("url") or ""))
                    safe_link = (parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)
                                 and parsed.username is None and parsed.password is None)
                except ValueError:
                    safe_link = False
                if safe_link:
                    st.link_button("Open source", n["url"], key=f"{key_prefix}_{link_index}")
                link_index += 1
