"""Source « dossier local » : le OneDrive synchronisé sur le Mac, lu sans aucun accès réseau.

macOS limite ce que `penny` peut lire (droits ACL posés par l'utilisateur sur les seuls
dossiers choisis). Penny ne copie rien : les fichiers sont lus là où ils sont.

Faute d'identifiant OneDrive, chaque fichier reçoit un identifiant Penny stable :
  - même chemin, même taille et même date : même fichier, empreinte réutilisée (rien n'est relu) ;
  - même chemin, contenu changé : même fichier, nouvelle version ;
  - nouveau chemin dont le contenu est identique à un fichier disparu : fichier déplacé ou renommé ;
  - sinon : nouveau fichier.
Seuls les documents lisibles (texte, PDF, Office) sous la taille maximale sont lus pour
l'empreinte : les images, vidéos et archives ne sont jamais ouvertes (fichiers « à la
demande » non téléchargés pour rien).
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .extract import DOCLING_EXT, TEXT_EXT
from .onedrive import OneDriveError, RemoteFile

IGNORED_PREFIXES = (".", "~$")  # fichiers cachés, verrous Office


class SourceError(OneDriveError):
    pass


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


class LocalFolderSource:
    def __init__(self, base: Path, conn: sqlite3.Connection, max_file_mb: int = 50):
        self.base = Path(base).expanduser()
        self.conn = conn
        self.max_bytes = max_file_mb * 1024 * 1024

    def _root_dir(self, root: str) -> Path:
        if not str(self.base) or str(self.base) == ".":
            raise SourceError("PENNY_LOCAL_ROOT n'est pas configuré")
        rel = PurePosixPath(root.strip("/"))
        if rel.is_absolute() or ".." in rel.parts:
            raise SourceError("dossier refusé : il doit être relatif à PENNY_LOCAL_ROOT, sans « .. »")
        path = self.base / rel
        if not os.access(path, os.R_OK | os.X_OK) or not path.is_dir():
            raise SourceError("Penny ne peut pas lire ce dossier : vérifier son nom et les droits "
                              "accordés à penny (tutoriel, étape 11.3)")
        return path

    def _hash(self, path: Path, ext: str, size: int, mtime: str) -> str:
        if ext in TEXT_EXT | DOCLING_EXT and size <= self.max_bytes:
            try:
                return sha256_of(path)
            except OSError:
                pass  # fichier non disponible localement : il sera signalé en erreur au traitement
        return f"meta:{size}:{mtime}"

    def list_files(self, root: str) -> list[RemoteFile]:
        top = self._root_dir(root)
        known = {r["path"]: r for r in self.conn.execute(
            "SELECT id, path, size, mtime, hash FROM items WHERE root = ? AND gone = 0", (root,))}
        missing = dict(known)
        found: list[RemoteFile] = []
        unknown: list[tuple[str, str, int, str, str]] = []

        for dirpath, dirnames, filenames in os.walk(top, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(IGNORED_PREFIXES))
            for name in sorted(filenames):
                if name.startswith(IGNORED_PREFIXES):
                    continue
                full = Path(dirpath) / name
                if full.is_symlink():
                    continue  # jamais de sortie du périmètre autorisé
                try:
                    st = full.stat()
                except OSError:
                    continue
                rel = full.relative_to(top).as_posix()
                ext = PurePosixPath(name).suffix.lower()
                mtime = datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()
                row = known.get(rel)
                if row is not None:
                    missing.pop(rel, None)
                    same = row["size"] == st.st_size and row["mtime"] == mtime
                    hash_ = row["hash"] if same else self._hash(full, ext, st.st_size, mtime)
                    found.append(RemoteFile(row["id"], rel, name, st.st_size, mtime, hash_))
                else:
                    unknown.append((rel, name, st.st_size, mtime, self._hash(full, ext, st.st_size, mtime)))

        by_hash = {}
        for row in missing.values():
            if not row["hash"].startswith("meta:"):
                by_hash.setdefault(row["hash"], row)
        for rel, name, size, mtime, hash_ in unknown:
            moved = by_hash.pop(hash_, None)
            item_id = moved["id"] if moved is not None else "local:" + uuid.uuid4().hex
            found.append(RemoteFile(item_id, rel, name, size, mtime, hash_))
        return found

    def fetch(self, root: str, item: RemoteFile, dest: Path) -> Path:
        """Pas de copie : le fichier est lu sur place."""
        path = self._root_dir(root) / item.path
        if not path.is_file() or path.is_symlink():
            raise SourceError("fichier introuvable ou non autorisé")
        return path

    def check(self) -> str:
        if not os.access(self.base, os.X_OK):
            raise SourceError("PENNY_LOCAL_ROOT inaccessible pour penny (droits de passage manquants)")
        return f"Dossier OneDrive local accessible (lecture seule, sans réseau)."
