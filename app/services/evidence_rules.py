"""Deterministic evidence rules for Verity (regression patch for the v1.4.1 trap-PDF issues).

Pure functions, no network and no Streamlit, so each rule is unit-testable against real saved reports.
They are designed to be called by the existing pipeline AFTER retrieval and BEFORE rating:

  build_not_counted(...)        - every retrieved source that was not used, with an explicit reason
  split_units / entity_units    - row-bounded and sentence-bounded text units (never mix table rows)
  snippet_cross_row_numbers     - detects a focused snippet that stitched numbers from another row
  correction_check(...)         - is the corrected value present in an official source's entity row/sentence?
  choose_correction(...)        - official-first corrected fact, with date, plus newer secondary estimate
  entity_row_values / find_conflicts - conflicts only from the SAME entity's row
  source_support_summary / explanation_overstates_sources - honest wording for single-source findings
"""
import re
from urllib.parse import urlparse

# "Academic" is treated as institutional because v1.4.1 already does (e.g. climate.mit.edu for CO2). Edit to tighten.
OFFICIAL_TYPES = {"Government", "Official / institutional", "Academic"}
LOW_RELEVANCE = 0.25
UGC_DOMAINS = {"brainly.com", "facebook.com", "instagram.com", "quora.com", "reddit.com", "tiktok.com",
               "x.com", "twitter.com", "pinterest.com", "answers.yahoo.com", "youtube.com"}
M_PER_FT = 0.3048
_SECOND_LEVEL = {"co", "com", "org", "gov", "ac", "edu", "net"}


# ------------------------------------------------------------------ domains
def registrable_domain(url_or_host):
    s = (url_or_host or "").strip().lower()
    host = urlparse(s).netloc if "://" in s else s.split("/")[0]
    host = host.split(":")[0]
    parts = [p for p in host.split(".") if p]
    if parts and parts[0] == "www":
        parts = parts[1:]
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in _SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else ".".join(parts)


def _is_ugc(ev):
    url = ev.get("url", "") or ""
    host = (urlparse(url).netloc or url.split("/")[0]).lower().split(":")[0].removeprefix("www.")
    return (ev.get("source_type") == "User-generated"
            or any(host == domain or host.endswith("." + domain) for domain in UGC_DOMAINS)
            or registrable_domain(url) in UGC_DOMAINS)


# ------------------------------------------------------------------ not counted (issue 1)
def build_not_counted(evidence, used_urls, relevance_floor=LOW_RELEVANCE):
    """One record per retrieved source that did not support the verdict, with the reason."""
    used = set(used_urls or [])
    out = []
    seen = set()
    for ev in evidence or []:
        url = str(ev.get("url") or "").strip()
        if not url or url in used or url in seen:
            continue
        seen.add(url)
        if _is_ugc(ev):
            reason = "user-generated"
        elif isinstance(ev.get("relevance_score"), (int, float)) and ev["relevance_score"] < relevance_floor:
            reason = "low relevance"
        elif ev.get("relevance_score") is None:
            reason = "not cited by the assessment"
        else:
            reason = "not cited by the assessment"
        out.append({"url": url, "domain": ev.get("domain") or registrable_domain(url),
                    "source_type": ev.get("source_type", ""), "reason": reason,
                    "relevance_score": ev.get("relevance_score")})
    return out


def merge_not_counted(cited_exclusions, retrieved_exclusions):
    """Return one canonical exclusion list, preserving specific reasons and unique URLs.

    Cited-but-rejected sources and retrieved-but-unused sources are two views of the same
    exclusion set. User-generated status takes precedence over generic "not cited" labels.
    """
    by_url = {}
    priority = {"not cited by the assessment": 0, "low relevance": 1,
                "no direct support stated": 2, "outdated for claim": 3,
                "projection not current": 3, "user-generated": 4}
    for item in list(cited_exclusions or []) + list(retrieved_exclusions or []):
        if not isinstance(item, dict) or not item.get("url"):
            continue
        url = item["url"]
        old = by_url.get(url)
        if old is None or priority.get(item.get("reason", ""), 1) > priority.get(old.get("reason", ""), 1):
            merged = dict(old or {})
            merged.update({k: v for k, v in item.items() if v not in (None, "")})
            by_url[url] = merged
        else:
            for k, v in item.items():
                if k not in by_url[url] or by_url[url][k] in (None, ""):
                    by_url[url][k] = v
    return list(by_url.values())


