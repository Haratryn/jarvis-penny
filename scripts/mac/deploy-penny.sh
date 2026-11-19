#!/usr/bin/env bash
# Profil mac — déploie la version courante du dépôt pour le compte penny.
#
# À lancer depuis le compte du développeur (administrateur), dans sa copie du dépôt :
#   sudo ./scripts/mac/deploy-penny.sh
#
# - copie le commit courant (arbre propre exigé) dans /opt/penny/releases/<commit>,
#   installe ses dépendances figées (uv.lock), et pointe /opt/penny/current dessus ;
# - tout appartient à root : penny peut exécuter Penny mais pas la modifier ;
# - crée la configuration de penny si elle n'existe pas, et télécharge les modèles Ollama.
# Idempotent. Aucun secret. Compatible bash 3.2.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SERVICE_USER="penny"
BASE="/opt/penny"

info() { echo "  $1"; }
die()  { echo "ERREUR : $1" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || die "ce script ne concerne que le profil mac"
[[ "$(id -u)" -eq 0 ]] || die "lancer avec sudo depuis le compte administrateur"
[[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "$SERVICE_USER" ]] || die "lancer depuis le compte du développeur, pas depuis $SERVICE_USER"
id "$SERVICE_USER" >/dev/null 2>&1 || die "compte $SERVICE_USER introuvable"

as_dev() { sudo -u "$SUDO_USER" "$@"; }
as_penny() { sudo -u "$SERVICE_USER" -H "$@"; }

cd "$REPO_DIR"
[[ -z "$(as_dev git status --porcelain)" ]] || die "le dépôt a des modifications non commitées : commiter ou annuler avant de déployer"
COMMIT="$(as_dev git rev-parse --short=12 HEAD)"

# Emplacements Homebrew (Apple Silicon, puis Intel) : on ne dépend pas des fichiers de shell.
find_tool() {
  local c
  for c in "/opt/homebrew/bin/$1" "/usr/local/bin/$1"; do
    [[ -x "$c" ]] && { echo "$c"; return; }
  done
}
UV="$(find_tool uv)"
RCLONE="$(find_tool rclone)"
OLLAMA="/usr/local/bin/ollama"
[[ -x "$UV" ]] || die "uv absent : brew install uv (depuis votre compte)"
[[ -x "$RCLONE" ]] || info "rclone absent : inutile avec la source « dossier local »"

# OneDrive synchronisé sur le Mac du développeur (source « dossier local »)
ONEDRIVE_LOCAL=""
for d in "/Users/$SUDO_USER/Library/CloudStorage"/OneDrive-*; do
  [[ -d "$d" ]] || continue
  [[ -z "$ONEDRIVE_LOCAL" ]] || { info "plusieurs dossiers OneDrive : renseigner PENNY_LOCAL_ROOT à la main"; ONEDRIVE_LOCAL=""; break; }
  ONEDRIVE_LOCAL="$d"
done

# Un binaire utilisé par Penny ne doit pas être modifiable par penny.
for bin in "$UV" ${RCLONE:+"$RCLONE"}; do
  real="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$bin")"
  dir="$real"
  while [[ "$dir" != "/" ]]; do
    sudo -u "$SERVICE_USER" test -w "$dir" && die "$dir est modifiable par $SERVICE_USER"
    dir="$(dirname "$dir")"
  done
done
info "uv : $("$UV" --version)"
[[ -x "$RCLONE" ]] && info "rclone : $("$RCLONE" version | head -1)"

echo "Déploiement de la version $COMMIT :"
# Les dépendances (Docling, modèles…) vivent dans un environnement partagé, identifié par
# l'empreinte de uv.lock et pyproject.toml : il n'est reconstruit que si elles changent.
# Chaque version ne contient que le code de Penny (quelques centaines de Ko).
REL="$BASE/releases/$COMMIT"
DEPS_ID="$(cat uv.lock pyproject.toml | shasum -a 256 | cut -c1-16)"
VENV="$BASE/venvs/$DEPS_ID"
mkdir -p "$BASE/releases" "$BASE/venvs"

if [[ ! -x "$VENV/bin/python" ]]; then
  info "dépendances modifiées : installation de l'environnement $DEPS_ID (long la première fois)"
  rm -rf "$VENV"
  BUILD="$(mktemp -d)"
  as_dev git archive --format=tar HEAD uv.lock pyproject.toml | tar -x -C "$BUILD"
  UV_PYTHON_INSTALL_DIR="$BASE/python" UV_CACHE_DIR="$BASE/uv-cache" UV_PROJECT_ENVIRONMENT="$VENV" \
    "$UV" sync --frozen --no-dev --extra extract --no-install-project --project "$BUILD" --python 3.13 --managed-python
  rm -rf "$BUILD"
  chown -R root:wheel "$VENV" "$BASE/python" "$BASE/uv-cache"
  chmod -R go-w "$VENV" "$BASE/python" "$BASE/uv-cache"
else
  info "dépendances inchangées : environnement $DEPS_ID réutilisé"
fi

if [[ ! -d "$REL/src/penny" ]]; then
  rm -rf "$REL"
  mkdir -p "$REL"
  as_dev git archive --format=tar HEAD | tar -x -C "$REL"
  chown -R root:wheel "$REL"
  chmod -R go-w "$REL"
