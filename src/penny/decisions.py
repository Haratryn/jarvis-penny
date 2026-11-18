"""Décisions de l'utilisateur sur les dossiers : analyser, inventaire seul, ignorer.

Couche « décisions de l'utilisateur » : conservée dans la base ET exportée dans un fichier
lisible (decisions/dossiers.md), indépendant du moteur de mémoire.

Règles :
  - une décision sur un dossier vaut pour tous ses sous-dossiers, sauf décision plus précise ;
  - une décision « fichiers seulement » ne vaut que pour les fichiers posés directement dans le
    dossier (cas d'un dossier dont on a décidé les sous-dossiers un par un) ;
  - sans décision : « à décider » — Penny inventorie mais ne lit rien.
Les décisions sont rattachées au chemin du dossier, relatif au dossier analysé (root).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ANALYSE, INVENTAIRE, IGNORE, A_DECIDER = "analyser", "inventaire", "ignorer", "a_decider"
DECISIONS = (ANALYSE, INVENTAIRE, IGNORE)
LABELS = {ANALYSE: "Analyser", INVENTAIRE: "Inventaire seul", IGNORE: "Ignorer", A_DECIDER: "À décider"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS folder_decisions (
    root        TEXT NOT NULL,
    folder      TEXT NOT NULL,             -- relatif à root ; '' = le dossier analysé lui-même
    files_only  INTEGER NOT NULL DEFAULT 0, -- 1 : seulement les fichiers posés directement dans folder
    decision    TEXT NOT NULL CHECK (decision IN ('analyser', 'inventaire', 'ignorer')),
    decided_at  TEXT NOT NULL,
    PRIMARY KEY (root, folder, files_only)
);
"""


def norm(folder: str) -> str:
    folder = str(PurePosixPath(folder.strip("/"))) if folder.strip("/") else ""
    return "" if folder == "." else folder


class Decisions:
    """Décisions d'un dossier analysé, chargées en mémoire pour décider vite fichier par fichier."""

    def __init__(self, conn: sqlite3.Connection, root: str):
        self.conn, self.root = conn, root
        self.reload()

    def reload(self) -> None:
        rows = self.conn.execute(
            "SELECT folder, files_only, decision FROM folder_decisions WHERE root = ?", (self.root,)).fetchall()
        self.full = {r["folder"]: r["decision"] for r in rows if not r["files_only"]}
        self.files = {r["folder"]: r["decision"] for r in rows if r["files_only"]}

    def for_folder(self, folder: str) -> str:
        """Décision qui s'applique à un dossier (et donc à ses sous-dossiers sans décision propre)."""
        parts = PurePosixPath(norm(folder)).parts if norm(folder) else ()
        for n in range(len(parts), -1, -1):
            key = "/".join(parts[:n])
            if key in self.full:
                return self.full[key]
        return A_DECIDER

    def for_file(self, rel_path: str) -> str:
        parent = norm(str(PurePosixPath(rel_path).parent))
        if parent in self.files:
            return self.files[parent]
        return self.for_folder(parent)

    def is_ignored_dir(self, rel_dir: str) -> bool:
        return self.for_folder(rel_dir) == IGNORE

    def set(self, folder: str, decision: str | None, files_only: bool = False) -> None:
        folder = norm(folder)
        if decision is None:
            self.conn.execute("DELETE FROM folder_decisions WHERE root = ? AND folder = ? AND files_only = ?",
                              (self.root, folder, int(files_only)))
        else:
            assert decision in DECISIONS
            self.conn.execute(
                "INSERT OR REPLACE INTO folder_decisions(root, folder, files_only, decision, decided_at)"
                " VALUES (?,?,?,?,?)",
                (self.root, folder, int(files_only), decision,
                 datetime.now(timezone.utc).isoformat(timespec="seconds")))
        self.conn.commit()
        self.reload()


def apply_scope(conn: sqlite3.Connection, root: str, decisions: "Decisions | None" = None) -> None:
    """Recalcule la décision effective (items.scope) de chaque fichier du dossier analysé."""
    decisions = decisions or Decisions(conn, root)
    rows = conn.execute("SELECT id, path, scope FROM items WHERE root = ?", (root,)).fetchall()
    updates = [(scope, r["id"]) for r in rows if (scope := decisions.for_file(r["path"])) != r["scope"]]
    conn.executemany("UPDATE items SET scope = ? WHERE id = ?", updates)
    conn.commit()


def scope_counts(conn: sqlite3.Connection, root: str) -> dict[str, int]:
    return {r[0]: r[1] for r in conn.execute(
        "SELECT scope, COUNT(*) FROM items WHERE root = ? AND gone = 0 GROUP BY scope", (root,))}


def export_markdown(conn: sqlite3.Connection, path: Path) -> None:
    """Journal lisible de toutes les décisions (réutilisable si l'on change d'outil)."""
    lines = ["# Décisions de dossiers (Penny)", "",
             "Généré automatiquement à chaque décision. Règle : une décision vaut pour les sous-dossiers,",
             "sauf décision plus précise ; « fichiers seulement » ne concerne que les fichiers posés",
             "directement dans le dossier.", ""]
    for root in [r[0] for r in conn.execute("SELECT DISTINCT root FROM folder_decisions ORDER BY root")]:
        lines += [f"## {root}", "", "| Dossier | Décision | Portée | Date |", "|---|---|---|---|"]
        for r in conn.execute("SELECT folder, files_only, decision, decided_at FROM folder_decisions "
                              "WHERE root = ? ORDER BY folder, files_only", (root,)):
            lines.append(f"| {r['folder'] or '(dossier entier)'} | {LABELS[r['decision']]} | "
                         f"{'fichiers seulement' if r['files_only'] else 'avec sous-dossiers'} | "
                         f"{r['decided_at'][:10]} |")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def folder_stats(conn: sqlite3.Connection, root: str, parent: str) -> tuple[list[dict], dict]:
    """Sous-dossiers directs de `parent` avec nombre de fichiers, taille, types et date la plus récente,
    d'après le seul inventaire. Renvoie aussi les mêmes chiffres pour les fichiers posés directement
    dans `parent`."""
    parent = norm(parent)
    prefix = f"{parent}/" if parent else ""
    rows = conn.execute("SELECT path, ext, size, mtime FROM items WHERE root = ? AND gone = 0 AND path LIKE ?",
                        (root, prefix.replace("%", "\\%").replace("_", "\\_") + "%")).fetchall()
    groups: dict[str, list] = {}
    loose: list = []
    for r in rows:
        rest = r["path"][len(prefix):]
        if "/" in rest:
            groups.setdefault(rest.split("/", 1)[0], []).append(r)
        else:
            loose.append(r)

    def summary(items: list) -> dict:
        exts: dict[str, int] = {}
        for it in items:
            exts[it["ext"] or "(aucune)"] = exts.get(it["ext"] or "(aucune)", 0) + 1
        top = sorted(exts.items(), key=lambda x: -x[1])[:3]
        total = len(items) or 1
        return {"files": len(items), "size": sum(it["size"] for it in items),
                "types": ", ".join(f"{e.lstrip('.')} {round(100 * n / total)} %" for e, n in top),
                "latest": max((it["mtime"] or "")[:7] for it in items) if items else ""}

    out = []
    for name in sorted(groups, key=str.lower):
        folder = f"{prefix}{name}"
        out.append({"name": name, "folder": folder, **summary(groups[name])})
    return out, summary(loose)


def human_size(n: int) -> str:
    for unit in ("o", "Ko", "Mo", "Go"):
        if n < 1024 or unit == "Go":
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return str(n)