def make_explanation_source_scope(explanation, counted_sources):
    """Avoid claiming every retrieved/supplied source agrees when only a subset was counted."""
    text = str(explanation or "")
    if not text:
        return text
    domains = {registrable_domain(e.get("url", "")) for e in counted_sources or [] if e.get("url")}
    if not domains:
        return text
    replacements = {
        "All supplied sources": "The counted sources",
        "all supplied sources": "the counted sources",
        "All sources": "The counted sources",
        "all sources": "the counted sources",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    if len(domains) < 2:
        nouns = {"sources": "source", "estimates": "estimate", "studies": "study",
                 "reports": "report", "agencies": "agency", "institutions": "institution"}
        verbs = {"agree": "agrees", "confirm": "confirms", "state": "states", "report": "reports",
                 "indicate": "indicates", "show": "shows", "support": "supports", "are": "is", "have": "has"}
        plural_clause = re.compile(
            r"\b((?:(?:multiple|several|various|independent|different|all|both|supplied|counted|"
            r"secondary|official|primary|institutional|recent)\s+)?)"
            r"(sources|estimates|studies|reports|agencies|institutions)\s+"
            r"(agree|confirm|state|report|indicate|show|support|are|have)\b", re.I)
        def singular_clause(match):
            qualifier = match.group(1).strip().lower()
            qualifier = qualifier if qualifier in {"secondary", "official", "primary", "institutional", "recent"} else ""
            middle = f"{qualifier} " if qualifier else ""
            return f"the cited {middle}{nouns[match.group(2).lower()]} {verbs[match.group(3).lower()]}"
        text = plural_clause.sub(singular_clause, text)
        text = re.sub(r"\b(sources|estimates|studies|reports|agencies|institutions)\b",
                      lambda m: nouns[m.group(1).lower()],
                      text, flags=re.I)
    return text


# ------------------------------------------------------------------ quantities
_NUM = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?:\s*(billion|million|bn|metres?|meters?|m|ft|feet|foot|ppm|parts\s+per\s+million))?(?![\w])", re.I)


def parse_quantities(text):
    """[(value, kind, raw)] - length normalised to metres, counts scaled (billion/million).

    Also recognises common number words in source prose (e.g. “six million sq km”),
    because institutional sources often spell out small integers.
    """
    number_words = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
                    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
                    "eleven": "11", "twelve": "12"}
    source_text = text or ""
    for word, digit in number_words.items():
        source_text = re.sub(rf"\b{word}(?=\s+(?:million|billion|bn)\b)", digit, source_text, flags=re.I)
    out = []
    for m in _NUM.finditer(source_text):
        num = float(m.group(1).replace(",", ""))
        unit = (m.group(2) or "").lower()
        if unit in ("m", "metre", "metres", "meter", "meters"):
            out.append((num, "length", m.group(0).strip()))
        elif unit in ("ft", "feet", "foot"):
            out.append((num * M_PER_FT, "length", m.group(0).strip()))
        elif unit in ("billion", "bn"):
            out.append((num * 1e9, "count", m.group(0).strip()))
        elif unit == "million":
            out.append((num * 1e6, "count", m.group(0).strip()))
        elif unit in ("ppm",) or unit.startswith("parts"):
            out.append((num, "ppm", m.group(0).strip()))
        elif num >= 1e6:
            out.append((num, "count", m.group(0).strip()))
        elif not unit:
            out.append((num, "number", m.group(0).strip()))
    return out


def _close(a, b, tol):
    return abs(a - b) <= tol * max(abs(a), abs(b), 1e-9)


# ------------------------------------------------------------------ row / sentence units
_RANK_BOUNDARY = re.compile(r"\|\s*\|\s*(?=\d{1,3}\s*\|)")


