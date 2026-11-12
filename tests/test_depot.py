"""Le dépôt contient bien ce que les scripts de déploiement utilisent (leçon du 12/11 :
penny.example.env exclu par le .gitignore, déploiement en échec sur le Mac)."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def tracked() -> set[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return set(out.splitlines())


def test_fichiers_utilises_par_les_scripts_sont_versionnes():
    files = tracked()
    for script in ("scripts/mac/deploy-penny.sh", "scripts/mac/install-services.sh"):
        for ref in re.findall(r"\b((?:config|deploy|scripts)/[\w./-]+\.(?:env|template|sh))\b",
                              (ROOT / script).read_text()):
            if ref.endswith(".env") and ".example." not in ref:
                continue  # configuration locale, volontairement hors du dépôt
            assert ref in files, f"{script} utilise {ref}, absent du dépôt (gitignore ?)"


def test_aucun_vrai_fichier_env_versionne():
    assert not [f for f in tracked() if f.endswith(".env") and ".example." not in f]
