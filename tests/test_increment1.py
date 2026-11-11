"""Incrément 1 : analyser un dossier, l'inventorier, répondre avec des sources vérifiées.
Tests de réussite ET d'échec, sur un faux OneDrive."""
from __future__ import annotations

import pytest
from conftest import ROOT, states

from penny.llm import LLMError, Ollama
from penny.pipeline import chunk_text
from penny.report import diag_text, status_text
from penny.search import NOT_FOUND, Searcher, cards_listing


def test_inventaire_complet_et_statut_pour_chaque_fichier(env):
    rep = env.scanner.scan(ROOT)
    assert rep.listed == 9 and rep.new == 9
    st = states(env.conn)
    assert len(st) == 9, "chaque fichier listé doit avoir un statut"
    assert [st[i] for i in ("ID!101", "ID!102", "ID!103", "ID!104", "ID!105", "ID!106")] == ["indexed"] * 6
    assert st["ID!107"] == "no_text"      # image : en attente d'OCR
    assert st["ID!109"] == "no_text"      # texte insignifiant
    assert st["ID!108"] == "skipped"      # format non pris en charge
    assert rep.remaining == 0


def test_relance_ne_refait_rien(env):
    env.scanner.scan(ROOT)
    downloads, cards = len(env.source.downloads), env.llm.cards
    rep = env.scanner.scan(ROOT)
    assert (rep.new, rep.changed, rep.processed) == (0, 0, 0)
    assert len(env.source.downloads) == downloads and env.llm.cards == cards


def test_limite_puis_reprise(env):
    rep = env.scanner.scan(ROOT, limit=3)
    assert rep.processed + rep.no_text + rep.skipped == 3 and rep.remaining == 6
    rep = env.scanner.scan(ROOT)
    assert rep.remaining == 0 and len(env.source.downloads) == 9  # rien téléchargé deux fois


def test_modification_renommage_disparition(env):
    env.scanner.scan(ROOT)
    path, content = env.source.files["ID!104"]
    env.source.files["ID!104"] = (path, content + " Contre-visite inutile.")      # modifié
    env.source.files["ID!103"] = ("Archives/megane-carte-grise.md", env.source.files["ID!103"][1])  # déplacé
    del env.source.files["ID!105"]                                                   # supprimé
    cards = env.llm.cards
    rep = env.scanner.scan(ROOT)
    assert (rep.changed, rep.moved, rep.gone, rep.processed) == (1, 1, 1, 1)
    assert env.llm.cards == cards + 1, "seul le fichier modifié est réanalysé"
    row = env.conn.execute("SELECT path FROM items WHERE id = 'ID!103'").fetchone()
    assert row["path"] == "Archives/megane-carte-grise.md"
    ans = Searcher(env.conn, env.llm).retrieve("immatriculation Mégane AB-123-CD")
    assert any(p.item_id == "ID!103" and p.path.endswith("Archives/megane-carte-grise.md") for p in ans)
    assert all(p.item_id != "ID!105" for p in Searcher(env.conn, env.llm).retrieve("pare-brise VitreAuto"))


def test_erreur_de_telechargement_puis_reprise(env):
    env.source.fail_on = {"ID!102"}
    rep = env.scanner.scan(ROOT)
    assert rep.errors == 1 and states(env.conn)["ID!102"] == "error"
    env.source.fail_on = set()
    rep = env.scanner.scan(ROOT)
    assert rep.processed == 1 and states(env.conn)["ID!102"] == "indexed"


def test_reponse_avec_sources_verifiees_et_perimetre(env):
    env.scanner.scan(ROOT)
    ans = Searcher(env.conn, env.llm).ask("Quelle est l'immatriculation de la Mégane ?")
    assert "[1]" in ans.text and "[42]" not in ans.text, "une source inventée doit être retirée"
    assert len(ans.sources) == 1
    assert "6 documents analysés sur 9" in ans.perimeter
    assert "sans texte" in ans.perimeter and "peut exister ailleurs" in ans.perimeter


def test_question_sans_rapport_ne_fabrique_pas_de_source(env):
    env.scanner.scan(ROOT)
    ans = Searcher(env.conn, env.llm).ask("xylophone zeppelin quasar")
    assert ans.text == NOT_FOUND and ans.sources == []


def test_reponse_sans_citation_est_signalee(env):
    env.scanner.scan(ROOT)
    env.llm.answer = "Le contrat est résilié."
    ans = Searcher(env.conn, env.llm).ask("Mon contrat d'assurance habitation ?")
    assert "sans source vérifiable" in ans.text


def test_fiches_et_inventaire(env):
    env.scanner.scan(ROOT)
    rows = cards_listing(env.conn, ROOT, None, False)
    assert len(rows) == 9
    att = next(r for r in rows if r["path"].endswith("attestation-habitation-2026.md"))
    assert att["doc_type"] == "attestation" and att["doc_date"] == "2026-04-01"
    piege = next(r for r in rows if r["path"].endswith("piege.md"))
    assert piege["doc_date"] is None, "une date invalide renvoyée par le modèle est écartée"
    assert len(cards_listing(env.conn, ROOT, None, True)) == 2  # sans texte


def test_diag_ne_contient_aucun_nom_ni_contenu(env):
    env.scanner.scan(ROOT)
    report = diag_text(env.conn, "m", "e")
    for _, (path, content) in env.source.files.items():
        for word in path.replace("/", " ").replace(".", " ").split():
            if len(word) > 4:
                assert word not in report, f"le diagnostic divulgue « {word} »"
    assert "Horizon" not in report and "AB-123-CD" not in report
    assert "indexed" in report and ".md" in report


def test_status_lisible(env):
    assert "Aucun dossier" in status_text(env.conn)
    env.scanner.scan(ROOT)
    text = status_text(env.conn, ROOT)
    assert "9 fichiers listés" in text and "analysés" in text and "OCR" in text


def test_ollama_refuse_un_serveur_distant():
    with pytest.raises(LLMError):
        Ollama("http://192.168.1.20:11434", "m", "e")
    with pytest.raises(LLMError):
        Ollama("https://api.example.com", "m", "e")
    Ollama("http://127.0.0.1:11435", "m", "e")


def test_decoupage():
    text = "\n\n".join(f"Paragraphe {i} " + "mot " * 60 for i in range(20))
    chunks = chunk_text(text)
    assert len(chunks) > 3 and all(len(c) <= 1500 for c in chunks)
    assert chunk_text("x" * 5000) and all(len(c) <= 1200 for c in chunk_text("x" * 5000))


def test_erreur_inattendue_d_extraction_n_arrete_pas_le_scan(env):
    class Boom:
        def to_markdown(self, path):
            if path.suffix == ".txt":
                raise ConnectionError("modèles Docling non téléchargeables")
            from penny.extract import LocalExtractor
            return LocalExtractor().to_markdown(path)
    env.scanner.extractor = Boom()
    rep = env.scanner.scan(ROOT)
    assert rep.errors == 2 and rep.error_codes == {"ConnectionError": 2}
    assert rep.processed == 5
