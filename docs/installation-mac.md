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

> Le Docker de `penny` **ne démarre pas automatiquement** sur le Mac (voir étape 10).
> **Après chaque redémarrage**, depuis votre compte :
> ```
> $ su - penny -c 'orb start'
> ```

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
> **Constaté le 08/11** : Ollama est installé par l'appli **Ollama.app** (téléchargée sur
> ollama.com) ; binaire `/Applications/Ollama.app/Contents/Resources/ollama`, lien
> `/usr/local/bin/ollama`. **Problème ouvert** : l'appli se met à jour seule, donc la version
> de `penny` n'est pas figée. À décider : couper la mise à jour automatique, ou passer à un
> binaire versionné installé par le script.

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

## 10. Démarrage automatique d'Ollama pour `penny`

**Principe.** `penny` n'ouvre jamais de session graphique : un LaunchAgent ne se lancerait pas.
On installe un **LaunchDaemon système** qui tourne sous l'identité `penny` (clé `UserName`) :

| Service | Lance | Comportement |
|---|---|---|
| `local.penny.ollama` | `ollama serve` sur `127.0.0.1:11435` | au démarrage, relancé automatiquement s'il s'arrête |

Avec FileVault, il démarre après le déverrouillage du disque (votre mot de passe au démarrage).

