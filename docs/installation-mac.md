# Installation sur Mac (prototype)

Validé le 08/11/2026 sur MacBook Air M4, macOS, OrbStack + Docker 29.8.2, Ollama 0.40.5.

## Principe
Penny tourne sous un compte macOS dédié `penny`, **standard (non administrateur)**,
lancé depuis la session du développeur avec `su - penny`. La session graphique de
`penny` n'a pas besoin d'être ouverte.

## Étapes manuelles (impossibles à scripter, une seule fois)
1. FileVault actif (`fdesetup status` → « FileVault is On »).
2. Créer le compte `penny` : Standard, sans identifiant Apple, sans ouverture automatique.
3. Retirer `penny` des dossiers partagés (Réglages → Partage → Partage de fichiers).
4. Cloisonner les dossiers personnels : `chmod 700` sur le dossier du développeur et sur `/Users/penny`.
5. Installer OrbStack depuis un compte administrateur (`brew install orbstack`).
6. **Ouvrir une fois la session graphique `penny`**, lancer OrbStack, choisir Docker et
   accepter les autorisations macOS (TCC). Sans cela, `orb start` échoue depuis `su`
   avec « missing TCC permission for data storage directory ». Fermer ensuite la session.

## Constats testés
| Test | Résultat |
|---|---|
| `penny` utilise le Docker du développeur (`/var/run/docker.sock`) | Refusé (permission denied) |
| `orb start` depuis `su - penny`, après autorisation TCC | OK, socket `/Users/penny/.orbstack/run/docker.sock` |
| Docker de `penny` après `exit` du terminal | Continue de tourner |
| `ollama serve` sous `penny`, `OLLAMA_HOST=127.0.0.1:11435` | OK, écoute sur 127.0.0.1 uniquement |
| Ollama après `disown` + `exit` | Continue de tourner |
| Lecture croisée des dossiers personnels après `chmod 700` | Refusée dans les deux sens |
| Ollama de `penny` joignable depuis le compte du développeur | **Oui** (127.0.0.1 n'isole pas les comptes) |

## Limites du prototype
- Après un redémarrage, FileVault bloque tout jusqu'à la saisie d'un mot de passe.
- Mac en veille = Penny à l'arrêt (rappels de secours via ntfy sur le VPS).
- Démarrage automatique : à faire (service système décrit dans ce dépôt).
