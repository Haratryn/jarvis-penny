# Jeu de test vérité-terrain (données inventées)

Tout ici est **fictif**. Aucun vrai nom, adresse, numéro ou mail.
Domaines d'adresses : uniquement des sous-domaines de `example.com`, `example.org`, `example.net`.

## Vie inventée (`vie-inventee/`)

Généré par `generate_vie_inventee.py` (bibliothèque standard, déterministe) :

```
python3 tests/fixtures/generate_vie_inventee.py
```

Ne pas modifier les fichiers générés à la main : modifier le script et le relancer.

| Dossier | Contenu | Usage |
|---|---|---|
| `corpus/mails/` | 103 mails `.eml` (53 utiles + 50 de bruit), fils de discussion, pièces jointes | **à ingérer** |
| `corpus/agendas/` | `agenda-perso.ics`, `agenda-pro.ics` (Outlook) | **à ingérer** |
| `corpus/documents/` | 10 papiers (texte extrait : assurances, cartes grises, CT, factures…) | **à ingérer** |
| `evaluation/` | 24 questions et réponses attendues (`questions.json`, `QUESTIONS.md`) | **ne jamais ingérer** |

**Date de référence : 10/11/2026.** Les questions « faut-il relancer ? » ou « 30 prochains jours »
se calculent par rapport à elle, pas à la date réelle.

**Le foyer.** Julien Marchal (salarié d'Altimea), sa compagne Claire Rouvière, leur fils Hugo
(en 3e) ; deux voitures (Renault Mégane E-Tech, Peugeot 2008) ; assurés chez Mutuelle Horizon.

**Trois familles de questions** :
- **A. Mémoire datée** : dernier sinistre (survenance, déclaration, indemnisation), montants,
  échéances, abonnements, absence d'information (« je ne sais pas »).
- **B. État des échanges** : dernier mail sur un sujet, qui attend qui, faut-il relancer.
- **C. Engagements et vigilance** : rendez-vous récurrent, congé à poser avant un rendez-vous,
  appel à passer, suivi du référencement d'un site, briefing des 30 jours.

**Pièges** : deux Antoine (collègue et ami), un surnom (« Toto »), une adresse reprise par une autre
personne (comptable), une date annoncée puis corrigée (contrôle technique), un tarif qui change,
un abonnement résilié, un mail piégé (faux domaine et consignes adressées aux assistants).

**Règle des agendas** : un congé qui ne figure pas dans l'agenda Outlook n'est pas posé.
