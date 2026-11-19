"""Doublons : rapport en lecture seule, trois niveaux de preuve."""
from __future__ import annotations

import shutil

import pytest

from conftest import FAKE_FILES, FakeLLM
from penny import cli, db
from penny.decisions import ANALYSE, IGNORE, Decisions
from penny.duplicates import all_groups, exact_groups, hint_groups, similar_groups, summary
from penny.extract import LocalExtractor
from penny.localfolder import LocalFolderSource
from penny.pipeline import Scanner
from penny.report import diag_text

ROOT = "Documents/Administratif"


@pytest.fixture
def dup(tmp_path):
    base = tmp_path / "OneDrive-Personnel"
    top = base / ROOT
    for _, (rel, content) in FAKE_FILES.items():
        (top / rel).parent.mkdir(parents=True, exist_ok=True)
        (top / rel).write_text(content, encoding="utf-8")
    # 1. copie exacte
    (top / "Archives").mkdir()
    shutil.copy(top / "Assurances/attestation-habitation-2026.md", top / "Archives/attestation-copie.md")
    # 2. même document, version légèrement différente
    v2 = (top / "Voitures/controle-technique-2008.txt").read_text(encoding="utf-8").replace(
        "favorable", "favorable sans défaut")
    (top / "Archives/controle-technique-2008-v2.txt").write_text(v2, encoding="utf-8")
    # 3. même nom, même taille, contenu non lu (photos)
    (top / "Photos").mkdir()
    (top / "Photos/IMG_0001.jpg").write_bytes(b"\xff\xd8" + b"a" * 500)
    (top / "Archives/IMG_0001.jpg").write_bytes(b"\xff\xd8" + b"b" * 500)
    conn = db.connect(tmp_path / "data" / "penny.sqlite")
    Decisions(conn, ROOT).set("", ANALYSE)
    scanner = Scanner(conn, LocalFolderSource(base, conn), LocalExtractor(), FakeLLM(),
                      tmp_path / "data/sources", tmp_path / "data/markdown")
    scanner.scan(ROOT)
    yield type("Dup", (), dict(conn=conn, top=top, base=base, tmp=tmp_path, scanner=scanner))
    conn.close()


def paths(group) -> set[str]:
    return {m["path"] for m in group.members}


def test_copies_identiques(dup):
    groups = exact_groups(dup.conn)
    assert len(groups) == 1
    assert paths(groups[0]) == {"Assurances/attestation-habitation-2026.md", "Archives/attestation-copie.md"}
    assert groups[0].wasted > 0


def test_meme_document_formes_differentes(dup):
    # Le faux modèle (sac de mots) est moins fin qu'un vrai : seuil abaissé pour le test.
    # Sur données réelles, le seuil se règle avec --seuil (défaut 0,95).
    groups = similar_groups(dup.conn, threshold=0.9)
    assert any(paths(g) == {"Voitures/controle-technique-2008.txt", "Archives/controle-technique-2008-v2.txt"}
               for g in groups)
    flat = set().union(*(paths(g) for g in groups)) if groups else set()
    assert "Archives/attestation-copie.md" not in flat, "les copies exactes restent au premier niveau"
    assert "Maison/piege.md" not in flat, "un document sans rapport n'est pas regroupé"


def test_indices_meme_nom_meme_taille_sans_lecture(dup):
    groups = hint_groups(dup.conn)
    assert len(groups) == 1 and paths(groups[0]) == {"Photos/IMG_0001.jpg", "Archives/IMG_0001.jpg"}
    assert "à vérifier" in groups[0].proof


def test_dossier_ignore_exclu(dup):
    Decisions(dup.conn, ROOT).set("Archives", IGNORE)
    dup.scanner.scan(ROOT)
    assert exact_groups(dup.conn) == [] and hint_groups(dup.conn) == []


def test_seuil_plus_strict_moins_de_probables(dup):
    assert len(similar_groups(dup.conn, threshold=0.999)) <= len(similar_groups(dup.conn, threshold=0.95))


def test_resume_et_diag_sans_nom(dup):
    stats = summary(all_groups(dup.conn))
    assert stats["identiques"][0] == 1 and stats["indices"][0] == 1
    report = diag_text(dup.conn, "m", "e")
    assert "Doublons : identiques 1 groupes" in report
    assert "attestation" not in report and "IMG_0001" not in report


def test_commande_doublons_ne_modifie_rien(dup, monkeypatch, capsys):
    for key, value in {"PENNY_ALLOW_ANY_USER": "1", "PENNY_DATA_DIR": str(dup.tmp / "data"),
                       "PENNY_CONFIG": str(dup.tmp / "absent.env"), "PENNY_LOCAL_ROOT": str(dup.base)}.items():
        monkeypatch.setenv(key, value)
    before = dup.conn.execute("SELECT COUNT(*), SUM(gone), GROUP_CONCAT(path) FROM items").fetchone()
    cli.main(["doublons"])
    out = capsys.readouterr().out
    assert "COPIES IDENTIQUES" in out and "Rien n'a été modifié" in out
    assert "Archives/attestation-copie.md" in out
    after = dup.conn.execute("SELECT COUNT(*), SUM(gone), GROUP_CONCAT(path) FROM items").fetchone()
    assert tuple(before) == tuple(after)
    assert (dup.top / "Archives/attestation-copie.md").exists()
