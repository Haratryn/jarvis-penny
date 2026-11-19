"""OCR (--ocr) : seuls les fichiers sans texte sont repris ; une photo sans texte ne l'est qu'une fois.
Apple Vision n'existe pas hors Mac : le moteur est remplacé par un faux, la logique de Penny est réelle."""
from __future__ import annotations

import pytest

from conftest import FakeLLM, states
from penny import db
from penny.decisions import ANALYSE, Decisions
from penny.extract import LocalExtractor
from penny.localfolder import LocalFolderSource
from penny.pipeline import Scanner

ROOT = "Papiers"
SCAN_TEXT = "Facture n° 2026-118 du 2026-02-03. Garage du Pont. Remplacement des plaquettes. Total 245,00 euros TTC."
OCR_RESULTS = {
    "facture-scan.pdf": SCAN_TEXT,
    "ticket.jpg": "Ticket de caisse Sportéo Villeneuve 2026-05-14 : chaussures de course 89,99 euros, total 89,99 euros.",
    "carte.heic": "Carte grise inventée : immatriculation ZZ-999-ZZ, première immatriculation 2024-01-10, titulaire fictif.",
    "plage.jpg": "",
}


@pytest.fixture
def ocr(tmp_path, monkeypatch):
    base = tmp_path / "OneDrive-Personnel"
    top = base / ROOT
    (top / "Scans").mkdir(parents=True)
    (top / "Photos").mkdir()
    (top / "Scans/facture-scan.pdf").write_bytes(b"%PDF-1.4 scan sans texte")
    (top / "Photos/ticket.jpg").write_bytes(b"\xff\xd8 ticket")
    (top / "Photos/plage.jpg").write_bytes(b"\xff\xd8 plage")
    (top / "Photos/carte.heic").write_bytes(b"heic carte")
    (top / "note.txt").write_text("Note texte inventée, assez longue pour être considérée comme lisible. " * 2)

    calls = []

    class FakeDoc:
        def __init__(self, text):
            self.document = type("D", (), {"export_to_markdown": lambda s: text})()

    class NoTextConverter:  # Docling sans OCR : un scan ne donne aucun texte
        def convert(self, path):
            return FakeDoc("<!-- image -->")

    monkeypatch.setattr(LocalExtractor, "_docling", lambda self: NoTextConverter())
    monkeypatch.setattr(LocalExtractor, "_ocr_text",
                        lambda self, path: calls.append(path.name) or OCR_RESULTS[path.name])
    conn = db.connect(tmp_path / "data" / "penny.sqlite")
    Decisions(conn, ROOT).set("", ANALYSE)
    llm = FakeLLM()
    scanner = Scanner(conn, LocalFolderSource(base, conn), LocalExtractor(), llm,
                      tmp_path / "data/sources", tmp_path / "data/markdown")
    yield type("O", (), dict(conn=conn, scanner=scanner, calls=calls, llm=llm))
    conn.close()


def by_name(conn) -> dict[str, tuple[str, str]]:
    return {r[0].split("/")[-1]: (r[1], r[2]) for r in conn.execute(
        "SELECT i.path, p.state, p.reason FROM items i JOIN processing p ON p.item_id = i.id")}


def test_sans_ocr_scans_et_images_en_attente(ocr):
    ocr.scanner.scan(ROOT)
    s = by_name(ocr.conn)
    assert s["facture-scan.pdf"] == ("no_text", "sans_texte")
    assert s["ticket.jpg"] == ("no_text", "image") and s["carte.heic"] == ("no_text", "image")
    assert s["note.txt"][0] == "indexed"
    assert ocr.calls == [], "pas d'OCR sans --ocr"


def test_ocr_lit_scans_et_documents_photographies(ocr):
    ocr.scanner.scan(ROOT)
    ocr.scanner.ocr = True
    rep = ocr.scanner.scan(ROOT)
    s = by_name(ocr.conn)
    assert s["facture-scan.pdf"][0] == "indexed"
    assert s["ticket.jpg"][0] == "indexed" and s["carte.heic"][0] == "indexed"
    assert s["plage.jpg"] == ("no_text", "photo_sans_texte"), "une vraie photo reste une photo"
    assert sorted(ocr.calls) == ["carte.heic", "facture-scan.pdf", "plage.jpg", "ticket.jpg"]
    assert rep.processed == 3
    card = ocr.conn.execute("SELECT c.doc_date FROM cards c JOIN items i ON i.id = c.item_id "
                            "WHERE i.path LIKE '%facture-scan.pdf'").fetchone()
    assert card["doc_date"] == "2026-02-03"


def test_ocr_ne_reprend_pas_ce_qui_est_fait(ocr):
    ocr.scanner.ocr = True
    ocr.scanner.scan(ROOT)
    n, cards = len(ocr.calls), ocr.llm.cards
    rep = ocr.scanner.scan(ROOT)
    assert len(ocr.calls) == n and ocr.llm.cards == cards and rep.processed == 0
    ocr.scanner.ocr = False
    ocr.scanner.scan(ROOT)
    assert by_name(ocr.conn)["ticket.jpg"][0] == "indexed", "les acquis restent sans --ocr"


def test_ocr_et_limite(ocr):
    ocr.scanner.scan(ROOT)
    ocr.scanner.ocr = True
    rep = ocr.scanner.scan(ROOT, limit=2)
    assert len(ocr.calls) == 2 and rep.remaining == 2


def test_ocr_indisponible_hors_mac(monkeypatch, tmp_path):
    import penny.extract as ex
    monkeypatch.setattr(ex.sys, "platform", "linux")
    img = tmp_path / "x.jpg"
    img.write_bytes(b"\xff\xd8")
    with pytest.raises(ex.Unsupported, match="hors_mac"):
        LocalExtractor().to_markdown(img, ocr=True)
