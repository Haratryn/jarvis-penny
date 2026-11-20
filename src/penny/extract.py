"""Extraction locale du texte des documents vers Markdown.

- texte brut (.txt, .md, .csv) : lu directement ;
- PDF, Word, PowerPoint, Excel, HTML : Docling, sans OCR (rapide) ;
- images et PDF sans texte : « en attente d'OCR » ; avec ocr=True, lus par Apple Vision
  (OCR local de macOS, via Docling et ocrmac) — les HEIC sont d'abord convertis par sips ;
- une image où l'OCR trouve trop peu de texte est une photo : « sans texte » définitivement ;
- autres formats : ignorés avec un motif.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Protocol

TEXT_EXT = {".txt", ".md", ".csv"}
DOCLING_EXT = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff", ".webp", ".bmp"}
MIN_TEXT_CHARS = 40
MIN_OCR_IMAGE_CHARS = 80   # en dessous, une image est une photo (paysage, personnes…), pas un document
DOCLING_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
OCR_LANGS = ["fr-FR", "en-US"]


class Unsupported(Exception):
    """Format non pris en charge : le fichier est ignoré avec ce motif (code)."""


class NoText(Exception):
    """Aucun texte exploitable (scan, photo) : en attente d'OCR."""


class Extractor(Protocol):
    def to_markdown(self, path: Path, ocr: bool = False) -> str: ...


def meaningful(text: str, minimum: int = MIN_TEXT_CHARS) -> bool:
    cleaned = re.sub(r"<!--.*?-->|[#|*\-_\s]", "", text)
    return len(cleaned) >= minimum


def quiet_libraries() -> None:
    """Masque barres de progression et avertissements des bibliothèques d'IA."""
    import logging
    import os
    import warnings
    for key, value in {"TQDM_DISABLE": "1", "HF_HUB_DISABLE_PROGRESS_BARS": "1",
                       "TRANSFORMERS_VERBOSITY": "error", "TORCH_CPP_LOG_LEVEL": "ERROR",
                       "TOKENIZERS_PARALLELISM": "false"}.items():
        os.environ.setdefault(key, value)
    warnings.filterwarnings("ignore")
    for name in ("docling", "torch", "transformers", "huggingface_hub", "rapidocr", "easyocr"):
        logging.getLogger(name).setLevel(logging.ERROR)


def page_text(lines: list) -> str:
    """Remet les lignes reconnues dans l'ordre de lecture : de haut en bas, puis de gauche à droite.
    Coordonnées Apple Vision : origine en bas à gauche, donc haut de ligne = y + h."""
    rows = []
    for text, _conf, box in lines:
        x, y, w, h = box
        rows.append((round(1 - (y + h), 2), x, str(text).strip()))
    return "\n".join(t for _, _, t in sorted(rows) if t)


