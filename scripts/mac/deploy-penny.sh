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
if [[ ! -f "$CONF_DIR/penny.env" ]]; then
  sed "s|^PENNY_RCLONE_BIN=.*|PENNY_RCLONE_BIN=$RCLONE|" config/penny.example.env | as_penny tee "$CONF_DIR/penny.env" >/dev/null
  info "créée : $CONF_DIR/penny.env"
else
  info "conservée : $CONF_DIR/penny.env"
fi

echo "Modèles Ollama de $SERVICE_USER :"
# shellcheck disable=SC2046
eval $(grep -E '^PENNY_(LLM|EMBED)_MODEL=|^PENNY_OLLAMA_URL=' "$CONF_DIR/penny.env")
HOSTPORT="${PENNY_OLLAMA_URL#http://}"
for model in "$PENNY_EMBED_MODEL" "$PENNY_LLM_MODEL"; do
  as_penny env OLLAMA_HOST="$HOSTPORT" "$OLLAMA" pull "$model" >/dev/null && info "$model : prêt"
done
echo "Terminé. Suite : docs/installation-mac.md, étape 11."
