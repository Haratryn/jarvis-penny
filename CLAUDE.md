# Penny — règles du projet pour Claude Code

Penny est un assistant personnel local : une seconde mémoire qui relie mails, agendas,
documents, papiers, contrats, abonnements, véhicules et domotique, suit les engagements
et anticipe les échéances. Référence complète : « Jarvis — choix et objectifs » (synthèse)
et « Jarvis — revue contradictoire » (Claude Docs). « Jarvis » était le nom de travail.

## Règles absolues

1. **Fausses données uniquement.** Aucun vrai mail, agenda, document ou contact ne passe
   dans une session Claude Code. Les tests utilisent `tests/fixtures/` (données inventées).
   Si une tâche semble exiger de vraies données, s'arrêter et demander.
2. **Aucun secret dans Git, les prompts, les logs ou la mémoire.** Les secrets passent par
   la couche `secrets` (trousseau macOS sur Mac, coffre chiffré sur Linux). Jamais en clair
   dans un fichier de config, une variable d'environnement commitée ou un exemple.
3. **Rien ne s'installe à la main.** Tout ce qui est installé est décrit dans le dépôt
   (Compose, `scripts/install.sh`, versions figées). Une étape manuelle = un bug.
4. **Versions figées partout** : images Docker par tag précis (idéalement digest), modèles
   par tag, dépendances par fichier de verrouillage.
5. **Services sur 127.0.0.1 uniquement.** Bases de données et API de modèles jamais exposées.
6. **Composants éprouvés plutôt que sécurité maison** (authentification, chiffrement, jetons).

## Architecture à respecter

- **La base SQL est la source de vérité** (éléments, mentions, entités, faits avec statut,
  source, date d'enregistrement, validité, `replaced_by`). Les sources originales sont
  immuables. Vecteurs, graphes, résumés et coffre Obsidian/OKF sont des **dérivés**, jamais
  des preuves.
- **Le coffre Obsidian (format OKF) est généré à sens unique** depuis la base ; seule la
  section « Mes notes » est relue, comme faits déclarés.
- **Le contexte donné au modèle est construit par Penny** depuis la base : entité résolue,
  faits valides, preuves citées, filtrage par règles (pas par le modèle), budget de tokens.
- **Circuit d'action** : Hermes propose → contrôleur (règles déterministes, ne lit pas le
  raisonnement de l'agent) → autorisation liée au hash des paramètres exacts, avec
  expiration → exécuteur séparé (seul détenteur des jetons d'écriture, clé d'idempotence)
  → vérificateur qui relit le système cible. Sans preuve : « non confirmé », jamais « c'est fait ».
- **Pas de suppression autonome.** Les déplacements demandent validation. Droit à l'oubli explicite.
- **Fusion d'entités = proposition réversible**, distincte du rattachement d'une mention.

## Portabilité (Mac pour le prototype, Linux pour la cible)

- Le code de Penny ne contient **rien de spécifique au Mac** (pas de launchd, trousseau,
  FileVault). Ces spécificités vivent uniquement dans le profil `mac` du script d'installation
  et dans l'implémentation `mac` de la couche secrets.
- Les services se parlent en HTTP ; changer de machine = changer des adresses dans
  `config/machine.env`, pas le code.
- Profils Compose : `mac` (inférence native hors Docker) et `linux-gpu` (inférence en conteneur).
- Vérifier que chaque image existe en arm64 **et** amd64.

## Manière de travailler

- Itérations courtes ; on valide sur schéma avant de coder une brique nouvelle.
- Réutiliser l'existant open source plutôt que redévelopper.
- Distinguer dans les notes ce qui est **documenté**, **supposé** et **testé**.
- Chaque fonctionnalité arrive avec ses tests de réussite **et** d'échec (cf. revue contradictoire).
- Langue : code et identifiants en anglais, documentation et messages utilisateur en français.
