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
            options.ocr_options = OcrMacOptions(lang=OCR_LANGS)
            self._ocr_converter = DocumentConverter(format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=options),
                InputFormat.IMAGE: ImageFormatOption(pipeline_options=options)})
        return self._ocr_converter

    def _ocr_text(self, path: Path) -> str:
        ext = path.suffix.lower()
        if ext == ".heic":  # non pris en charge par Docling : conversion locale par sips (macOS)
            with tempfile.TemporaryDirectory(prefix="penny-ocr-") as tmp:
                jpg = Path(tmp) / "image.jpg"
                res = subprocess.run(["sips", "-s", "format", "jpeg", str(path), "--out", str(jpg)],
                                     capture_output=True, text=True, check=False)
                if res.returncode != 0 or not jpg.exists():
                    raise Unsupported("conversion_heic_impossible")
                return self._ocr().convert(str(jpg)).document.export_to_markdown()
        if ext not in DOCLING_IMAGE_EXT and ext != ".pdf":
            raise Unsupported("format_image_non_pris_en_charge")
        return self._ocr().convert(str(path)).document.export_to_markdown()

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
            text = self._ocr_text(path)
            if not meaningful(text, MIN_OCR_IMAGE_CHARS):
                raise NoText("photo_sans_texte")
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
                raise NoText("ocr_sans_texte")
            raise NoText("sans_texte")
        return text
