#!/usr/bin/env bash
# Profil mac — partie administrateur : démarrage automatique d'Ollama pour le compte penny,
# via un LaunchDaemon système (UserName=penny).
#
# Le Docker de penny (OrbStack) n'est PAS démarré automatiquement : testé le 08/11/2026,
# OrbStack lancé par launchd échoue au démarrage à froid (TCC, Group Containers).
# Le Mac sert au développement ; le service 24 h/24 sera assuré par le PC Linux.
# Après un redémarrage : su - penny -c 'orb start'
#
# À lancer depuis le compte du développeur (administrateur), jamais depuis penny :
#   sudo ./scripts/mac/install-services.sh             installer ou mettre à jour
#   sudo ./scripts/mac/install-services.sh --uninstall désinstaller
#        ./scripts/mac/install-services.sh --status    état (sans sudo)
#
# Compatible bash 3.2 (celui de macOS). Idempotent. Aucun secret lu ni écrit.
# Équivalent sur le PC IA Linux (profil linux-gpu) : aucun daemon propre à Penny ;
# systemd démarre Docker et Compose relance tout, Ollama compris (restart: unless-stopped).
# Le plist généré appartient à root et n'est pas modifiable par penny ; il n'appelle
# qu'un binaire que penny ne peut pas modifier.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
TEMPLATE_DIR="$REPO_DIR/deploy/mac/launchd"
DAEMON_DIR="/Library/LaunchDaemons"
SERVICE_USER="penny"
LABELS=(local.penny.ollama)
# Services abandonnés : retirés à chaque installation ou désinstallation.
RETIRED_LABELS=(local.penny.orbstack)

