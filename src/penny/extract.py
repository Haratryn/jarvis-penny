"""Extraction locale du texte des documents vers Markdown.

- texte brut (.txt, .md, .csv) : lu directement ;
- PDF, Word, PowerPoint, Excel, HTML : Docling, OCR désactivé (incrément 1) ;
- images et PDF sans texte : « en attente d'OCR », signalés explicitement ;
- autres formats : ignorés avec un motif.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

TEXT_EXT = {".txt", ".md", ".csv"}
DOCLING_EXT = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff", ".webp", ".bmp"}
MIN_TEXT_CHARS = 40


class Unsupported(Exception):
    """Format non pris en charge : le fichier est ignoré avec ce motif (code)."""


class NoText(Exception):
    """Aucun texte exploitable (scan, photo) : en attente d'OCR."""


class Extractor(Protocol):
    def to_markdown(self, path: Path) -> str: ...


def meaningful(text: str) -> bool:
    cleaned = re.sub(r"<!--.*?-->|[#|*\-_\s]", "", text)
    return len(cleaned) >= MIN_TEXT_CHARS


class LocalExtractor:
    def __init__(self) -> None:
        self._converter = None

    def _docling(self):
        if self._converter is None:
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

    def to_markdown(self, path: Path) -> str:
        ext = path.suffix.lower()
        if ext in IMAGE_EXT:
            raise NoText("image")
        if ext in TEXT_EXT:
            text = path.read_text(encoding="utf-8", errors="replace")
        elif ext in DOCLING_EXT:
            text = self._docling().convert(str(path)).document.export_to_markdown()
        else:
            raise Unsupported("format_non_pris_en_charge")
        if not meaningful(text):
            raise NoText("sans_texte")
        return text
