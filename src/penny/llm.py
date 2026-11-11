"""Accès au modèle local (Ollama, 127.0.0.1). Aucun autre fournisseur n'est prévu."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Protocol
from urllib.parse import urlparse

import numpy as np


class LLM(Protocol):
    model: str
    embed_model: str

    def embed(self, texts: list[str]) -> np.ndarray: ...
    def chat_json(self, system: str, user: str, schema: dict) -> dict: ...
    def chat(self, system: str, user: str) -> str: ...


class LLMError(RuntimeError):
    pass


class Ollama:
    def __init__(self, url: str, model: str, embed_model: str, timeout: int = 600):
        host = urlparse(url).hostname
        # Règle du projet : jamais de modèle hors de la machine.
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise LLMError(f"PENNY_OLLAMA_URL doit pointer vers la machine locale (actuel : {host})")
        self.url, self.model, self.embed_model, self.timeout = url, model, embed_model, timeout

    def _post(self, path: str, payload: dict) -> dict:
        req = urllib.request.Request(self.url + path, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.URLError as exc:
            raise LLMError(f"Ollama injoignable sur {self.url} ({exc.__class__.__name__})") from exc

    def embed(self, texts: list[str]) -> np.ndarray:
        out = self._post("/api/embed", {"model": self.embed_model, "input": texts})
        vecs = np.asarray(out["embeddings"], dtype=np.float32)
        return vecs / np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-12)

    def chat_json(self, system: str, user: str, schema: dict) -> dict:
        out = self._post("/api/chat", {
            "model": self.model, "stream": False, "format": schema, "think": False,
            "options": {"temperature": 0},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        })
        try:
            return json.loads(out["message"]["content"])
        except (KeyError, json.JSONDecodeError) as exc:
            raise LLMError("réponse JSON invalide du modèle") from exc

    def chat(self, system: str, user: str) -> str:
        out = self._post("/api/chat", {
            "model": self.model, "stream": False, "think": False, "options": {"temperature": 0},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        })
        return out["message"]["content"].strip()
