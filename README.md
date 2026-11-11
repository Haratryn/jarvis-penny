# Penny

Assistant personnel local : seconde mémoire, suivi des engagements, anticipation des échéances.

État : **incrément 1** — analyser un dossier OneDrive réel (lecture seule), l'inventorier et
répondre avec des sources. IA 100 % locale (Ollama). Penny voit les données réelles sous le
compte `penny` ; Claude Code ne voit que des données inventées (voir `CLAUDE.md`).

## Utilisation (compte `penny`)

```
penny onedrive connect | check     # accès OneDrive en lecture seule (rclone)
penny scan "<dossier>" [--limit N] # inventaire puis analyse (reprise automatique)
penny status [<dossier>]           # listés, analysés, sans texte, ignorés, erreurs
penny docs [--type T] [--sans-texte]
penny ask "question" [--root <dossier>]
penny diag                         # rapport anonymisé : le seul à transmettre à Claude
```

Déploiement sur le Mac : `sudo ./scripts/mac/deploy-penny.sh` (tutoriel, étape 11).
Développement : `uv sync --group dev && uv run pytest` (faux OneDrive, faux modèle).

## Couches de la mémoire

| Couche | Où | État |
|---|---|---|
| Sources | `items` (identifiant OneDrive stable, chemin, empreinte) + copie locale | incrément 1 |
| Mémoire extraite | `cards` (fiche par document), `chunks` (passages, plein texte, vecteurs), reliées à (identifiant, empreinte) | incrément 1 |
| Corrections et décisions | journal séparé, indépendant du moteur | incrément 2 |
| Engagements et preuves | à venir | — |

## Arborescence

| Dossier | Rôle |
|---|---|
| `config/` | Configuration **sans secret** : `machine.example.env` (machine), `penny.example.env` (compte penny) |
| `scripts/` | `install.sh` : vérification des prérequis (compte `penny`) ; `mac/install-services.sh` : démarrage automatique d'Ollama ; `mac/deploy-penny.sh` : déploiement de Penny |
| `deploy/` | Fichiers système par profil (`mac/launchd/` : modèle du LaunchDaemon d'Ollama) |
| `src/penny/` | Code de Penny : `onedrive` (rclone), `extract` (Docling), `pipeline` (scan), `search` (réponses citées), `report` (état, diagnostic), `cli` |
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
