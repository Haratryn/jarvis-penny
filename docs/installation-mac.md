# Tutoriel — installer le socle de Penny sur un Mac (prototype)

Validé le 08/11/2026 : MacBook Air M4, OrbStack + Docker 29.8.2, Ollama 0.40.5.

**Principe.** Penny tourne sous un compte macOS dédié `penny`, **standard (non
administrateur)**, isolé du compte du développeur. On le pilote depuis sa propre session
avec `su - penny` : la session graphique de `penny` ne sert qu'une fois, à l'étape 6.

Conventions : `$` = Terminal de **votre** compte ; `penny%` = terminal en tant que `penny`.
Coller les blocs **une commande à la fois** quand une commande change d'utilisateur
(`su`) : sinon les lignes suivantes partent dans le mauvais terminal.

---

## 1. Vérifier FileVault

Réglages Système → Confidentialité et sécurité → FileVault : activé.

```
$ fdesetup status
```
Attendu : `FileVault is On.`

## 2. Créer le compte `penny`

Réglages Système → Utilisateurs et groupes → Ajouter un utilisateur :
- Type : **Standard** (jamais Administrateur)
- Nom complet : `Penny` — Nom du compte : `penny`
- Mot de passe long et unique, rangé dans le gestionnaire de mots de passe
- **Pas d'identifiant Apple**, **pas d'ouverture de session automatique**

```
$ id -Gn penny
```
Attendu : **pas** de `admin` dans la liste (`staff everyone localaccounts _lpoperator …`).

## 3. Couper le partage de fichiers pour `penny`

Si `id -Gn penny` affiche des groupes `com.apple.sharepoint.group.N`, le Partage de fichiers
donne à `penny` l'accès à des dossiers partagés.
Réglages Système → Général → Partage → Partage de fichiers → (i) : le désactiver, ou retirer
`penny` (et « Tout le monde ») des dossiers partagés.

## 4. Cloisonner les dossiers personnels

Par défaut, tous les comptes sont dans le groupe `staff` et peuvent lister le dossier
personnel des autres (`drwxr-x---`). On ferme dans les deux sens :

```
$ chmod 700 ~
$ su - penny -c 'chmod 700 ~'
```
Vérification :
```
$ ls -ld ~ /Users/penny
$ ls /Users/penny
$ su - penny -c "ls $HOME"
```
Attendu : les deux dossiers en `drwx------` ; les deux `ls` → `Permission denied`.

## 5. Installer OrbStack (depuis votre compte, droits administrateur)

