"""Source « dossier local » (OneDrive synchronisé sur le Mac) : réussite et échec."""
from __future__ import annotations

import os
import shutil

import pytest

from conftest import FAKE_FILES, FakeLLM, states
from penny import cli, db
from penny.extract import LocalExtractor
from penny.localfolder import LocalFolderSource, SourceError
from penny.pipeline import Scanner
from penny.search import Searcher

ROOT = "Documents/Administratif"


@pytest.fixture
def local(tmp_path):
    base = tmp_path / "OneDrive-Personnel"
    top = base / ROOT
    for _, (rel, content) in FAKE_FILES.items():
        (top / rel).parent.mkdir(parents=True, exist_ok=True)
        (top / rel).write_text(content, encoding="utf-8")
    (top / ".DS_Store").write_text("x")
    (top / "Assurances" / "~$verrou.docx").write_text("x")
    (base / "Secret").mkdir()
    (base / "Secret" / "identite.txt").write_text("Carte d'identité n° 123456789012, inventée. " * 3)
    conn = db.connect(tmp_path / "data" / "penny.sqlite")
    source = LocalFolderSource(base, conn)
    llm = FakeLLM()
    scanner = Scanner(conn, source, LocalExtractor(), llm, tmp_path / "data/sources", tmp_path / "data/markdown")
    yield type("Local", (), dict(base=base, top=top, conn=conn, source=source, llm=llm, scanner=scanner, tmp=tmp_path))
    conn.close()


def test_analyse_sur_place_sans_copie(local):
    rep = local.scanner.scan(ROOT)
    assert rep.listed == 9, "fichiers cachés et verrous Office ignorés"
    assert sum(s == "indexed" for s in states(local.conn).values()) == 6
    assert not (local.tmp / "data/sources").exists(), "aucune copie des fichiers"
    assert all(i.startswith("local:") for i in states(local.conn))


def test_relance_ne_relit_pas_les_fichiers_inchanges(local, monkeypatch):
    local.scanner.scan(ROOT)
    import penny.localfolder as lf
    calls = []
    monkeypatch.setattr(lf, "sha256_of", lambda p: calls.append(p) or "sha256:x")
    rep = local.scanner.scan(ROOT)
    assert calls == [] and (rep.new, rep.changed, rep.moved, rep.processed) == (0, 0, 0, 0)


def test_renommage_modification_suppression(local):
    local.scanner.scan(ROOT)
    ids_before = {r["path"]: r["id"] for r in local.conn.execute("SELECT id, path FROM items")}
    # renommé et déplacé
    (local.top / "Archives").mkdir()
    shutil.move(local.top / "Voitures/carte-grise-megane.md", local.top / "Archives/megane.md")
    # modifié (taille différente)
    with open(local.top / "Voitures/controle-technique-2008.txt", "a", encoding="utf-8") as fh:
        fh.write(" Contre-visite inutile.")
    # supprimé
    os.remove(local.top / "Maison/facture-vitreauto.md")
    cards = local.llm.cards
    rep = local.scanner.scan(ROOT)
    assert (rep.moved, rep.changed, rep.gone, rep.new) == (1, 1, 1, 0)
    assert local.llm.cards == cards + 1, "seul le fichier modifié est réanalysé"
    row = local.conn.execute("SELECT id FROM items WHERE path = 'Archives/megane.md'").fetchone()
    assert row["id"] == ids_before["Voitures/carte-grise-megane.md"], "le déplacé garde son identifiant"
    hits = Searcher(local.conn, local.llm).retrieve("immatriculation Mégane AB-123-CD")
    assert any(p.path.endswith("Archives/megane.md") for p in hits)


def test_hors_du_dossier_autorise_refuse(local):
    for bad in ("../Secret", "/etc", "Documents/../../Secret"):
        with pytest.raises(SourceError):
            local.source.list_files(bad)


def test_lien_symbolique_vers_l_exterieur_ignore(local):
    (local.top / "raccourci.txt").symlink_to(local.base / "Secret" / "identite.txt")
    rep = local.scanner.scan(ROOT)
    assert rep.listed == 9
    assert not local.conn.execute("SELECT 1 FROM chunks WHERE text LIKE '%123456789012%'").fetchone()


def test_dossier_illisible_message_clair(local):
    with pytest.raises(SourceError, match="ne peut pas lire"):
        local.source.list_files("Inexistant")


def test_fichier_a_la_demande_illisible_n_arrete_pas_le_scan(local, monkeypatch):
    original = LocalExtractor.to_markdown
    def flaky(self, path):
        if path.name == "attestation-habitation-2026.md":
            raise OSError(35, "Resource deadlock avoided")  # erreur typique d'un fichier non téléchargé
        return original(self, path)
    monkeypatch.setattr(LocalExtractor, "to_markdown", flaky)
    rep = local.scanner.scan(ROOT)
    assert rep.errors == 1 and rep.processed == 5


def test_cli_source_locale(local, monkeypatch, capsys):
    for key, value in {"PENNY_ALLOW_ANY_USER": "1", "PENNY_DATA_DIR": str(local.tmp / "cli"),
                       "PENNY_CONFIG": str(local.tmp / "absent.env"), "PENNY_LOCAL_ROOT": str(local.base),
                       "PENNY_OLLAMA_URL": "http://127.0.0.1:1"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("PENNY_SOURCE", raising=False)
    cli.main(["onedrive", "check"])
    assert "Source : local" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="aucune connexion"):
        cli.main(["onedrive", "connect"])
