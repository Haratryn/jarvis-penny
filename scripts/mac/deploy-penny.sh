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

UV="$(as_dev /bin/bash -lc 'command -v uv' || true)"
RCLONE="$(as_dev /bin/bash -lc 'command -v rclone' || true)"
OLLAMA="/usr/local/bin/ollama"
[[ -x "$UV" ]] || die "uv absent : brew install uv (depuis votre compte)"
[[ -x "$RCLONE" ]] || die "rclone absent : brew install rclone (depuis votre compte)"

# Un binaire utilisé par Penny ne doit pas être modifiable par penny.
for bin in "$UV" "$RCLONE"; do
  real="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$bin")"
  dir="$real"
  while [[ "$dir" != "/" ]]; do
    sudo -u "$SERVICE_USER" test -w "$dir" && die "$dir est modifiable par $SERVICE_USER"
    dir="$(dirname "$dir")"
  done
done
info "uv : $("$UV" --version) ; rclone : $("$RCLONE" version | head -1)"

echo "Déploiement de la version $COMMIT :"
REL="$BASE/releases/$COMMIT"
mkdir -p "$BASE/releases"
if [[ ! -x "$REL/.venv/bin/penny" ]]; then
  rm -rf "$REL"
  mkdir -p "$REL"
  as_dev git archive --format=tar HEAD | tar -x -C "$REL"
  UV_PYTHON_INSTALL_DIR="$BASE/python" UV_CACHE_DIR="$BASE/uv-cache" UV_PROJECT_ENVIRONMENT="$REL/.venv" \
    "$UV" sync --frozen --no-dev --extra extract --project "$REL" --python 3.13 --managed-python
fi
chown -R root:wheel "$BASE"
chmod -R go-w "$BASE"
ln -sfn "$REL" "$BASE/current"
cat > /usr/local/bin/penny <<EOF
#!/bin/sh
exec $BASE/current/.venv/bin/penny "\$@"
EOF
chown root:wheel /usr/local/bin/penny
chmod 755 /usr/local/bin/penny
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
[[ -x "$(value_of PENNY_RCLONE_BIN)" ]] || die "PENNY_RCLONE_BIN invalide dans $CONF"

echo "Modèles Ollama de $SERVICE_USER (téléchargement si absent, peut être long) :"
[[ -x "$OLLAMA" ]] || die "ollama introuvable : $OLLAMA"
HOSTPORT="${OLLAMA_URL#http://}"
curl -fsS "$OLLAMA_URL/api/version" >/dev/null || die "l'Ollama de $SERVICE_USER ne répond pas sur $OLLAMA_URL (étape 10)"
for model in "$EMBED_MODEL" "$LLM_MODEL"; do
  as_penny env OLLAMA_HOST="$HOSTPORT" "$OLLAMA" pull "$model" || die "téléchargement du modèle $model impossible"
  info "$model : prêt"
done
echo "Terminé. Suite : docs/installation-mac.md, étape 11."
