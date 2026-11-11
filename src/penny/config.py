"""Configuration de Penny.

Ordre de priorité : variables d'environnement, puis fichier ~/.config/penny/penny.env
(ou celui désigné par PENNY_CONFIG), puis valeurs par défaut.
Aucun secret ici : le mot de passe de la configuration rclone vient du trousseau
(PENNY_RCLONE_PASSWORD_COMMAND) ou est demandé à l'écran.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@dataclass(frozen=True)
class Config:
    data_dir: Path
    ollama_url: str
    llm_model: str
    embed_model: str
    rclone_bin: str
    rclone_remote: str
    rclone_config: Path
    rclone_password_command: str
    max_file_mb: int

    @property
    def db_path(self) -> Path:
        return self.data_dir / "penny.sqlite"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "sources"

    @property
    def markdown_dir(self) -> Path:
        return self.data_dir / "markdown"


def load_config() -> Config:
    home = Path.home()
    file_values = _read_env_file(Path(os.environ.get("PENNY_CONFIG", home / ".config/penny/penny.env")))

    def get(key: str, default: str) -> str:
        return os.environ.get(key) or file_values.get(key) or default

    data_dir = Path(get("PENNY_DATA_DIR", str(home / "penny-data"))).expanduser()
    return Config(
        data_dir=data_dir,
        ollama_url=get("PENNY_OLLAMA_URL", "http://127.0.0.1:11435").rstrip("/"),
        llm_model=get("PENNY_LLM_MODEL", "qwen3:8b"),
        embed_model=get("PENNY_EMBED_MODEL", "bge-m3"),
        rclone_bin=get("PENNY_RCLONE_BIN", "rclone"),
        rclone_remote=get("PENNY_RCLONE_REMOTE", "penny-onedrive"),
        rclone_config=Path(get("PENNY_RCLONE_CONFIG", str(home / ".config/penny/rclone.conf"))).expanduser(),
        rclone_password_command=get("PENNY_RCLONE_PASSWORD_COMMAND", ""),
        max_file_mb=int(get("PENNY_MAX_FILE_MB", "50")),
    )
