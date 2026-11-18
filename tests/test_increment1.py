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
    # --limit ne compte que les documents à lire : image et zip sont classés hors limite
    assert rep.skipped == 1 and rep.no_text >= 1 and rep.processed + rep.no_text + rep.skipped == 5
    assert rep.remaining == 4
    rep = env.scanner.scan(ROOT)
    assert rep.remaining == 0 and len(env.source.downloads) == 7  # rien téléchargé deux fois


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


def test_images_et_formats_non_pris_en_charge_ne_sont_pas_telecharges(env):
    env.scanner.scan(ROOT)
    assert "ID!107" not in env.source.downloads   # image
    assert "ID!108" not in env.source.downloads   # zip
    assert "ID!109" in env.source.downloads       # texte (vide, mais lisible)
    reasons = dict(env.conn.execute("SELECT item_id, reason FROM processing").fetchall())
    assert reasons["ID!107"] == "image" and reasons["ID!108"] == "format_non_pris_en_charge"


def test_avancement_sans_nom_de_fichier(env):
    import io
    from penny.progress import Progress
    out = io.StringIO()
    progress = Progress(stream=out, every=1)
    env.scanner.scan(ROOT, progress=progress)
    progress.finish()
    text = out.getvalue()
    assert "Classés d'après leur format, sans lecture : 2 fichiers" in text
    assert "À analyser ce passage : 7 documents" in text
    assert "[7/7]" in text and "analysés 6, sans texte 1, ignorés 0, erreurs 0" in text
    assert "moyenne" in text and "reste" in text and "Durée du passage" in text
    for _, (path, _) in env.source.files.items():
        assert path.split("/")[-1] not in text, "aucun nom de fichier dans l'avancement"


def test_avancement_avec_limite(env):
    import io
    from penny.progress import Progress
    out = io.StringIO()
    env.scanner.scan(ROOT, limit=3, progress=Progress(stream=out, every=1))
    assert "À analyser ce passage : 3 documents (sur 7 en attente)" in out.getvalue()


def test_consultation_pendant_un_scan(env, tmp_path):
    """Un scan qui écrit ne bloque pas status / docs / ask (constaté sur le Mac le 18/11)."""
    from penny import db as pdb
    env.scanner.scan(ROOT, limit=3)
    path = env.tmp / "data" / "penny.sqlite"
    env.conn.execute("BEGIN IMMEDIATE")          # le scan tient le verrou d'écriture
    env.conn.execute("UPDATE items SET size = size WHERE id = 'ID!101'")
    reader = pdb.connect(path, readonly=True)
    try:
        assert "9 fichiers listés" in status_text(reader, ROOT)
        assert cards_listing(reader, ROOT, None, False)
        Searcher(reader, env.llm).retrieve("Mégane")
    finally:
        reader.close()
        env.conn.rollback()


def test_aucun_verrou_pendant_les_appels_au_modele(env):
    from penny import db as pdb
    path = env.tmp / "data" / "penny.sqlite"
    seen = []
    original = env.llm.embed

    def embed_and_check(texts):
        other = pdb.connect(path)               # un autre écrivain doit pouvoir écrire maintenant
        other.execute("PRAGMA busy_timeout = 0")
        other.execute("INSERT INTO timings(step, seconds, at) VALUES ('test', 0, 'x')")
        other.commit()
        other.close()
        seen.append(True)
        return original(texts)
    env.llm.embed = embed_and_check
    env.scanner.scan(ROOT, limit=2)
    assert seen


def test_detail_des_erreurs_local_mais_pas_dans_diag(env):
    env.source.fail_on = {"ID!102"}
    env.scanner.scan(ROOT)
    rows = cards_listing(env.conn, ROOT, None, False, "error")
    assert len(rows) == 1 and rows[0]["reason"] == "OneDriveError" and "simulation" in rows[0]["detail"]
    report = diag_text(env.conn, "m", "e")
    assert "simulation" not in report and "avis-echeance" not in report
    assert "Erreurs par extension" in report and "OneDriveError" in report
    assert "Ignorés par extension" in report and ".zip" in report
    assert len(cards_listing(env.conn, ROOT, None, False, "skipped")) == 1


def test_avancement_detaille_sur_demande(env):
    import io
    from penny.progress import Progress
    out = io.StringIO()
    env.scanner.scan(ROOT, progress=Progress(stream=out, every=1, details=True))
    text = out.getvalue()
    assert "analysé" in text and "Voitures/carte-grise-megane.md" in text
    assert "attestation, 2026-04-01" in text and "sans texte" in text
