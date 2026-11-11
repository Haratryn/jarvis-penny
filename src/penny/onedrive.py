"""Accès à OneDrive par rclone, en lecture seule.

rclone fournit l'identifiant OneDrive de chaque fichier (stable au renommage et au
déplacement) et son empreinte QuickXorHash. Penny n'utilise que des commandes de lecture
(lsjson, copyto vers le disque local) ; le jeton lui-même est limité à la lecture
(access_scopes), donc Microsoft refuserait toute écriture.
"""
from __future__ import annotations

import getpass
import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol


@dataclass(frozen=True)
class RemoteFile:
    id: str
    path: str      # relatif au dossier analysé
    name: str
    size: int
    mtime: str
    hash: str


class Source(Protocol):
    def list_files(self, root: str) -> list[RemoteFile]: ...
    def download(self, root: str, item: RemoteFile, dest: Path) -> None: ...


class OneDriveError(RuntimeError):
    pass


def _hash_of(entry: dict) -> str:
    hashes = entry.get("Hashes") or {}
    for key in ("quickxor", "sha1", "sha256"):
        if hashes.get(key):
            return f"{key}:{hashes[key]}"
    # Repli : taille + date (moins fiable, signalé dans le diagnostic)
    return f"meta:{entry.get('Size')}:{entry.get('ModTime')}"


class RcloneOneDrive:
    def __init__(self, rclone_bin: str, remote: str, config: Path, password_command: str = ""):
        self.bin, self.remote, self.config = rclone_bin, remote, config
        self.password_command = password_command
        self._env: dict[str, str] | None = None

    def _environment(self) -> dict[str, str]:
        """Mot de passe de la configuration chiffrée : demandé une fois, transmis à rclone
        par variable d'environnement (jamais écrit sur disque ni dans les journaux)."""
        if self._env is not None:
            return self._env
        env = dict(os.environ, RCLONE_CONFIG=str(self.config))
        if self.config.is_file() and self.config.read_text(errors="ignore").startswith("# Encrypted"):
            if self.password_command:
                res = subprocess.run(shlex.split(self.password_command), capture_output=True, text=True, check=False)
                if res.returncode != 0:
                    raise OneDriveError("le trousseau n'a pas fourni le mot de passe rclone "
                                        "(trousseau verrouillé ? essayer : security unlock-keychain)")
                env["RCLONE_CONFIG_PASS"] = res.stdout.strip()
            else:
                env["RCLONE_CONFIG_PASS"] = getpass.getpass("Mot de passe de la configuration rclone : ")
        self._env = env
        return env

    def _run(self, args: list[str]) -> str:
        res = subprocess.run([self.bin, *args], capture_output=True, text=True, env=self._environment(), check=False)
        if res.returncode != 0:
            # On ne remonte que la dernière ligne : elle peut citer un chemin, elle reste locale.
            last = (res.stderr.strip().splitlines() or ["?"])[-1]
            raise OneDriveError(f"rclone a échoué : {last}")
        return res.stdout

    def _remote_path(self, root: str, rel: str = "") -> str:
        path = str(PurePosixPath(root.strip("/")) / rel) if rel else root.strip("/")
        return f"{self.remote}:{path}"

    def list_files(self, root: str) -> list[RemoteFile]:
        out = self._run(["lsjson", "-R", "--files-only", "--hash", "--fast-list",
                         self._remote_path(root)])
        files = []
        for entry in json.loads(out or "[]"):
            if not entry.get("ID"):
                raise OneDriveError("rclone ne fournit pas l'identifiant OneDrive (champ ID) : "
                                    "version de rclone trop ancienne ?")
            files.append(RemoteFile(id=entry["ID"], path=entry["Path"], name=entry["Name"],
                                    size=int(entry.get("Size") or 0), mtime=entry.get("ModTime", ""),
                                    hash=_hash_of(entry)))
        return files

    def download(self, root: str, item: RemoteFile, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._run(["copyto", self._remote_path(root, item.path), str(dest)])

    def check(self) -> str:
        return self._run(["about", f"{self.remote}:"])