def render_pdf_pages(path: Path, scale: float = 3.0, max_pages: int = 30) -> list:
    """Pages d'un PDF en images (pypdfium2, déjà installé avec Docling)."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(path))
    try:
        return [pdf[i].render(scale=scale).to_pil() for i in range(min(len(pdf), max_pages))]
    finally:
        pdf.close()


class LocalExtractor:
    def __init__(self) -> None:
        self._converter = None
        self._ocr_converter = None

    def _ocr(self):
        """Convertisseur Docling avec OCR Apple Vision (PDF scannés et images)."""
        if self._ocr_converter is None:
            if sys.platform != "darwin":
                raise Unsupported("ocr_indisponible_hors_mac")
            quiet_libraries()
            try:
                from docling.datamodel.base_models import InputFormat
                from docling.datamodel.pipeline_options import OcrMacOptions, PdfPipelineOptions
                from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption
            except ImportError as exc:
                raise Unsupported("ocr_absent") from exc
            options = PdfPipelineOptions()
            options.do_ocr = True
            # Page entière : sinon le texte situé dans une zone classée « image » (carte d'identité
            # scannée sur une page, document photographié) est lu puis écarté (constaté le 20/11).
            try:
                from docling.datamodel.pipeline_options import OcrMode
                options.ocr_options = OcrMacOptions(lang=OCR_LANGS, mode=OcrMode.FULL_PAGE)
            except ImportError:
                options.ocr_options = OcrMacOptions(lang=OCR_LANGS, force_full_page_ocr=True)
            self._ocr_converter = DocumentConverter(format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=options),
                InputFormat.IMAGE: ImageFormatOption(pipeline_options=options)})
        return self._ocr_converter

    def _ocr_text(self, path: Path, minimum: int = MIN_TEXT_CHARS) -> str:
        """1. Docling + Apple Vision en page entière (garde la mise en forme) ;
        2. si le résultat est trop maigre : Apple Vision directement, texte brut ligne par ligne."""
        ext = path.suffix.lower()
        if ext == ".heic":  # non pris en charge par Docling : conversion locale par sips (macOS)
            with tempfile.TemporaryDirectory(prefix="penny-ocr-") as tmp:
                jpg = Path(tmp) / "image.jpg"
                res = subprocess.run(["sips", "-s", "format", "jpeg", str(path), "--out", str(jpg)],
                                     capture_output=True, text=True, check=False)
                if res.returncode != 0 or not jpg.exists():
                    raise Unsupported("conversion_heic_impossible")
                return self._ocr_text(jpg, minimum)
        if ext not in DOCLING_IMAGE_EXT and ext != ".pdf":
            raise Unsupported("format_image_non_pris_en_charge")
        text = self._ocr().convert(str(path)).document.export_to_markdown()
        if meaningful(text, minimum):
            return text
        raw = self._vision_raw(path)
        return raw if meaningful(raw, minimum) else text

    def _vision_lines(self, image) -> list:
        """Apple Vision via ocrmac : [(texte, confiance, [x, y, l, h])], coordonnées relatives,
        origine en bas à gauche (vérifié dans le code source d'ocrmac 1.0.1)."""
        if sys.platform != "darwin":
            raise Unsupported("ocr_indisponible_hors_mac")
        try:
            from ocrmac.ocrmac import text_from_image
        except ImportError as exc:
            raise Unsupported("ocr_absent") from exc
        return text_from_image(image, recognition_level="accurate", language_preference=OCR_LANGS)

    def _vision_raw(self, path: Path) -> str:
        """Texte brut par Apple Vision, page par page (PDF rendus en images par pypdfium2)."""
        from PIL import Image
        if path.suffix.lower() == ".pdf":
            pages = [page_text(self._vision_lines(img)) for img in render_pdf_pages(path)]
            return "\n\n".join(p for p in pages if p)
        with Image.open(path) as img:
            return page_text(self._vision_lines(img.convert("RGB")))

    def _docling(self):
        if self._converter is None:
            quiet_libraries()
            try:
                from docling.datamodel.base_models import InputFormat
                from docling.datamodel.pipeline_options import PdfPipelineOptions
                from docling.document_converter import (
                    DocumentConverter,
                    PdfFormatOption,
                )
            except ImportError as exc:
                raise Unsupported("docling_absent") from exc
            options = PdfPipelineOptions()
            options.do_ocr = False  # OCR : incrément ultérieur
            self._converter = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
        return self._converter

    def to_markdown(self, path: Path, ocr: bool = False) -> str:
        ext = path.suffix.lower()
        if ext in IMAGE_EXT:
            if not ocr:
                raise NoText("image")
            text = self._ocr_text(path, MIN_OCR_IMAGE_CHARS)
            if not meaningful(text, MIN_OCR_IMAGE_CHARS):
                raise NoText("photo_vide")
            return text
        if ext in TEXT_EXT:
            text = path.read_text(encoding="utf-8", errors="replace")
        elif ext in DOCLING_EXT:
            text = self._docling().convert(str(path)).document.export_to_markdown()
        else:
            raise Unsupported("format_non_pris_en_charge")
        if not meaningful(text):
            if ocr and ext == ".pdf":
                text = self._ocr_text(path)
                if meaningful(text):
                    return text
                raise NoText("ocr_vide")
            raise NoText("sans_texte")
        return text