```
$ brew install orbstack
```
(ou télécharger l'appli sur orbstack.dev). Au premier lancement : choisir **Docker**
(pas Kubernetes, pas Linux), accepter la demande de mot de passe administrateur,
ignorer la création de compte OrbStack.

```
$ docker version
```
Attendu : `Context: orbstack`, `Server: … OS/Arch: linux/arm64`.

## 6. Autoriser OrbStack pour `penny` (seule étape en session graphique)

macOS protège certains dossiers par des autorisations (TCC) qui ne peuvent être accordées
que par un clic dans une session graphique. Sans cette étape, `orb start` depuis `su` échoue :

```
level=fatal msg="panic: missing TCC permission for data storage directory: permission denied"
```

1. Menu  → Fermer la session, se connecter en `penny`.
2. Lancer OrbStack, choisir **Docker**, cliquer **Autoriser** à chaque demande.
3. Si un mot de passe administrateur est demandé : saisir **vos** identifiants, ne jamais
   rendre `penny` administrateur.
4. **Fermer** la session `penny` (pas seulement la verrouiller) et revenir dans la vôtre.

## 7. Démarrer le Docker de `penny` depuis votre session

> Lancement manuel, une seule fois, pour valider. Après l'étape 10, le démarrage est automatique.

```
$ su - penny
penny% orb start
penny% docker context use orbstack
penny% docker context inspect --format '{{.Endpoints.docker.Host}}'
penny% docker version --format '{{.Server.Version}}'
penny% docker run --rm hello-world
penny% orb config get k8s.enable
penny% exit
```
Attendu :
- contexte : `unix:///Users/penny/.orbstack/run/docker.sock` — **si le chemin n'est pas
  sous `/Users/penny/`, arrêter** : ce serait votre Docker ;
- version : `29.8.2` (ou la version figée du moment) ;
- `Hello from Docker!` ;
- `k8s.enable` : `false` (sinon `orb config set k8s.enable false`).

Vérifier que Docker survit à la fermeture du terminal :
```
$ su - penny -c "docker version --format '{{.Server.Version}}'"
```

## 8. Démarrer l'Ollama de `penny`

> Lancement manuel, une seule fois, pour valider. L'étape 10 arrête cette instance et confie
> Ollama à launchd.
>
> **À compléter** : l'installation d'Ollama n'est pas encore décrite. Noter la sortie de
> `ls -l $(which ollama)` (formule Homebrew ou appli Ollama.app) pour l'ajouter ici et figer la version.

L'Ollama de votre compte occupe le port 11434 : celui de `penny` prend **11435**.
Les deux ne doivent pas charger de modèle en même temps (16 Go de mémoire).

```
$ su - penny
penny% export OLLAMA_HOST=127.0.0.1:11435
penny% nohup ollama serve > ~/ollama.log 2>&1 &
penny% sleep 3
penny% curl -s http://127.0.0.1:11435/api/version; echo
penny% lsof -nP -iTCP:11435 -sTCP:LISTEN
penny% ls -ld ~/.ollama
penny% disown
penny% exit
```
Attendu :
- `{"version":"0.40.5"}` ;
- `ollama … penny … TCP 127.0.0.1:11435 (LISTEN)` — **jamais** `*:11435` ;
- `/Users/penny/.ollama` appartient à `penny`.

Sans `disown`, zsh affiche `you have running jobs` au `exit` : taper `disown`, puis `exit`.

Vérifier depuis votre compte :
```
$ curl -s http://127.0.0.1:11435/api/version; echo
```

## 9. Vérification globale

```
$ su - penny
penny% cd ~/penny && cp config/machine.example.env config/machine.env
penny% ./scripts/install.sh
```
Attendu : toutes les lignes en `ok`, puis `Prérequis OK.`

## 10. Démarrage automatique de Docker et d'Ollama pour `penny`

**Principe.** `penny` n'ouvre jamais de session graphique : un LaunchAgent ne se lancerait pas.
On installe deux **LaunchDaemons système** qui tournent sous l'identité `penny` (clé `UserName`) :

| Service | Lance | Comportement |
|---|---|---|
| `local.penny.orbstack` | `orb start` | une fois au démarrage ; les conteneurs reviennent grâce à `restart: unless-stopped` |
| `local.penny.ollama` | `ollama serve` sur `127.0.0.1:11435` | relancé automatiquement s'il s'arrête |

Avec FileVault, ils démarrent après le déverrouillage du disque (votre mot de passe au démarrage).

**Sécurité.** Les plists sont posés en `root:wheel 644` dans `/Library/LaunchDaemons`.
Le script refuse tout binaire que `penny` pourrait modifier, et les plists n'appellent
**aucun script du dépôt**. Sinon `penny` pourrait réécrire ce que launchd exécute.

**Installation**, depuis **votre** compte (administrateur), dans votre copie du dépôt :

```
$ cd ~/GIT/penny
$ git pull
$ cp -n config/machine.example.env config/machine.env   # si absent
$ ls -l /opt/homebrew/bin/orb /opt/homebrew/bin/ollama  # sinon renseigner PENNY_*_BIN
$ sudo ./scripts/mac/install-services.sh
```
Attendu : les deux binaires `non modifiable par penny`, deux lignes `root:wheel 644`,
`installé, chargé`, puis `Ollama répond sur 127.0.0.1:11435`.

État à tout moment : `./scripts/mac/install-services.sh --status`.
Journaux : `/Users/penny/Library/Logs/penny/` (lisibles par `penny` seulement).
Désinstallation : `sudo ./scripts/mac/install-services.sh --uninstall`.

### Tests

À faire dans l'ordre. Noter chaque résultat (réussi / échoué) dans le tableau « Constats ».

1. **Redémarrage** : redémarrer le Mac, déverrouiller, ouvrir **votre** session, **sans `su`** :
   ```
   $ curl -s http://127.0.0.1:11435/api/version; echo
   $ sudo lsof -nP -iTCP:11435 -sTCP:LISTEN
   $ su - penny -c "docker version --format '{{.Server.Version}}'"
   $ sudo cat /Users/penny/Library/Logs/penny/orbstack.log
   ```
   Attendu : `{"version":"0.40.5"}` ; `ollama … penny … 127.0.0.1:11435`, **jamais** `*:11435` ;
   version de Docker affichée **sans avoir lancé `orb start`**.
   > Si le journal d'OrbStack contient `missing TCC permission`, l'autorisation de l'étape 6
   > ne s'applique pas aux daemons : **c'est le risque principal, à signaler**.
2. **Relance d'Ollama** : `sudo pkill -u penny -f "ollama serve"`, attendre 15 s, relancer le `curl` → répond.
3. **Votre Ollama intact** : `curl -s http://127.0.0.1:11434/api/version` répond toujours.
4. **Plists non modifiables par penny** (doit **échouer**) :
   ```
   $ su - penny -c 'touch /Library/LaunchDaemons/local.penny.ollama.plist'
   ```
   Attendu : `Permission denied`.
5. **Garde-fou du script** (doit **échouer**) : `./scripts/mac/install-services.sh` sans `sudo`
   → `ERREUR : lancer avec sudo…`.
6. **Désinstallation** : `--uninstall`, redémarrer : `curl … 11435` ne répond plus. Puis réinstaller.

### Équivalent sur le PC IA (Linux, profil `linux-gpu`)

Rien de spécifique à Penny à installer : Ollama tourne dans Compose (`compose.yaml`),
systemd démarre Docker (`systemctl enable docker`) et la politique `restart: unless-stopped`
relance tous les conteneurs. Ces LaunchDaemons disparaissent à la migration.

---

## Pièges rencontrés

| Symptôme | Cause | Solution |
|---|---|---|
| `sudo -iu penny` refuse votre mot de passe | `sudo` attend **votre** mot de passe et exige un compte administrateur | Utiliser `su - penny` (mot de passe de `penny`) |
| `orb start` : `missing TCC permission` | Autorisation macOS jamais accordée à `penny` | Étape 6 |
| `permission denied … unix:///var/run/docker.sock` | `penny` tente d'utiliser **votre** Docker (refus = isolation correcte) | `docker context use orbstack` après l'étape 6 |
| Un second `su - penny` se lance tout seul | Plusieurs lignes collées d'un coup après un `su` | Coller ligne par ligne ; `exit` jusqu'à retrouver votre invite |
| `zsh: you have running jobs` | Ollama lancé en tâche de fond | `disown` puis `exit` |
| Écran « Docker / Kubernetes / Linux » | Premier lancement d'OrbStack | Choisir Docker |

## Constats de sécurité (testés)

| Test | Résultat |
|---|---|
| `penny` utilise le Docker du développeur | Refusé |
| Docker de `penny` isolé dans `/Users/penny/.orbstack` | Oui |
| Ollama de `penny` écoute sur le réseau | Non, 127.0.0.1 uniquement |
| Lecture croisée des dossiers personnels | Refusée dans les deux sens |
| Ollama de `penny` joignable depuis votre compte | **Oui** : 127.0.0.1 n'isole pas les comptes d'un même Mac → la base et le serveur MCP de Penny exigeront une authentification même en local |

## Limites du prototype

- Après un redémarrage, FileVault bloque tout jusqu'à la saisie d'un mot de passe ; les
  services de l'étape 10 démarrent ensuite seuls.
- Mac en veille = Penny à l'arrêt (rappels de secours via ntfy sur le VPS).
- OrbStack sans interface graphique ne se met pas à jour seul : mise à jour volontaire avec
  `brew upgrade --greedy orbstack`, ce qui convient aux versions figées.