fi
[[ -d "$REL/.venv" && ! -L "$REL/.venv" ]] && rm -rf "${REL:?}/.venv"  # version de l'ancien format
ln -sfn "$VENV" "$REL/.venv"
chown -h root:wheel "$REL/.venv"
chown root:wheel "$BASE" "$BASE/releases" "$BASE/venvs"
chmod go-w "$BASE" "$BASE/releases" "$BASE/venvs"
ln -sfn "$REL" "$BASE/current"
printf '%s\n' '#!/bin/sh' \
  '# Penny : code de la version courante + environnement de dépendances partagé (tout en root:wheel)' \
  "PYTHONPATH=\"$BASE/current/src\" exec \"$BASE/current/.venv/bin/python\" -m penny.cli \"\$@\"" \
  > /usr/local/bin/penny
chown root:wheel /usr/local/bin/penny
chmod 755 /usr/local/bin/penny
# Lanceur depuis le compte du développeur (garde OneDrive réveillé) : copie, pas un lien,
# pour qu'il reste root:wheel quelle que soit la copie de travail.
install -o root -g wheel -m 755 "$REL/scripts/mac/penny-lancer" /usr/local/bin/penny-lancer
info "commandes : /usr/local/bin/penny (sous penny), /usr/local/bin/penny-lancer (depuis votre compte)"

# Ménage : on garde les 3 dernières versions et les environnements qu'elles utilisent.
current_rel="$(readlink "$BASE/current")"
# shellcheck disable=SC2012  # noms de versions = commits, sans caractères spéciaux
while IFS= read -r old; do
  [[ -n "$old" && "$BASE/releases/$old" != "$current_rel" ]] && rm -rf "${BASE:?}/releases/${old:?}"
done < <(ls -1t "$BASE/releases" | tail -n +4)
for env in "$BASE/venvs"/*; do
  [[ -d "$env" ]] || continue
  used=0
  for rel in "$BASE/releases"/*; do
    [[ "$(readlink "$rel/.venv" 2>/dev/null)" == "$env" ]] && used=1
  done
  if [[ $used -eq 0 ]]; then
    rm -rf "${env:?}"
    info "ancien environnement supprimé : $(basename "$env")"
  fi
done
info "Penny $COMMIT installée dans $REL (root:wheel, non modifiable par $SERVICE_USER)"

echo "Configuration de $SERVICE_USER :"
PENNY_HOME="$(dscl . -read "/Users/$SERVICE_USER" NFSHomeDirectory | awk '{print $2}')"
CONF_DIR="$PENNY_HOME/.config/penny"
as_penny mkdir -p "$CONF_DIR"
as_penny chmod 700 "$PENNY_HOME/.config" "$CONF_DIR"
CONF="$CONF_DIR/penny.env"
[[ -f "$CONF" ]] || as_penny touch "$CONF"
as_penny chmod 600 "$CONF"
# Complète la configuration : toute clé absente ou vide reprend la valeur du modèle
# (les valeurs déjà renseignées par l'utilisateur sont conservées).
while IFS= read -r line; do
  [[ "$line" =~ ^(PENNY_[A-Z_]+)=(.*)$ ]] || continue
  key="${BASH_REMATCH[1]}"; value="${BASH_REMATCH[2]}"
  [[ "$key" == "PENNY_RCLONE_BIN" ]] && value="$RCLONE"
  [[ "$key" == "PENNY_LOCAL_ROOT" ]] && value="$ONEDRIVE_LOCAL"
  if ! grep -qE "^${key}=.+" "$CONF"; then
    tmp="$(mktemp)"
    grep -vE "^${key}=" "$CONF" > "$tmp" || true
    echo "${key}=${value}" >> "$tmp"
    as_penny tee "$CONF" < "$tmp" >/dev/null
    rm -f "$tmp"
    info "configuration : $key=$value"
  fi
done < config/penny.example.env
info "configuration : $CONF"

value_of() { grep -E "^$1=" "$CONF" | tail -1 | cut -d= -f2-; }
LLM_MODEL="$(value_of PENNY_LLM_MODEL)"
EMBED_MODEL="$(value_of PENNY_EMBED_MODEL)"
OLLAMA_URL="$(value_of PENNY_OLLAMA_URL)"
[[ -n "$LLM_MODEL" && -n "$EMBED_MODEL" && -n "$OLLAMA_URL" ]] || die "configuration incomplète : $CONF"
if [[ "$(value_of PENNY_SOURCE)" == "rclone" ]]; then
  [[ -x "$(value_of PENNY_RCLONE_BIN)" ]] || die "PENNY_RCLONE_BIN invalide dans $CONF"
else
  [[ -n "$(value_of PENNY_LOCAL_ROOT)" ]] || die "PENNY_LOCAL_ROOT vide dans $CONF (dossier OneDrive local introuvable)"
  sudo -u "$SERVICE_USER" test -x "$(value_of PENNY_LOCAL_ROOT)" \
    || info "penny ne peut pas encore traverser le dossier OneDrive : faire l'étape 11.3"
fi

echo "Modèles Ollama de $SERVICE_USER (téléchargement si absent, peut être long) :"
[[ -x "$OLLAMA" ]] || die "ollama introuvable : $OLLAMA"
HOSTPORT="${OLLAMA_URL#http://}"
curl -fsS "$OLLAMA_URL/api/version" >/dev/null || die "l'Ollama de $SERVICE_USER ne répond pas sur $OLLAMA_URL (étape 10)"
for model in "$EMBED_MODEL" "$LLM_MODEL"; do
  as_penny env OLLAMA_HOST="$HOSTPORT" "$OLLAMA" pull "$model" || die "téléchargement du modèle $model impossible"
  info "$model : prêt"
done
echo "Terminé. Suite : docs/installation-mac.md, étape 11."
