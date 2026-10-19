"""Persistance SQLite : briefs versionnés, rendus, contrôles, validations, exports."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import DB_PATH, PROJECT_MARKER, ensure_dirs, to_stored
from .models import Brief

SCHEMA = """
CREATE TABLE IF NOT EXISTS briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brief_key TEXT NOT NULL,
    version INTEGER NOT NULL,
    brand_id TEXT NOT NULL,
    data TEXT NOT NULL,
    change_note TEXT,
    author TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (brief_key, version)
);
CREATE TABLE IF NOT EXISTS renders (
    id TEXT PRIMARY KEY,
    brief_id INTEGER NOT NULL REFERENCES briefs(id),
    template_id TEXT NOT NULL,
    background_source TEXT NOT NULL,
    params TEXT NOT NULL,
    file_path TEXT,
    sha256 TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'error')),
    error TEXT,
    duration_s REAL,
    created_at TEXT NOT NULL,
    batch_id TEXT,
    layout TEXT
);
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    render_id TEXT NOT NULL REFERENCES renders(id),
    name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('conforme', 'anomalie', 'non_concluant')),
    detail TEXT NOT NULL,
    limit_note TEXT
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    render_id TEXT NOT NULL REFERENCES renders(id),
    sha256 TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    reviewer TEXT NOT NULL,
    comment TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    render_id TEXT NOT NULL REFERENCES renders(id),
    approval_id INTEGER NOT NULL REFERENCES approvals(id),
    file_path TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(db_path: Path | None = None):
    ensure_dirs()
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn) -> None:
    """Ajoute les colonnes apparues après la création d'une base existante."""
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(renders)")}
    for name in ("batch_id", "layout"):
        if name not in columns:
            conn.execute(f"ALTER TABLE renders ADD COLUMN {name} TEXT")
    # Anciens chemins absolus (Windows) -> chemins relatifs au projet, lisibles sous WSL comme sous Windows
    for table in ("renders", "exports"):
        for row in conn.execute(f"SELECT rowid, file_path FROM {table} WHERE file_path LIKE '%generation_de_visuel%'"):
            text = row["file_path"].replace("\\", "/")
            conn.execute(f"UPDATE {table} SET file_path = ? WHERE rowid = ?",
                         (text.split(PROJECT_MARKER, 1)[1], row["rowid"]))


# --- Briefs ---------------------------------------------------------------

def create_brief(conn, brief: Brief, author: str | None = None) -> int:
    return _insert_brief(conn, uuid.uuid4().hex[:12], 1, brief, "Création", author)


def revise_brief(conn, brief_key: str, brief: Brief, change_note: str, author: str) -> int:
    if not change_note.strip():
        raise ValueError("Une justification est obligatoire pour modifier un brief.")
    row = conn.execute("SELECT MAX(version) AS v FROM briefs WHERE brief_key = ?", (brief_key,)).fetchone()
    if row["v"] is None:
        raise KeyError(f"Brief inconnu : {brief_key}")
    return _insert_brief(conn, brief_key, row["v"] + 1, brief, change_note, author)


def _insert_brief(conn, key, version, brief: Brief, note, author) -> int:
    cur = conn.execute(
        "INSERT INTO briefs (brief_key, version, brand_id, data, change_note, author, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (key, version, brief.brand_id, brief.model_dump_json(), note, author, now()),
    )
    return cur.lastrowid


def get_brief(conn, brief_id: int) -> tuple[sqlite3.Row, Brief]:
    row = conn.execute("SELECT * FROM briefs WHERE id = ?", (brief_id,)).fetchone()
    if row is None:
        raise KeyError(f"Brief introuvable : {brief_id}")
    return row, Brief.model_validate_json(row["data"])


def brief_versions(conn, brief_key: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM briefs WHERE brief_key = ? ORDER BY version", (brief_key,)
    ).fetchall()


def list_briefs(conn, brand_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT b.* FROM briefs b JOIN (SELECT brief_key, MAX(version) v FROM briefs GROUP BY brief_key) l"
        " ON b.brief_key = l.brief_key AND b.version = l.v WHERE b.brand_id = ? ORDER BY b.created_at DESC",
        (brand_id,),
    ).fetchall()


# --- Rendus et contrôles --------------------------------------------------

