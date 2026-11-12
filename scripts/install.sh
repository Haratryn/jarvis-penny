#!/usr/bin/env bash
# Vérification des prérequis de Penny, à lancer sous le compte penny APRÈS le déploiement :
#   su - penny -c /opt/penny/current/scripts/install.sh
# N'installe rien, ne demande aucun droit admin. Lit ~/.config/penny/penny.env.
# shellcheck disable=SC2015  # ok/fail/info renvoient toujours 0
set -euo pipefail

CONF="${PENNY_CONFIG:-$HOME/.config/penny/penny.env}"
if [[ -f "$CONF" ]]; then
  # shellcheck disable=SC1090
  source "$CONF"
fi
PENNY_PROFILE="${PENNY_PROFILE:-mac}"
PENNY_OLLAMA_URL="${PENNY_OLLAMA_URL:-http://127.0.0.1:11435}"

ok()   { echo "  ok    $1"; }
info() { echo "  info  $1"; }
fail() { echo "  ÉCHEC $1"; FAILED=1; }
FAILED=0

echo "Profil : ${PENNY_PROFILE}"
echo "Vérifications :"

[[ "$(id -un)" == "penny" ]] && ok "compte penny" || fail "lancer depuis le compte penny (actuel : $(id -un))"
id -Gn | grep -qw admin && fail "le compte ne doit pas être administrateur" || ok "compte non administrateur"
[[ -f "$CONF" ]] && ok "configuration $CONF" || fail "configuration absente : $CONF (déployer : étape 11)"
command -v penny >/dev/null && ok "commande penny ($(command -v penny))" || fail "commande penny absente (déployer : étape 11)"
[[ -x "${PENNY_RCLONE_BIN:-}" ]] && ok "rclone" || fail "rclone introuvable (${PENNY_RCLONE_BIN:-non configuré})"

case "$PENNY_PROFILE" in
  mac)
    fdesetup status 2>/dev/null | grep -q "FileVault is On" && ok "FileVault" || fail "FileVault inactif"
    [[ "$(stat -f %Lp "$HOME")" == "700" ]] && ok "dossier personnel en 700" || fail "dossier personnel lisible par d'autres comptes (chmod 700 ~)"
    ;;
  linux-gpu)
    command -v nvidia-smi >/dev/null && ok "GPU NVIDIA" || fail "nvidia-smi absent"
    ;;
  *) fail "profil inconnu : ${PENNY_PROFILE}" ;;
esac

if curl -fsS "${PENNY_OLLAMA_URL}/api/version" >/dev/null 2>&1; then
  ok "Ollama joignable sur ${PENNY_OLLAMA_URL}"
  tags="$(curl -fsS "${PENNY_OLLAMA_URL}/api/tags" 2>/dev/null || true)"
  for model in ${PENNY_EMBED_MODEL:-bge-m3} ${PENNY_LLM_MODEL:-qwen3:8b}; do
    [[ "$model" == *:* ]] || model="$model:latest"
    grep -q "\"$model\"" <<<"$tags" && ok "modèle $model" || fail "modèle $model absent (relancer le déploiement)"
  done
else
  fail "Ollama injoignable sur ${PENNY_OLLAMA_URL} (étape 10)"
fi

if [[ -d "${PENNY_DATA_DIR:-$HOME/penny-data}" ]]; then
  [[ "$(stat -f %Lp "${PENNY_DATA_DIR:-$HOME/penny-data}" 2>/dev/null)" == "700" ]] && ok "données en 700" || fail "dossier de données trop ouvert"
fi
command -v docker >/dev/null && info "Docker présent (non requis pour l'incrément 1)" || info "Docker absent (non requis pour l'incrément 1)"

[[ $FAILED -eq 0 ]] && echo "Prérequis OK." || { echo "Prérequis incomplets."; exit 1; }