**Pourquoi pas Docker.** Testé le 08/11/2026 : OrbStack lancé par launchd échoue au démarrage
à froid (`missing TCC permission for data storage directory`). Ses données sont dans
`~/Library/Group Containers`, protégé par TCC, et l'autorisation de l'étape 6 ne vaut pas pour
launchd (même cas : issue OrbStack #2580, sans contournement). Le Mac sert au développement ;
le service 24 h/24 sera assuré par le PC Linux, où systemd démarre Docker nativement. On
accepte donc un `orb start` manuel après chaque redémarrage (étape 7).

**Sécurité.** Le plist est posé en `root:wheel 644` dans `/Library/LaunchDaemons`.
Le script refuse tout binaire que `penny` pourrait modifier, et le plist n'appelle
**aucun script du dépôt**. Sinon `penny` pourrait réécrire ce que launchd exécute.

**Installation**, depuis **votre** compte (administrateur), dans votre copie du dépôt :

```
$ cd ~/GIT/penny
$ git pull
$ cp -n config/machine.example.env config/machine.env   # si absent
$ sudo ./scripts/mac/install-services.sh
```
Le script trouve seul `ollama` dans les emplacements connus (appli dans `/Applications`,
Homebrew). En cas d'échec, renseigner `PENNY_OLLAMA_BIN` dans `config/machine.env`.
Il retire aussi l'ancien service `local.penny.orbstack` s'il est encore installé.

Attendu : `non modifiable par penny`, une ligne `root:wheel 644`, `installé, chargé`,
puis `Ollama répond sur 127.0.0.1:11435`.

État à tout moment : `./scripts/mac/install-services.sh --status`.
Journaux : `/Users/penny/Library/Logs/penny/` (lisibles par `penny` seulement).
Désinstallation : `sudo ./scripts/mac/install-services.sh --uninstall`.

### Tests

À faire dans l'ordre, **une commande à la fois** (un bloc collé derrière `sudo` ou `su` est avalé).

1. **Redémarrage à froid** — testé OK le 08/11 : redémarrer, déverrouiller, ouvrir **votre**
   session, **sans `su`** :
   ```
   $ curl -s http://127.0.0.1:11435/api/version; echo
   $ sudo lsof -nP -iTCP:11435 -sTCP:LISTEN
   ```
   Attendu : `{"version":"0.40.5"}` ; `ollama … penny … 127.0.0.1:11435`, **jamais** `*:11435`.
   > Un service n'est validé qu'après un vrai redémarrage : avant, il peut sembler marcher
   > parce que le programme tournait déjà.
2. **Relance d'Ollama** : `sudo pkill -u penny -f "ollama serve"`, attendre 15 s, relancer le `curl` → répond.
3. **Votre Ollama intact** : `curl -s http://127.0.0.1:11434/api/version` répond toujours.
4. **Plist non modifiable par penny** (doit **échouer**) :
   ```
   $ sudo -u penny touch /Library/LaunchDaemons/local.penny.ollama.plist
   ```
   Attendu : `Permission denied`.
5. **Garde-fou du script** (doit **échouer**) : `./scripts/mac/install-services.sh` sans `sudo`
   → `ERREUR : lancer avec sudo…`.
6. **Désinstallation** : `--uninstall`, redémarrer : `curl … 11435` ne répond plus. Puis réinstaller.

### Équivalent sur le PC IA (Linux, profil `linux-gpu`)

Rien de spécifique à Penny à installer : Ollama tourne dans Compose (`compose.yaml`),
systemd démarre Docker (`systemctl enable docker`) et la politique `restart: unless-stopped`
relance tous les conteneurs. Ce LaunchDaemon disparaît à la migration.

## 11. Penny, incrément 1 : analyser un dossier OneDrive (lecture seule)

**Ce que fait cette version.** Penny inventorie un dossier de votre OneDrive, en télécharge une
copie **sous le compte `penny`**, en extrait le texte et une fiche par document **avec le modèle
local**, puis répond à vos questions en citant ses sources. Rien n'est modifié dans OneDrive : le
jeton Microsoft ne donne que des droits de lecture.

**Séparation avec Claude (règle).** Les données réelles n'existent que sous `/Users/penny`.
Claude Code tourne sous votre compte : macOS l'empêche de les lire. Ne jamais lancer Claude Code
sous `penny`. La seule sortie à transmettre à Claude est `penny diag` (compteurs, sans aucun nom
de fichier ni contenu). Un problème sur un vrai document se reproduit avec un document inventé.

### 11.1 Outils (votre compte)

```
$ brew install uv rclone
```

### 11.2 Déployer Penny

Depuis votre copie du dépôt, à jour et sans modification en cours :
```
$ cd ~/GIT/penny && git pull
```
```
$ sudo ./scripts/mac/deploy-penny.sh
```
Attendu : `Penny <commit> installée dans /opt/penny/releases/…`, la configuration de `penny`
créée, puis `bge-m3 : prêt` et `qwen3:8b : prêt`. Le premier déploiement télécharge Python,
les dépendances et les modèles : compter plusieurs minutes.

Vérification :
```
$ ls -ld /opt/penny/current/
$ su - penny -c 'penny status'
```
Attendu : propriétaire `root wheel` ; `Aucun dossier analysé.`

### 11.3 Connecter OneDrive en lecture seule

```
$ su - penny
penny% penny onedrive connect
```
Penny lance l'assistant de rclone et rappelle les réponses à donner :
- nom `penny-onedrive`, stockage `onedrive`, `client_id` et `client_secret` vides ;
- options avancées : `access_scopes` = `Files.Read offline_access`
  (si refusé : « Read only access to all resources ») ;
- authentification par navigateur : **non**. rclone affiche une commande
  `rclone authorize "onedrive" …` : la copier, l'exécuter **dans un autre terminal de votre
  compte** ; le navigateur s'ouvre. **Vérifier que Microsoft n'affiche que des droits de
  lecture**, accepter, puis coller le jeton dans le terminal de `penny` ;
- choisir **OneDrive personnel** ;
- enfin `s) Set configuration password` : choisir un mot de passe (configuration chiffrée).

Option : ranger ce mot de passe dans le trousseau de `penny` pour ne pas le saisir à chaque fois.
```
penny% security add-generic-password -a penny -s penny-rclone -w
```
puis décommenter `PENNY_RCLONE_PASSWORD_COMMAND` dans `~/.config/penny/penny.env`.
> **À tester** : via `su`, le trousseau de `penny` peut être verrouillé. Si Penny affiche
> « trousseau verrouillé », lancer `security unlock-keychain` (mot de passe de `penny`), ou
> laisser la ligne commentée et saisir le mot de passe à chaque lancement.

```
penny% penny onedrive check
```
Attendu : l'espace utilisé et total, puis `Accès OneDrive : OK`.

### 11.4 Premier passage

**Avant de lancer** : écrire pour vous seul (pas dans le dépôt, pas à Claude) **10 questions** dont
vous connaissez la réponse dans ce dossier, dont **2 sans réponse**. C'est le critère de réussite.

```
penny% penny scan "Chemin/Du/Dossier" --limit 50
penny% penny status
```
- L'inventaire complet s'affiche tout de suite ; 50 fichiers au plus sont analysés à chaque passage.
  Relancer la même commande pour continuer (ou sans `--limit` pour tout faire).
- `Ctrl-C` à tout moment : la commande suivante reprend où elle s'était arrêtée.
- Le premier PDF déclenche le téléchargement des modèles de Docling (une fois).
- `penny status` indique combien de fichiers sont **sans texte** (scans, photos) : ils sont listés,
  en attente d'OCR (incrément ultérieur).

### 11.5 Utiliser

```
penny% penny docs                       # inventaire : date, type, titre, personnes, chemin
penny% penny docs --type facture
penny% penny docs --sans-texte          # scans et photos non lus
penny% penny ask "Où est mon attestation d'assurance habitation ?"
penny% penny diag                       # rapport anonymisé, le seul à transmettre à Claude
```
Chaque réponse cite ses sources (`[1]`, `[2]`… avec le chemin OneDrive) et rappelle le périmètre :
« N documents analysés sur M ». Une citation qui ne correspond à aucun extrait retrouvé est retirée.

### 11.6 Critère de réussite de l'incrément 1

| Test | Attendu |
|---|---|
| Inventaire | même nombre de fichiers que OneDrive pour ce dossier ; chacun a un statut |
| 10 questions | au moins 8 bonnes avec la bonne source ; aucune source inventée |
| 2 questions sans réponse | « Je n'ai pas trouvé… » et rappel du périmètre |
| Relance de `penny scan` | `0 analysés` : rien n'est refait |
| Interruption (`Ctrl-C`) puis relance | reprise sans tout refaire |
| `penny diag` | aucun nom de fichier ni contenu |
| Temps | relevés par `penny diag` (non bloquant) |

Bilan à noter : score sur 10, temps moyen par document et par question, limites constatées.

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
| `vmgr … missing TCC permission for data storage directory` au démarrage | OrbStack lancé par launchd (testé le 08/11) | Pas de démarrage automatique de Docker sur le Mac : `su - penny -c 'orb start'` |
| Un bloc de commandes collé derrière `sudo` n'affiche rien | La saisie du mot de passe avale les lignes suivantes | Une commande à la fois |

## Constats de sécurité (testés)

| Test | Résultat |
|---|---|
| `penny` utilise le Docker du développeur | Refusé |
| Docker de `penny` isolé dans `/Users/penny/.orbstack` | Oui |
| Ollama de `penny` écoute sur le réseau | Non, 127.0.0.1 uniquement (aussi lancé par launchd) |
| Ollama de `penny` démarre seul après redémarrage | Oui (LaunchDaemon, 08/11) |
| Docker de `penny` (OrbStack) démarre par launchd | **Non** : refus TCC au démarrage à froid |
| Lecture croisée des dossiers personnels | Refusée dans les deux sens |
| Ollama de `penny` joignable depuis votre compte | **Oui** : 127.0.0.1 n'isole pas les comptes d'un même Mac → la base et le serveur MCP de Penny exigeront une authentification même en local |

## Limites du prototype

- Après un redémarrage, FileVault bloque tout jusqu'à la saisie d'un mot de passe ; Ollama
  démarre ensuite seul, **Docker non** : `su - penny -c 'orb start'` (étape 7).
- Mac en veille = Penny à l'arrêt (rappels de secours via ntfy sur le VPS).
- OrbStack sans interface graphique ne se met pas à jour seul : mise à jour volontaire avec
  `brew upgrade --greedy orbstack`, ce qui convient aux versions figées.
