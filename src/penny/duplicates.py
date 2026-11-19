"""Doublons : un rapport en LECTURE SEULE. Rien n'est déplacé ni supprimé ; chaque groupe est une
hypothèse accompagnée de sa preuve.

Trois niveaux de preuve :
  1. identiques  — même empreinte de contenu (SHA-256) : copies exactes, certain ;
  2. probables   — même document sous deux formes (scan et PDF, Word et PDF, v1 et v2) :
                   textes très proches (similarité des vecteurs), documents analysés seulement ;
  3. indices     — même nom et même taille, contenu NON lu (photos, inventaire seul) : à vérifier.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import numpy as np

DEFAULT_THRESHOLD = 0.95


@dataclass
class Group:
    kind: str                 # identiques | probables | indices
    proof: str
    members: list[dict] = field(default_factory=list)

    @property
    def wasted(self) -> int:
        """Place occupée par les copies en trop (toutes sauf une)."""
        sizes = sorted((m["size"] for m in self.members), reverse=True)
        return sum(sizes[1:])


def _where(root: str | None) -> tuple[str, list]:
    sql = "i.gone = 0 AND i.scope != 'ignorer'"
    return (sql + " AND i.root = ?", [root]) if root else (sql, [])


def _member(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "root": r["root"], "path": r["path"], "size": r["size"], "mtime": r["mtime"] or ""}


def exact_groups(conn: sqlite3.Connection, root: str | None = None) -> list[Group]:
    where, args = _where(root)
    rows = conn.execute(
        f"""SELECT i.id, i.root, i.path, i.size, i.mtime, i.hash FROM items i
            WHERE {where} AND i.hash LIKE 'sha256:%' AND i.hash IN (
                SELECT hash FROM items i WHERE {where} AND hash LIKE 'sha256:%'
                GROUP BY hash HAVING COUNT(*) > 1)
            ORDER BY i.hash, i.path""", args + args).fetchall()
    groups: dict[str, Group] = {}
    for r in rows:
        groups.setdefault(r["hash"], Group("identiques", "même contenu (empreinte identique)")).members.append(_member(r))
    return list(groups.values())


def hint_groups(conn: sqlite3.Connection, root: str | None = None) -> list[Group]:
    """Même nom et même taille, quand le contenu n'a pas été lu (empreinte « meta »)."""
    where, args = _where(root)
    rows = conn.execute(
        f"""SELECT i.id, i.root, i.path, i.size, i.mtime, lower(i.name) AS key FROM items i
            WHERE {where} AND i.size > 0 AND i.hash LIKE 'meta:%'
              AND (lower(i.name), i.size) IN (
                SELECT lower(name), size FROM items i WHERE {where} AND size > 0 AND hash LIKE 'meta:%'
                GROUP BY lower(name), size HAVING COUNT(*) > 1)
            ORDER BY key, i.size, i.path""", args + args).fetchall()
    groups: dict[tuple, Group] = {}
    for r in rows:
        groups.setdefault((r["key"], r["size"]), Group(
            "indices", "même nom et même taille — contenu non lu, à vérifier")).members.append(_member(r))
    return list(groups.values())


def similar_groups(conn: sqlite3.Connection, root: str | None = None,
                   threshold: float = DEFAULT_THRESHOLD) -> list[Group]:
    """Documents analysés au texte très proche, hors copies identiques déjà repérées."""
    where, args = _where(root)
    rows = conn.execute(
        f"""SELECT i.id, i.root, i.path, i.size, i.mtime, i.hash, c.embedding FROM chunks c
            JOIN items i ON i.id = c.item_id JOIN processing p ON p.item_id = i.id
            WHERE {where} AND i.scope = 'analyser' AND p.state = 'indexed' AND p.hash = i.hash
              AND c.hash = i.hash ORDER BY i.id, c.ord""", args).fetchall()
    docs: dict[str, dict] = {}
    for r in rows:
        d = docs.setdefault(r["id"], {"row": r, "vecs": []})
        d["vecs"].append(np.frombuffer(r["embedding"], dtype=np.float32))
    if len(docs) < 2:
        return []
    ids = list(docs)
    matrix = np.vstack([np.mean(docs[i]["vecs"], axis=0) for i in ids])
    matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)
    sims = matrix @ matrix.T

    parent = list(range(len(ids)))  # regroupement par union-find

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    best: dict[int, float] = {}
    hashes = [docs[i]["row"]["hash"] for i in ids]
    for a, b in zip(*np.where(np.triu(sims, k=1) >= threshold)):
        if hashes[a] == hashes[b]:
            continue  # copies identiques : déjà dans le premier niveau
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
        best[find(a)] = max(best.get(find(a), 0.0), float(sims[a, b]))

    clusters: dict[int, list[int]] = {}
    for n in range(len(ids)):
        clusters.setdefault(find(n), []).append(n)
    out = []
    for root_n, members in clusters.items():
        if len(members) < 2:
            continue
        low = min(float(sims[a, b]) for a in members for b in members if a < b)
        g = Group("probables", f"textes très proches (similarité {low:.2f} à {best.get(root_n, low):.2f})")
        g.members = [_member(docs[ids[m]]["row"]) for m in members]
        out.append(g)
    return out


def all_groups(conn: sqlite3.Connection, root: str | None = None,
               threshold: float = DEFAULT_THRESHOLD) -> list[Group]:
    return exact_groups(conn, root) + similar_groups(conn, root, threshold) + hint_groups(conn, root)


def summary(groups: list[Group]) -> dict[str, tuple[int, int, int]]:
    """Par type : (groupes, fichiers concernés, octets en trop). Sans aucun nom : transmissible."""
    out: dict[str, tuple[int, int, int]] = {}
    for g in groups:
        n, f, w = out.get(g.kind, (0, 0, 0))
        out[g.kind] = (n + 1, f + len(g.members), w + g.wasted)
    return out
