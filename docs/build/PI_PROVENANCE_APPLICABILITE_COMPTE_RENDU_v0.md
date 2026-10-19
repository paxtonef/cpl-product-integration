# Passe identité, provenance et applicabilité — compte rendu v0

Date : 2026-10-19. Rien n'est décidé ici sur l'applicabilité réelle d'une notice. Aucun contenu constructeur,
aucun VIN, aucune plaque. Aucun appel fournisseur, aucun push, aucune fusion, aucun déploiement, aucune
migration réelle.

## 1. Branches et commits

| Dépôt | Branche | Départ | Commit |
|---|---|---|---|
| PGDR | `v1-fiat-provenance` | `v1-3b-reception` @ `1c5a5cc` | `79db828` |
| PI | `pi-fiat-provenance` | `pi-3b-conservation-purge` @ `a676809` (`a01c82f` code) | commit de ce compte rendu |
| VIR | — | `a4c0172` | non modifié |
| CPL | — | `bc09253` | non modifié |

`deploy/COMPOSITION.env` et le guide §1 sont actualisés : PGDR passe à `79db828`.

## 2. Avant et après

| Point | Avant (bloc 3A) | Après |
|---|---|---|
| Génération confirmée par le conducteur seulement | retirée par `map_resolution` : `None` dans l'identité, listée non résolue, rien d'autre | même retrait de `vehicle_identity` (lu par tous les consommateurs existants), **plus** `field_provenance.generation` : `user_confirmed`, valeur, source `driver_confirmation`, méthode `user_confirmation` |
| Autres champs | valeur sans provenance | statut de VIR (`epistemic_status`) par champ, sans promotion ; aucune entrée si VIR n'a pas de preuve |
| Véhicule | non désigné | `vehicle_ref` = actif CPL du dossier, transmis par le parcours |
| Refus de notice | statut et message | statut et message inchangés, **plus** motifs, clés comparées avec leur provenance, reste à vérifier, prochaine étape (affichés dans le dossier) |
| Ouverture | identité suffisante, égalité, `applicability_established` | les mêmes, et : une clé seulement confirmée n'ouvre jamais par le drapeau de la notice ; une attestation limitée à ce véhicule et à cette version de la notice ouvre |

Les règles d'acceptation et de refus figurent dans `docs/exigences/PROVENANCE_ET_APPLICABILITE_V1.md` de
PGDR (§2 à §4).

## 3. Tests 3A dont le comportement change

| Test | Changement et raison |
|---|---|
| `tests/test_notice_parcours.py::test_g_a_driver_confirmed_value_is_never_promoted_to_a_decode` | Le statut passe de `vehicle_identity_insufficient` à `applicability_not_confirmed`. La confirmation arrive maintenant avec sa provenance ; elle n'est plus traitée comme une valeur inconnue. Le parcours n'ouvre toujours rien, avec le motif « seule confirmation du conducteur ». |
| `tests/test_notice_parcours.py::test_g_provisional_identity_is_refused_and_no_notice_is_assumed` | Statut, message et page inchangés. La réponse porte en plus les motifs et la prochaine étape, et l'égalité de dictionnaire stricte a été remplacée. |
| `frontend/tests/e2e/o-notice-parcours.spec.ts` (O4) | Le message reste le même. Le refus affiche en plus les motifs et la prochaine étape, et le texte exact du bloc entier a été remplacé. |
| `tests/test_pgdr_handoff_confirmation.py` | Docstring seulement : elle disait que PGDR n'avait pas d'emplacement pour la provenance. Les assertions sont inchangées et passent. |

Défaut trouvé pendant l'essai O4 et corrigé : la prochaine étape suggérait une confirmation du conducteur
même pour un **modèle** inconnu. Elle ne la suggère plus que pour la génération, seule clé confirmable ; un
test vérifie l'égalité avec `CONFIRMABLE_FIELDS` de VIR.

## 4. Essais [exécuté]

| Suite | Résultat |
|---|---|
| PGDR complète (hors `packaging`) | **1046 passed** (référence de départ : 1005) |
| PI complète, avec le montage de développement des nouveaux arbres (état final) | **392 passed, 0 skipped, 0 failed** (référence : 380 avant la passe) |
| PI `tests/test_provenance_applicabilite.py` | 9 passed : chaîne réelle VIR (mode réel, faux transports) → PI → CPL → `map_resolution` → `/api/v1/vir-handoff`, sans `PGDR_V1_DEV_VEHICLE` ; un test par appelant (parcours, Photo-First, orchestration) ; deux titulaires ; aucun appel fournisseur à la confirmation, la correction, la consultation ou le retrait |
| PI `tests/test_provenance_navigateur.py` (Chromium, lancement de production HTTPS) | 3 passed : motifs et provenance du refus ; génération « confirmé par le conducteur » ; ouverture du seul véhicule attesté |
| Frontend : `tsc -b --noEmit` / vitest | OK / **53 passed** |
| Playwright O4 et P, contre le montage de développement | 2 passed |

Les autres specs Playwright (A à N, O1 à O3) n'ont pas été relancées.

## 5. Limites

- Un essai fictif prouve le raccordement technique, pas l'applicabilité réelle d'une notice.
- Les appelants Photo-First et orchestration ne transmettent pas `vehicle_ref`. Ils ne consultent aucune
  attestation, et une clé seulement confirmée y reste une lacune.
