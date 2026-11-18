"""Affichage de l'avancement d'un scan.

Aucun nom de fichier n'est affiché : les lignes peuvent être copiées telles quelles
(à Claude, par exemple) sans divulguer de donnée.
"""
from __future__ import annotations

import sys
import time

STEP_LABELS = {
    "read": "lecture",
    "extract": "extraction du texte",
    "card": "fiche (modèle local)",
    "index": "indexation",
}


def duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min {seconds % 60:02d} s"
    return f"{seconds // 3600} h {seconds % 3600 // 60:02d} min"


class Progress:
    def __init__(self, stream=None, every: int = 10):
        self.stream = stream or sys.stderr
        self.tty = hasattr(self.stream, "isatty") and self.stream.isatty()
        self.every = every
        self.start = time.monotonic()
        self.total = 0
        self.n = 0
        self.ext = ""
        self.step = ""
        self.done = {"indexed": 0, "no_text": 0, "skipped": 0, "error": 0}
        self.doc_seconds: list[float] = []  # durée des documents réellement analysés
        self._doc_start = 0.0

    def planned(self, pending: int, limit: int | None) -> None:
        self.total = pending if limit is None else min(pending, limit)
        self.start = time.monotonic()
        print(f"À analyser ce passage : {self.total} fichiers (sur {pending} en attente)", file=self.stream)

    def file_start(self, n: int, ext: str) -> None:
        self.n, self.ext, self.step = n, ext or "?", ""
        self._doc_start = time.monotonic()
        self._render()

    def step_start(self, step: str) -> None:
        self.step = STEP_LABELS.get(step, step)
        self._render()

    def file_done(self, outcome: str) -> None:
        self.done[outcome] = self.done.get(outcome, 0) + 1
        if outcome == "indexed":
            self.doc_seconds.append(time.monotonic() - self._doc_start)
        self.step = ""
        if not self.tty and (self.n % self.every == 0 or self.n == self.total):
            self._render(force_line=True)

    def line(self) -> str:
        elapsed = time.monotonic() - self.start
        parts = [f"[{self.n}/{self.total}]"]
        if self.step:
            parts.append(f"{self.ext} : {self.step}")
        parts.append(f"écoulé {duration(elapsed)}")
        if self.doc_seconds:
            avg = sum(self.doc_seconds) / len(self.doc_seconds)
            # Estimation : documents restants au rythme moyen (les fichiers sans texte sont quasi instantanés)
            remaining = max(self.total - self.n, 0) * avg
            parts.append(f"moyenne {avg:.0f} s/doc")
            parts.append(f"reste ~{duration(remaining)}")
        d = self.done
        parts.append(f"analysés {d['indexed']}, sans texte {d['no_text']}, ignorés {d['skipped']}, erreurs {d['error']}")
        return " — ".join(parts)

    def _render(self, force_line: bool = False) -> None:
        if self.tty:
            text = self.line()
            print("\r\033[K" + text, end="", file=self.stream, flush=True)
        elif force_line:
            print(self.line(), file=self.stream, flush=True)

    def finish(self) -> None:
        if self.tty and self.total:
            print("\r\033[K" + self.line(), file=self.stream, flush=True)
        print(f"Durée du passage : {duration(time.monotonic() - self.start)}", file=self.stream)
