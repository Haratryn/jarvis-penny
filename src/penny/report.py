"""État de la mémoire et diagnostic anonymisé.

`diag` est le SEUL rapport que l'utilisateur peut transmettre à une IA externe (Claude) :
il ne contient que des compteurs, des extensions, des codes d'erreur et des durées —
jamais de nom de fichier, de chemin, de titre ni de contenu.
"""
from __future__ import annotations

import platform
import sqlite3

from . import __version__

STATE_LABELS = {
    "indexed": "analysés",
    "no_text": "sans texte (scan ou photo, en attente d'OCR)",
    "skipped": "ignorés",
    "error": "en erreur",
    "listed": "en attente",
    "downloaded": "en cours (téléchargés)",
    "extracted": "en cours (texte extrait)",
    "carded": "en cours (fiche faite)",
    None: "en attente",
}
REASON_LABELS = {
    "format_non_pris_en_charge": "format non pris en charge",
    "trop_volumineux": "trop volumineux",
    "docling_absent": "extracteur absent",
    "image": "image",
    "sans_texte": "PDF sans texte",
}


def state_counts(conn: sqlite3.Connection, root: str | None = None) -> list[sqlite3.Row]:
    where = "WHERE i.gone = 0" + (" AND i.root = ?" if root else "")
    return conn.execute(
        f"""SELECT i.root,
                   CASE WHEN p.hash = i.hash THEN p.state END AS state,
                   CASE WHEN p.hash = i.hash THEN p.reason END AS reason,
                   COUNT(*) AS n
            FROM items i LEFT JOIN processing p ON p.item_id = i.id {where}
            GROUP BY 1, 2, 3 ORDER BY 1, 2, 3""", [root] if root else []).fetchall()


def status_text(conn: sqlite3.Connection, root: str | None = None) -> str:
    rows = state_counts(conn, root)
    if not rows:
        return "Aucun dossier analysé. Lancer : penny scan \"<dossier>\""
    lines, current = [], None
    totals: dict[str, int] = {}
    for r in rows:
        if r["root"] != current:
            current = r["root"]
            listed = sum(x["n"] for x in rows if x["root"] == current)
            gone = conn.execute("SELECT COUNT(*) FROM items WHERE root = ? AND gone = 1", (current,)).fetchone()[0]
            lines.append(f"« {current} » : {listed} fichiers listés" + (f", {gone} disparus de OneDrive" if gone else ""))
        label = STATE_LABELS.get(r["state"], r["state"])
        reason = f" — {REASON_LABELS.get(r['reason'], r['reason'])}" if r["reason"] and r["state"] in ("skipped", "error", "no_text") else ""
        lines.append(f"    {r['n']:>6}  {label}{reason}")
        totals[label] = totals.get(label, 0) + r["n"]
    return "\n".join(lines)


def diag_text(conn: sqlite3.Connection, llm_model: str, embed_model: str) -> str:
    """Rapport anonymisé : compteurs uniquement."""
    out = [f"Penny {__version__} — {platform.system()} {platform.machine()}",
           f"Modèles : génération {llm_model}, vecteurs {embed_model}",
           f"Dossiers analysés : {conn.execute('SELECT COUNT(DISTINCT root) FROM items').fetchone()[0]}",
           "Fichiers par état :"]
    for r in conn.execute(
            """SELECT CASE WHEN p.hash = i.hash THEN p.state ELSE 'listed' END AS state,
                      CASE WHEN p.hash = i.hash THEN p.reason END AS reason, COUNT(*) AS n
               FROM items i LEFT JOIN processing p ON p.item_id = i.id WHERE i.gone = 0
               GROUP BY 1, 2 ORDER BY 3 DESC"""):
        out.append(f"    {r['n']:>6}  {r['state']}" + (f" ({r['reason']})" if r["reason"] else ""))
    out.append("Extensions (fichiers présents) :")
    for r in conn.execute("SELECT ext, COUNT(*) AS n FROM items WHERE gone = 0 GROUP BY ext ORDER BY n DESC LIMIT 15"):
        out.append(f"    {r['n']:>6}  {r['ext'] or '(aucune)'}")
    hashes = conn.execute(
        "SELECT substr(hash, 1, instr(hash, ':') - 1) AS kind, COUNT(*) AS n FROM items GROUP BY kind").fetchall()
    out.append("Empreintes : " + ", ".join(f"{r['kind']} {r['n']}" for r in hashes))
    out.append("Durées moyennes par étape (s) :")
    for r in conn.execute("SELECT step, COUNT(*) AS n, AVG(seconds) AS avg, MAX(seconds) AS mx FROM timings GROUP BY step"):
        out.append(f"    {r['step']:<9} n={r['n']:<6} moyenne={r['avg']:.1f} max={r['mx']:.1f}")
    out.append(f"Passages indexés : {conn.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]}")
    return "\n".join(out)
