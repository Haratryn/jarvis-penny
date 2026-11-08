# Penny

Assistant personnel local : seconde mémoire, suivi des engagements, anticipation des échéances.

État : **It. 0** — fondations et évaluation, sur Mac, avec de fausses données uniquement.

## Arborescence

| Dossier | Rôle |
|---|---|
| `config/` | Configuration par machine, **sans secret** (`machine.example.env` à copier) |
| `scripts/` | `install.sh` : point d'entrée d'installation (compte `penny`) ; `mac/install-services.sh` : partie administrateur du profil mac (démarrage automatique) |
| `deploy/` | Fichiers système par profil (`mac/launchd/` : modèle du LaunchDaemon d'Ollama) |
| `src/` | Code de Penny (Core, serveur MCP, circuit d'action) |
| `tests/fixtures/` | Jeu de test inventé, en français, avec réponses attendues |
| `docs/` | Décisions, notes techniques et tutoriels (`installation-mac.md`) |

## Installation

```
cp config/machine.example.env config/machine.env   # puis ajuster
./scripts/install.sh
```

Les secrets ne sont jamais dans ce dépôt : voir `CLAUDE.md`.

## Portabilité (Mac prototype → PC IA Linux)

Tout doit pouvoir être reconstruit sur une autre machine depuis ce dépôt et la sauvegarde.
Ce qui diffère d'un profil à l'autre est isolé ici :

| Besoin | `mac` (prototype) | `linux-gpu` (cible) |
|---|---|---|
| Inférence | Ollama natif (Metal), hors Docker | Ollama en conteneur (Compose) |
| Démarrage automatique | Ollama : LaunchDaemon `local.penny.ollama` (`scripts/mac/install-services.sh`) ; Docker : `orb start` manuel après redémarrage (prototype de développement) | systemd démarre Docker, Compose relance tout, 24 h/24 |
| Isolation | compte macOS standard `penny`, FileVault | compte système `penny`, disque chiffré |
| Secrets | trousseau macOS | coffre chiffré (à choisir) |

Migration = installer le profil cible, copier `config/machine.env` en l'adaptant, restaurer la sauvegarde.