def split_units(text):
    """Split source text into units that must never be mixed: table rows (newline, '[...]' gaps and
    glued '| | 2 |' rank boundaries) and, for prose, sentences."""
    units = []
    for chunk in re.split(r"\[\.\.\.\]|\n", text or ""):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.startswith("|") or chunk.count("|") >= 3:
            units += [u.strip() for u in _RANK_BOUNDARY.split(chunk) if u.strip()]
        else:
            units += [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", chunk) if s.strip()]
    return units


def entity_units(text, entity_terms):
    terms = [t.lower() for t in entity_terms]
    return [u for u in split_units(text) if any(t in u.lower() for t in terms)]


def _after_entity(unit, entity_terms):
    low = unit.lower()
    pos = min((low.find(t.lower()) + len(t) for t in entity_terms if t.lower() in low), default=0)
    return unit[pos:]


def _first_cluster(unit, entity_terms, kind):
    """First value after the entity plus any following values that are the same number in another unit
    (828 m / 2,717 ft). Stops at the first disagreeing value: that belongs to another row or fact."""
    qs = [q for q in parse_quantities(_after_entity(unit, entity_terms)) if q[1] == kind]
    if not qs:
        return []
    cluster = [qs[0]]
    for q in qs[1:]:
        if _close(q[0], cluster[0][0], 0.01):
            cluster.append(q)
        else:
            break
    return cluster


CONTEXT_TERMS = {"length": ("tall", "height", "high", "tallest"), "count": ("population", "people", "inhabitants")}
# Different measures of the same thing (not conflicts): "without the spire", "roof height", "observation deck"...
QUALIFIER_RE = re.compile(r"\b(without|excluding|excluded|would be|hypothetical|roof|occupied|observation|spire|pinnacle|antenna)\b", re.I)


def _is_table_row(unit):
    return unit.startswith("|") or unit.count("|") >= 3


def entity_row_values(evidence, entity_terms, kind="length"):
    """The entity's own headline value(s) per source. Raw text is authoritative; the focused snippet is used
    only when it is not contaminated by another row. Prose sentences count only when they talk about the
    measure (e.g. 'tall') and carry no measure qualifier ('without the spire'); table rows always count."""
    vals = []
    for ev in evidence or []:
        texts = [ev.get("snippet_raw") or "", ev.get("title") or ""]
        snip = ev.get("snippet") or ""
        if snip and not snippet_cross_row_numbers(snip, ev.get("snippet_raw") or "", entity_terms):
            texts.append(snip)
        seen = set()
        for t in texts:
            for u in entity_units(t, entity_terms):
                if not _is_table_row(u):
                    if not any(w in u.lower() for w in CONTEXT_TERMS.get(kind, ())) or QUALIFIER_RE.search(u):
                        continue
                cl = _first_cluster(u, entity_terms, kind)
                if cl and round(cl[0][0], 3) not in seen:
                    seen.add(round(cl[0][0], 3))
                    vals.append({"value": cl[0][0], "display": " / ".join(c[2] for c in cl), "url": ev.get("url", ""),
                                 "domain": registrable_domain(ev.get("url", "")), "source_type": ev.get("source_type", "")})
    return vals


def find_conflicts(values, tol=0.01):
    """Conflict only when same-entity values disagree beyond tolerance. Returns [] when they agree."""
    if not values:
        return []
    base = values[0]["value"]
    return values if any(not _close(v["value"], base, tol) for v in values) else []


# ------------------------------------------------------------------ snippet contamination (issue 2)
def snippet_cross_row_numbers(snippet, raw, entity_terms):
    """Numbers in a focused snippet that exist in the raw text only OUTSIDE the entity's own row.
    Non-empty result = the snippet stitched the entity name to another row's numbers (e.g. 'Burj Khalifa 381 m')."""
    if not snippet or not raw:
        return []
    if not any(_is_table_row(u) for u in entity_units(raw, entity_terms)):
        return []          # prose: sentences are independent; row-stitching only happens in tables
    ent_nums = set()
    for u in entity_units(raw, entity_terms):
        ent_nums |= {round(q[0], 2) for q in parse_quantities(u)}
    other_nums = set()
    for u in split_units(raw):
        if u not in entity_units(raw, entity_terms):
            other_nums |= {round(q[0], 2) for q in parse_quantities(u)}
    bad = []
    for q in parse_quantities(snippet):
        v = round(q[0], 2)
        if v in other_nums and v not in ent_nums:
            bad.append(q[2])
    return bad


# ------------------------------------------------------------------ correction checks (issues 2 and 3)
def _date_of(ev):
    return ev.get("date_in_text") or ev.get("published_date") or ""


def _year(s):
    m = re.findall(r"(?:19|20)\d{2}", s or "")
    return int(m[-1]) if m else None


def entity_year_quantities(evidence, entity_terms, year, kind="count"):
    """Return entity quantities paired with the nearest explicit year in their source unit.

    A single sentence may list historical values and future projections. Pairing every number
    in that sentence with every year can turn a projection into a current estimate, so each
    year is matched to the nearest quantity in the source text.
    """
    out = []
    for ev in evidence or []:
        if _is_ugc(ev):
            continue
        seen = set()
        for text in (ev.get("snippet_raw") or "", ev.get("snippet") or "", ev.get("title") or ""):
            for unit in entity_units(text, entity_terms):
                years = list(re.finditer(r"\b(?:19|20)\d{2}\b", unit))
                quantities = []
                for match in _NUM.finditer(unit):
                    parsed = [q for q in parse_quantities(match.group(0)) if q[1] == kind]
                    if parsed:
                        quantities.append((match.start(), match.end(), parsed[0]))
                for y in years:
                    if int(y.group()) != int(year) or not quantities:
                        continue
                    preceding = [q for q in quantities if q[1] <= y.start() and y.start() - q[1] <= 80]
                    following = [q for q in quantities if q[0] >= y.end() and q[0] - y.end() <= 60]
                    if preceding:
                        q = max(preceding, key=lambda item: item[1])
                    elif following:
                        q = min(following, key=lambda item: item[0])
                    else:
                        continue
                    value, value_kind, raw_value = q[2]
                    marker = (ev.get("url", ""), round(value, 2), int(year))
                    if marker in seen:
                        continue
                    seen.add(marker)
                    context = unit[max(0, q[0] - 90):min(len(unit), y.end() + 40)]
                    if re.search(
                        r"\b(?:project(?:s|ed|ing|ion|ions)?|forecast(?:s|ed|ing)?|expected|expects|"
                        r"plan(?:s|ned|ning)?\s+to|will\s+(?:reach|have|count|be)|"
                        r"could\s+(?:reach|be)|is\s+set\s+to)\b",
                        context, re.I,
                    ) or re.search(r"\b(?:plans?|planned|expected)\b.{0,80}\b(?:census|count)\b", context, re.I):
                        value_type = "projection"
                    elif re.search(r"mid[ -]year", context, re.I):
                        value_type = "mid-year estimate"
                    elif re.search(r"\b(current|live|as of|today)\b", context, re.I):
                        value_type = "current estimate"
                    else:
                        value_type = "estimate"
                    out.append({
                        "value": value, "value_text": raw_value, "kind": value_kind,
                        "year": int(year), "row": context[:240], "url": ev.get("url", ""),
                        "domain": registrable_domain(ev.get("url", "")),
                        "source_type": ev.get("source_type", ""), "date": _date_of(ev),
                        "value_type": value_type, "relevance_score": ev.get("relevance_score"),
                    })
    return out


def current_population_correction(evidence, entity_terms, year):
    """Select a target-year population estimate, preferring official evidence.

    Projection rows are kept for explanation/exclusion but cannot be treated as a current
    estimate. Secondary-only estimates remain explicitly secondary.
    """
    values = [v for v in entity_year_quantities(evidence, entity_terms, year, "count")
              if v["value_type"] != "projection" and
              (v["relevance_score"] is None or v["relevance_score"] >= 0.30)]
    if not values:
        return None
    official = [v for v in values if v["source_type"] in OFFICIAL_TYPES]
    candidates = official or values
    groups = []
    for item in candidates:
        group = next((g for g in groups if abs(item["value"] - g[0]["value"]) /
                      max(abs(item["value"]), abs(g[0]["value"]), 1) <= 0.01), None)
        if group is None:
            groups.append([item])
        else:
            group.append(item)
    selected = max(groups, key=lambda g: (len({x["domain"] for x in g}),
                                           max((x.get("relevance_score") or 0) for x in g)))
    holder = max(selected, key=lambda x: x.get("relevance_score") or 0)
    return {
        "mode": "official_first" if official else "secondary_only",
        "official": bool(official), "year": int(year), "value": holder["value_text"],
        "numeric_value": holder["value"], "value_type": holder["value_type"],
        "sources": selected,
        "note": "" if official else f"No official {year} estimate was retrieved; this is secondary evidence.",
    }


def correction_matches(candidate_text, evidence, entity_terms, tol=0.001):
    """Where does the corrected value appear inside the ENTITY's own row/sentence? Returns
    {'official': [...], 'secondary': [...]} found_in records. Searches ALL retrieved evidence, not only cited URLs."""
    cands = parse_quantities(candidate_text)
    res = {"official": [], "secondary": []}
    if not cands:
        return res
    cv, ckind, _ = cands[0]
    for ev in evidence or []:
        if _is_ugc(ev):
            continue
        texts = [ev.get("snippet_raw") or ""]
        snip = ev.get("snippet") or ""
        if snip and not snippet_cross_row_numbers(snip, ev.get("snippet_raw") or "", entity_terms):
            texts.append(snip)
        hit = None
        for t in texts:
            for u in entity_units(t, entity_terms):
                if any(k == ckind and _close(v, cv, tol) for v, k, _ in parse_quantities(u)):
                    hit = u[:200]
                    break
            if hit:
                break
        if hit:
            rec = {"url": ev.get("url", ""), "domain": registrable_domain(ev.get("url", "")),
                   "source_type": ev.get("source_type", ""), "row": hit, "date": _date_of(ev)}
            res["official" if ev.get("source_type") in OFFICIAL_TYPES else "secondary"].append(rec)
    return res


def correction_check(candidate_text, evidence, entity_terms):
    m = correction_matches(candidate_text, evidence, entity_terms)
    if m["official"]:
        return "supported"
    return "secondary_only" if m["secondary"] else "unsupported"


def choose_correction(candidate_text, evidence, entity_terms, kind="count"):
    """Prefer a relevant institutional population count when a candidate is secondary-only.

    Numeric values are extracted only from the entity's own sentence/table row. Alternative
    measurement series (such as atmospheric ppm readings) and physical measurements with
    potentially different definitions are not substituted merely because their values are close.
    """
    m = correction_matches(candidate_text, evidence, entity_terms)
    if m["official"]:
        return {"mode": "confirmed", "value": candidate_text, "official": True,
                "sources": m["official"], "note": ""}
    candidate = parse_quantities(candidate_text)
    target = candidate[0][0] if candidate else None
    official_vals = []
    for ev in evidence or []:
        if ev.get("source_type") not in OFFICIAL_TYPES:
            continue
        raw = ev.get("snippet_raw") or ev.get("snippet") or ""
        for unit in entity_units(raw, entity_terms):
            for value, value_kind, raw_value in parse_quantities(unit):
                if value_kind != kind:
                    continue
                # A candidate-specific correction must be the same order of magnitude.
                if target is not None and abs(value-target) / max(abs(target), 1) > 0.15:
                    continue
                official_vals.append({"value_text": raw_value, "value": value,
                    "date": _date_of(ev), "url": ev.get("url", ""),
                    "domain": registrable_domain(ev.get("url", "")),
                    "source_type": ev.get("source_type", "")})
    # Keep one best figure per source/value and choose the nearest official value to the candidate.
    dedup = {}
    for item in official_vals:
        dedup[(item["url"], item["value"])] = item
    official_vals = list(dedup.values())
    sec = m["secondary"]
    if not official_vals or kind != "count":
        return {"mode": "secondary_only", "value": candidate_text, "official": False,
                "sources": sec, "note": "Only secondary sources state this figure; no institutional source confirms it."}
    best = min(official_vals, key=lambda x: abs(x["value"] - target) if target is not None else x["value"])
    note = (f"Institutional figure: {best['value_text']} ({best['domain']}, {best['date'] or 'date not stated'}). "
            f"The proposed figure {candidate_text} appears in secondary sources but is not directly confirmed by an institutional source."
            if sec else f"Institutional figure: {best['value_text']} ({best['domain']}, {best['date'] or 'date not stated'}).")
    return {"mode": "official_first", "value": best["value_text"], "official": True,
            "sources": [best], "secondary_estimate": {"value": candidate_text, "sources": sec}, "note": note}


# ------------------------------------------------------------------ single-source honesty (issue 4)
_PLURAL_CUES = re.compile(
    r"\b(sources|studies|agencies|institutions)\b|"
    r"\b(?:recent|official|multiple|several|independent|various|these|those|all|both|other|supplied|counted|secondary)"
    r"\s+(?:estimates|reports)\b|\b(several|multiple|both|various)\b", re.I)


def source_support_summary(result):
    used = result.get("used_urls") or []
    ev = {e.get("url"): e for e in result.get("evidence") or []}
    domains = sorted({registrable_domain(u) for u in used if not _is_ugc(ev.get(u, {"url": u}))})
    official = sorted({registrable_domain(u) for u in used if ev.get(u, {}).get("source_type") in OFFICIAL_TYPES})
    single = len(domains) == 1
    note = ""
    if single and domains:
        kind = "institutional" if official else "independent"
        note = (f"Single-source finding: {len(used)} cited page(s) from one {kind} domain ({domains[0]}). "
                "No second independent source confirms it; treat as provisional.")
    return {"cited_pages": len(used), "independent_domains": domains, "official_domains": official,
            "single_source": single, "note": note}


def explanation_overstates_sources(explanation, independent_domain_count):
    """True when the prose implies several sources/estimates but fewer than two independent domains back it."""
    return independent_domain_count < 2 and bool(_PLURAL_CUES.search(explanation or ""))


def rating_limits(result):
    """Human-readable reasons the rating is not higher: every failed evidence check, plus the single-source note."""
    limits = [c["label"] for c in result.get("evidence_checks", []) if c.get("ok") is False]
    s = source_support_summary(result)
    if s["note"]:
        limits.append(s["note"])
    return limits
