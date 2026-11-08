# Penny

Assistant personnel local : seconde mémoire, suivi des engagements, anticipation des échéances.

État : **It. 0** — fondations et évaluation, sur Mac, avec de fausses données uniquement.

## Arborescence

| Dossier | Rôle |
|---|---|
| `config/` | Configuration par machine, **sans secret** (`machine.example.env` à copier) |
| `scripts/` | `install.sh` : seul point d'entrée d'installation |
| `src/` | Code de Penny (Core, serveur MCP, circuit d'action) |
| `tests/fixtures/` | Jeu de test inventé, en français, avec réponses attendues |
| `docs/` | Décisions, notes techniques et tutoriels (`installation-mac.md`) |

## Installation

```
cp config/machine.example.env config/machine.env   # puis ajuster
./scripts/install.sh
```

Les secrets ne sont jamais dans ce dépôt : voir `CLAUDE.md`.