info() { echo "  $1"; }
die()  { echo "ERREUR : $1" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || die "ce script ne concerne que le profil mac"

# --- État -------------------------------------------------------------------
status() {
  local label state
  for label in "${LABELS[@]}" "${RETIRED_LABELS[@]}"; do
    if [[ -f "$DAEMON_DIR/$label.plist" ]]; then
      if launchctl print "system/$label" >/dev/null 2>&1; then
        state="$(launchctl print "system/$label" 2>/dev/null | awk -F'= ' '/^\tstate =/ {print $2; exit}')"
        info "$label : installé, chargé (état : ${state:-inconnu})"
      else
        info "$label : installé, NON chargé"
      fi
    else
      info "$label : non installé"
    fi
  done
}

if [[ "${1:-}" == "--status" ]]; then
  echo "Services de démarrage automatique de penny :"
  status
  exit 0
fi

[[ "$(id -u)" -eq 0 ]] || die "lancer avec sudo depuis le compte administrateur (pas depuis penny)"
[[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "$SERVICE_USER" ]] || die "lancer avec sudo depuis le compte du développeur, pas depuis $SERVICE_USER"
id "$SERVICE_USER" >/dev/null 2>&1 || die "compte $SERVICE_USER introuvable (tutoriel, étape 2)"

# --- Retrait ------------------------------------------------------------------
bootout() {
  local label="$1"
  if launchctl print "system/$label" >/dev/null 2>&1; then
    launchctl bootout "system/$label" 2>/dev/null || true
  fi
}

remove() {
  local label="$1"
  if [[ -f "$DAEMON_DIR/$label.plist" ]] || launchctl print "system/$label" >/dev/null 2>&1; then
    bootout "$label"
    rm -f "$DAEMON_DIR/$label.plist"
    info "$label retiré"
  fi
}

if [[ "${1:-}" == "--uninstall" ]]; then
  echo "Désinstallation :"
  for label in "${LABELS[@]}" "${RETIRED_LABELS[@]}"; do
    remove "$label"
  done
  info "Ollama s'arrête avec son service ; il ne redémarrera plus au boot."
  exit 0
fi

[[ $# -eq 0 ]] || die "option inconnue : $1 (attendu : rien, --uninstall ou --status)"

# --- Configuration ------------------------------------------------------------
CONF="$REPO_DIR/config/machine.env"
[[ -f "$CONF" ]] || die "manque $CONF (copier config/machine.example.env)"
# shellcheck disable=SC1090
source "$CONF"
[[ "${PENNY_PROFILE:-}" == "mac" ]] || die "PENNY_PROFILE doit valoir mac (actuel : ${PENNY_PROFILE:-vide})"

PENNY_HOME="$(dscl . -read "/Users/$SERVICE_USER" NFSHomeDirectory | awk '{print $2}')"
LOG_DIR="$PENNY_HOME/Library/Logs/penny"

# Chemin donné dans machine.env, sinon premier emplacement connu qui existe.
find_binary() {
  local given="$1"; shift
  if [[ -n "$given" ]]; then echo "$given"; return; fi
  local c
  for c in "$@"; do
    [[ -x "$c" ]] && { echo "$c"; return; }
  done
  echo "$1"
}
OLLAMA_BIN="$(find_binary "${PENNY_OLLAMA_BIN:-}" \
  /Applications/Ollama.app/Contents/Resources/ollama \
  /opt/homebrew/bin/ollama \
  /usr/local/bin/ollama)"

# Règle 5 : Ollama sur 127.0.0.1 uniquement.
OLLAMA_HOST="${PENNY_OLLAMA_URL#http://}"
OLLAMA_HOST="${OLLAMA_HOST%/}"
[[ "$OLLAMA_HOST" =~ ^127\.0\.0\.1:[0-9]{2,5}$ ]] \
  || die "PENNY_OLLAMA_URL doit être http://127.0.0.1:<port> (actuel : ${PENNY_OLLAMA_URL:-vide})"

# Les valeurs vont dans du XML : chemins absolus simples uniquement.
safe_path() { [[ "$1" =~ ^/[A-Za-z0-9._/-]+$ ]] || die "chemin refusé : $1"; }

# Un binaire lancé par un daemon ne doit pas être modifiable par penny :
# ni le fichier réel, ni aucun dossier qui le contient.
check_binary() {
  local name="$1" path="$2" var="$3" real dir
  safe_path "$path"
  [[ -x "$path" ]] || die "$name introuvable ou non exécutable : $path (renseigner $var dans machine.env)"
  real="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$path")"
  dir="$real"
  while [[ "$dir" != "/" ]]; do
    if sudo -u "$SERVICE_USER" test -w "$dir"; then
      die "$dir est modifiable par $SERVICE_USER : refus (le daemon exécuterait du code que penny contrôle)"
    fi
    dir="$(dirname "$dir")"
  done
  info "$name : $path → $real (non modifiable par $SERVICE_USER)"
}

echo "Vérifications :"
safe_path "$PENNY_HOME"
check_binary ollama "$OLLAMA_BIN" PENNY_OLLAMA_BIN
info "Ollama écoutera sur $OLLAMA_HOST"

# --- Génération ---------------------------------------------------------------
render() {
  sed -e "s|@PENNY_HOME@|$PENNY_HOME|g" \
      -e "s|@LOG_DIR@|$LOG_DIR|g" \
      -e "s|@OLLAMA_BIN@|$OLLAMA_BIN|g" \
      -e "s|@OLLAMA_HOST@|$OLLAMA_HOST|g" \
      "$1"
}

# Journaux dans le dossier de penny, créés par penny (il en est propriétaire).
sudo -u "$SERVICE_USER" mkdir -p "$LOG_DIR"
sudo -u "$SERVICE_USER" chmod 700 "$LOG_DIR"

echo "Installation :"
for label in "${RETIRED_LABELS[@]}"; do
  remove "$label"
done

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

for label in "${LABELS[@]}"; do
  out="$TMP/$label.plist"
  render "$TEMPLATE_DIR/$label.plist.template" > "$out"
  grep -q '@[A-Z_]*@' "$out" && die "$label : variable non remplacée"
  plutil -lint -s "$out" || die "$label : plist invalide"

  bootout "$label"
  install -o root -g wheel -m 644 "$out" "$DAEMON_DIR/$label.plist"
  info "$label : $DAEMON_DIR/$label.plist (root:wheel 644)"
done

# Une instance lancée à la main (tutoriel, étape 8) occuperait le port : on l'arrête
# pour que launchd en soit le seul responsable. Ollama ne contient aucune donnée.
if pgrep -u "$SERVICE_USER" -f "ollama serve" >/dev/null; then
  pkill -u "$SERVICE_USER" -f "ollama serve" || true
  info "Ollama lancé à la main arrêté (launchd le relance)"
  sleep 2
fi

for label in "${LABELS[@]}"; do
  launchctl bootstrap system "$DAEMON_DIR/$label.plist"
  launchctl enable "system/$label"
done

echo "Contrôle (quelques secondes) :"
sleep 5
status
if curl -fsS "http://$OLLAMA_HOST/api/version" >/dev/null 2>&1; then
  info "Ollama répond sur $OLLAMA_HOST"
else
  info "Ollama ne répond pas encore : voir $LOG_DIR/ollama.log"
fi
echo "Terminé. Tests complets : docs/installation-mac.md, étape 10."
