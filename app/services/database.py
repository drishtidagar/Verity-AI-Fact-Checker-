import json
import sqlite3
from contextlib import contextmanager
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.config import DB_PATH

VERDICT_KEYS = ["VERIFIED", "INACCURATE", "FALSE", "INSUFFICIENT EVIDENCE", "AI REVIEW FAILED", "SEARCH FAILED"]


@contextmanager
def db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def init_db():
    with db() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS audits(
            id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT, created_at TEXT, page_count INTEGER,
            claims_found INTEGER, filtered_candidates INTEGER, summary_json TEXT, findings_json TEXT,
            session_id TEXT)"""
        )
        # Migrate databases created by v1.0 (no session_id column).
        cols = {r["name"] for r in c.execute("PRAGMA table_info(audits)").fetchall()}
        if "session_id" not in cols:
            c.execute("ALTER TABLE audits ADD COLUMN session_id TEXT")


def summary(findings):
    return {k: sum(1 for x in findings if x["result"].get("verdict") == k) for k in VERDICT_KEYS}


def save_audit(filename, audit, session_id=""):
    created = datetime.now(timezone.utc).isoformat()
    findings = audit["findings"]
    counts = summary(findings)
    with db() as c:
        cur = c.execute(
            "INSERT INTO audits(filename,created_at,page_count,claims_found,filtered_candidates,"
            "summary_json,findings_json,session_id) VALUES(?,?,?,?,?,?,?,?)",
            (filename, created, audit["page_count"], audit["claims_found"], audit["filtered_candidates"],
             json.dumps(counts), json.dumps(findings), session_id),
        )
        return cur.lastrowid


def update_findings(aid, findings, session_id=None):
    """Replace the findings of an existing audit (used when failed claims are retried) and
    recompute its verdict summary. Nothing else about the audit changes."""
    counts = json.dumps(summary(findings))
    with db() as c:
        if session_id is None:
            c.execute("UPDATE audits SET findings_json=?, summary_json=? WHERE id=?",
                      (json.dumps(findings), counts, aid))
        else:
            c.execute("UPDATE audits SET findings_json=?, summary_json=? WHERE id=? AND session_id=?",
                      (json.dumps(findings), counts, aid, session_id))


def list_audits(session_id=None):
    """Audits for one browser session. Passing None returns everything (admin/tests only)."""
    with db() as c:
        if session_id is None:
            rows = c.execute("SELECT * FROM audits ORDER BY id DESC").fetchall()
        else:
            rows = c.execute("SELECT * FROM audits WHERE session_id=? ORDER BY id DESC", (session_id,)).fetchall()
    return [dict(x) for x in rows]


def get_audit(aid, session_id=None):
    with db() as c:
        if session_id is None:
            row = c.execute("SELECT * FROM audits WHERE id=?", (aid,)).fetchone()
        else:
            row = c.execute("SELECT * FROM audits WHERE id=? AND session_id=?", (aid, session_id)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["summary"] = json.loads(d.pop("summary_json"))
    d["findings"] = json.loads(d.pop("findings_json"))
    return d


def delete_audit(aid, session_id=None):
    with db() as c:
        if session_id is None:
            c.execute("DELETE FROM audits WHERE id=?", (aid,))
        else:
            c.execute("DELETE FROM audits WHERE id=? AND session_id=?", (aid, session_id))


def totals(rows):
    result = Counter()
    for r in rows:
        result.update(json.loads(r["summary_json"]))
    return dict(result)
