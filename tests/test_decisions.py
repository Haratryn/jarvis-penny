"""Décisions par dossier : rien n'est lu sans accord, dossiers ignorés jamais parcourus."""
from __future__ import annotations

import pytest

from conftest import FAKE_FILES, FakeLLM, states
from penny import cli, db
from penny.decisions import ANALYSE, IGNORE, INVENTAIRE, Decisions, export_markdown, folder_stats
from penny.extract import LocalExtractor
from penny.localfolder import LocalFolderSource
from penny.pipeline import Scanner
from penny.report import status_text
from penny.search import Searcher, perimeter

ROOT = "Documents/Administratif"


@pytest.fixture
def lf(tmp_path, monkeypatch):
    base = tmp_path / "OneDrive-Personnel"
    top = base / ROOT
    for _, (rel, content) in FAKE_FILES.items():
        (top / rel).parent.mkdir(parents=True, exist_ok=True)
        (top / rel).write_text(content, encoding="utf-8")
    conn = db.connect(tmp_path / "data" / "penny.sqlite")
    llm = FakeLLM()
    scanner = Scanner(conn, LocalFolderSource(base, conn), LocalExtractor(), llm,
                      tmp_path / "data/sources", tmp_path / "data/markdown")
    import penny.localfolder as lfmod
    reads = []
    real = lfmod.sha256_of
    monkeypatch.setattr(lfmod, "sha256_of", lambda p: reads.append(str(p)) or real(p))
    yield type("LF", (), dict(base=base, top=top, conn=conn, llm=llm, scanner=scanner, tmp=tmp_path,
                              reads=reads, dec=Decisions(conn, ROOT)))
    conn.close()


def scopes(conn) -> dict[str, str]:
    return {r[0]: r[1] for r in conn.execute("SELECT path, scope FROM items")}


def test_sans_decision_rien_n_est_lu(lf):
    rep = lf.scanner.scan(ROOT)
    assert rep.listed == 9 and rep.processed == 0
    assert lf.reads == [], "aucun fichier ouvert pour calculer une empreinte"
    assert lf.llm.cards == 0 and states(lf.conn) == {}
    assert set(scopes(lf.conn).values()) == {"a_decider"}
    assert "9 à décider" in status_text(lf.conn, ROOT) and "penny dossiers" in status_text(lf.conn, ROOT)


def test_inventaire_seul_ne_lit_pas_les_fichiers(lf):
    lf.dec.set("", INVENTAIRE)
    rep = lf.scanner.scan(ROOT)
    assert rep.listed == 9 and rep.processed == 0 and lf.reads == []
    assert set(scopes(lf.conn).values()) == {"inventaire"}


def test_dossier_ignore_jamais_parcouru(lf):
    lf.dec.set("", ANALYSE)
    lf.dec.set("Voitures", IGNORE)
    rep = lf.scanner.scan(ROOT)
    assert rep.listed == 7, "les 2 fichiers de Voitures ne sont pas listés"
    assert not any("Voitures" in p for p in lf.reads)
    assert "Voitures/carte-grise-megane.md" not in scopes(lf.conn)


def test_decision_heritee_et_affinee(lf):
    lf.dec.set("", ANALYSE)
    lf.dec.set("Divers", INVENTAIRE)
    lf.scanner.scan(ROOT)
    s = scopes(lf.conn)
    assert s["Assurances/avis-echeance-auto-2027.md"] == "analyser"
    assert s["Divers/presque-vide.txt"] == "inventaire"
    assert not any("presque-vide" in p for p in lf.reads)


def test_fichiers_seulement(lf):
    (lf.top / "note-racine.txt").write_text("Note posée à la racine du dossier, inventée pour le test. " * 3)
    lf.dec.set("", ANALYSE)
    lf.dec.set("", INVENTAIRE, files_only=True)
    lf.scanner.scan(ROOT)
    s = scopes(lf.conn)
    assert s["note-racine.txt"] == "inventaire" and s["Maison/piege.md"] == "analyser"


def test_changer_d_avis_retire_puis_restaure_sans_reanalyse(lf):
    lf.dec.set("", ANALYSE)
    lf.scanner.scan(ROOT)
    searcher = Searcher(lf.conn, lf.llm)
    assert any("carte-grise" in p.path for p in searcher.retrieve("immatriculation Mégane AB-123-CD"))
    cards = lf.llm.cards

    lf.dec.set("Voitures", IGNORE)
    rep = lf.scanner.scan(ROOT)
    assert rep.gone == 0, "un dossier ignoré n'est pas « disparu »"
    assert not any("carte-grise" in p.path for p in searcher.retrieve("immatriculation Mégane AB-123-CD"))
    assert "non consultés" in perimeter(lf.conn, ROOT)

    lf.dec.set("Voitures", None)   # annuler : la décision du dossier entier (analyser) s'applique de nouveau
    rep = lf.scanner.scan(ROOT)
    assert rep.processed == 0 and lf.llm.cards == cards, "rien n'est réanalysé"
    assert any("carte-grise" in p.path for p in searcher.retrieve("immatriculation Mégane AB-123-CD"))


def test_export_lisible_et_statistiques(lf):
    lf.dec.set("", ANALYSE)
    lf.dec.set("Divers", INVENTAIRE)
    path = lf.tmp / "data" / "decisions" / "dossiers.md"
    export_markdown(lf.conn, path)
    text = path.read_text(encoding="utf-8")
    assert "| Divers | Inventaire seul | avec sous-dossiers |" in text
    lf.scanner.scan(ROOT)
    subs, loose = folder_stats(lf.conn, ROOT, "")
    assert [s["name"] for s in subs] == ["Assurances", "Divers", "Maison", "Voitures"]
    assert next(s for s in subs if s["name"] == "Divers")["files"] == 3


def test_revue_interactive(lf, monkeypatch, capsys):
    for key, value in {"PENNY_ALLOW_ANY_USER": "1", "PENNY_DATA_DIR": str(lf.tmp / "data"),
                       "PENNY_CONFIG": str(lf.tmp / "absent.env"), "PENNY_LOCAL_ROOT": str(lf.base),
                       "PENNY_OLLAMA_URL": "http://127.0.0.1:1"}.items():
        monkeypatch.setenv(key, value)
    # dossier entier : décider un par un ; Assurances analyser, Divers ignorer,
    # Maison : descendre (aucun sous-dossier) puis ses fichiers en inventaire, Voitures : plus tard
    answers = iter(["", "", "x", "d", "i", "p"])  # Entrée = décider un par un, puis Entrée = analyser
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    cli.main(["dossiers", ROOT])
    out = capsys.readouterr().out
    assert "Assurances" in out and "Journal des décisions" in out
    dec = Decisions(lf.conn, ROOT)
    assert dec.for_folder("Assurances") == ANALYSE and dec.for_folder("Divers") == IGNORE
    assert dec.for_file("Maison/facture-vitreauto.md") == INVENTAIRE
    assert dec.for_folder("Voitures") == "a_decider"
    assert (lf.tmp / "data" / "decisions" / "dossiers.md").exists()
    cli.main(["dossiers", ROOT, "--liste"])
    assert "Ignorer" in capsys.readouterr().out
