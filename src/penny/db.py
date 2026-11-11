"""Base SQLite de Penny.

Couches (cf. CLAUDE.md) :
  - sources     : items (identifiant OneDrive stable, chemin courant, empreinte)
  - mémoire     : cards (fiche par document), chunks (passages + vecteurs, plein texte)
  - corrections : réservé (incrément 2), indépendant du moteur
Toute donnée extraite est rattachée à (item_id, hash) : si la source change, elle est refaite.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS items (
    id          TEXT PRIMARY KEY,          -- identifiant OneDrive (stable au renommage/déplacement)
    root        TEXT NOT NULL,             -- dossier analysé
    path        TEXT NOT NULL,             -- chemin courant, relatif à root
    name        TEXT NOT NULL,
    ext         TEXT NOT NULL,
    size        INTEGER NOT NULL,
    mtime       TEXT,
    hash        TEXT NOT NULL,             -- empreinte OneDrive (QuickXorHash) ou repli
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    gone        INTEGER NOT NULL DEFAULT 0 -- disparu de OneDrive au dernier inventaire
);
CREATE INDEX IF NOT EXISTS items_root ON items(root);

CREATE TABLE IF NOT EXISTS processing (
    item_id     TEXT PRIMARY KEY REFERENCES items(id),
    hash        TEXT NOT NULL,             -- version traitée
    state       TEXT NOT NULL,             -- listed|downloaded|extracted|carded|indexed|no_text|skipped|error
    reason      TEXT,                      -- code (jamais de contenu ni de nom de fichier)
    attempts    INTEGER NOT NULL DEFAULT 0,
    local_path  TEXT,
    md_path     TEXT,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cards (
    item_id     TEXT PRIMARY KEY REFERENCES items(id),
    hash        TEXT NOT NULL,
    doc_type    TEXT,
    doc_date    TEXT,
    title       TEXT,
    parties     TEXT,                      -- JSON : personnes et organismes
    subject     TEXT,
    summary     TEXT,
    model       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY,
    item_id     TEXT NOT NULL REFERENCES items(id),
    hash        TEXT NOT NULL,
    ord         INTEGER NOT NULL,
    text        TEXT NOT NULL,
    embedding   BLOB NOT NULL,             -- float32 normalisé
    model       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_item ON chunks(item_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, tokenize = 'unicode61 remove_diacritics 2');

CREATE TABLE IF NOT EXISTS timings (
    step        TEXT NOT NULL,
    seconds     REAL NOT NULL,
    at          TEXT NOT NULL
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    conn.commit()
    return conn


def forget_extraction(conn: sqlite3.Connection, item_id: str) -> None:
    """Efface la mémoire extraite d'un document (jamais la source)."""
    ids = [r[0] for r in conn.execute("SELECT id FROM chunks WHERE item_id = ?", (item_id,))]
    conn.executemany("DELETE FROM chunks_fts WHERE rowid = ?", [(i,) for i in ids])
    conn.execute("DELETE FROM chunks WHERE item_id = ?", (item_id,))
    conn.execute("DELETE FROM cards WHERE item_id = ?", (item_id,))