def insert_render(conn, render_id, brief_id, template_id, source, params, file_path, sha, status,
                  error=None, duration_s=None, batch_id=None, layout=None) -> None:
    conn.execute(
        "INSERT INTO renders (id, brief_id, template_id, background_source, params, file_path, sha256,"
        " status, error, duration_s, created_at, batch_id, layout) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (render_id, brief_id, template_id, source, json.dumps(params, ensure_ascii=False),
         to_stored(file_path) if file_path else None, sha, status, error, duration_s, now(), batch_id, layout),
    )


def batch_renders(conn, batch_id: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM renders WHERE batch_id = ? ORDER BY rowid", (batch_id,)).fetchall()


def insert_checks(conn, render_id: str, results) -> None:
    conn.executemany(
        "INSERT INTO checks (render_id, name, status, detail, limit_note) VALUES (?, ?, ?, ?, ?)",
        [(render_id, r.name, r.status, r.detail, r.limit) for r in results],
    )


def get_render(conn, render_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM renders WHERE id = ?", (render_id,)).fetchone()
    if row is None:
        raise KeyError(f"Rendu introuvable : {render_id}")
    return row


def get_checks(conn, render_id: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM checks WHERE render_id = ? ORDER BY id", (render_id,)).fetchall()


def list_renders(conn, brand_id: str | None = None) -> list[sqlite3.Row]:
    sql = ("SELECT r.*, b.brief_key, b.version AS brief_version, b.brand_id, b.data AS brief_data FROM renders r"
           " JOIN briefs b ON b.id = r.brief_id")
    args = ()
    if brand_id:
        sql += " WHERE b.brand_id = ?"
        args = (brand_id,)
    return conn.execute(sql + " ORDER BY r.created_at DESC", args).fetchall()


def recent_series_params(conn, brand_id: str, series: str, limit: int = 3) -> list[dict]:
    rows = conn.execute(
        "SELECT r.params FROM renders r JOIN briefs b ON b.id = r.brief_id"
        " WHERE b.brand_id = ? AND json_extract(b.data, '$.series') = ? AND r.status != 'error'"
        " ORDER BY r.created_at DESC LIMIT ?",
        (brand_id, series, limit),
    ).fetchall()
    return [json.loads(r["params"]) for r in rows]


# --- Validation et export -------------------------------------------------

def insert_approval(conn, render_id, sha, decision, reviewer, comment) -> int:
    cur = conn.execute(
        "INSERT INTO approvals (render_id, sha256, decision, reviewer, comment, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (render_id, sha, decision, reviewer, comment, now()),
    )
    conn.execute("UPDATE renders SET status = ? WHERE id = ?", (decision, render_id))
    return cur.lastrowid


def missing_render_files(conn) -> list[sqlite3.Row]:
    """Rendus enregistrés dont le fichier n'existe plus (ex. dossier nettoyé à la main)."""
    from .config import from_stored
    rows = conn.execute("SELECT * FROM renders WHERE file_path IS NOT NULL").fetchall()
    return [r for r in rows if not from_stored(r["file_path"]).exists()]


def prune_missing_renders(conn) -> tuple[int, int]:
    """Retire de la base les rendus sans fichier, avec leurs contrôles et décisions.

    Un rendu déjà exporté est conservé : la trace de son approbation ne doit pas disparaître.
    Renvoie (rendus retirés, rendus exportés conservés).
    """
    removed = kept = 0
    for r in missing_render_files(conn):
        if conn.execute("SELECT 1 FROM exports WHERE render_id = ?", (r["id"],)).fetchone():
            kept += 1
            continue
        conn.execute("DELETE FROM checks WHERE render_id = ?", (r["id"],))
        conn.execute("DELETE FROM approvals WHERE render_id = ?", (r["id"],))
        conn.execute("DELETE FROM renders WHERE id = ?", (r["id"],))
        removed += 1
    return removed, kept


def latest_approval(conn, render_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM approvals WHERE render_id = ? ORDER BY id DESC LIMIT 1", (render_id,)
    ).fetchone()


def insert_export(conn, render_id, approval_id, file_path) -> None:
    conn.execute(
        "INSERT INTO exports (render_id, approval_id, file_path, created_at) VALUES (?, ?, ?, ?)",
        (render_id, approval_id, to_stored(file_path), now()),
    )
