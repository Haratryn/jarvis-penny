#!/usr/bin/env bash
# Point d'entrée unique d'installation de Penny.
# It. 0 : vérifie seulement les prérequis. N'installe rien, ne demande aucun droit admin.
set -euo pipefail

cd "$(dirname "$0")/.."
CONF="config/machine.env"
[[ -f "$CONF" ]] || { echo "Manque $CONF (copier config/machine.example.env)"; exit 1; }
# shellcheck disable=SC1090
source "$CONF"

ok()   { echo "  ok    $1"; }
fail() { echo "  ÉCHEC $1"; FAILED=1; }
FAILED=0

echo "Profil : ${PENNY_PROFILE}"
echo "Vérifications :"

[[ "$(id -un)" == "penny" ]] && ok "compte penny" || fail "lancer depuis le compte penny (actuel : $(id -un))"
id -Gn | grep -qw admin && fail "le compte ne doit pas être administrateur" || ok "compte non administrateur"
command -v git >/dev/null && ok "git" || fail "git absent"
command -v docker >/dev/null && ok "docker" || fail "docker absent"

case "$PENNY_PROFILE" in
  mac)
    fdesetup status 2>/dev/null | grep -q "FileVault is On" && ok "FileVault" || fail "FileVault inactif"
    curl -fsS "${PENNY_OLLAMA_URL}/api/version" >/dev/null && ok "Ollama natif joignable" || fail "Ollama natif injoignable sur ${PENNY_OLLAMA_URL}"
    ;;
  linux-gpu)
    command -v nvidia-smi >/dev/null && ok "GPU NVIDIA" || fail "nvidia-smi absent"
    ;;
  *) fail "profil inconnu : ${PENNY_PROFILE}" ;;
esac

[[ $FAILED -eq 0 ]] && echo "Prérequis OK." || { echo "Prérequis incomplets."; exit 1; }
