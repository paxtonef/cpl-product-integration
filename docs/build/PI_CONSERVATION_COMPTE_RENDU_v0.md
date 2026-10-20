# Suite du bloc 3B — conservation et purge — compte rendu v0

Date : 2026-10-19. Branche PI `pi-3b-conservation-purge`, depuis `pi-3b-reception-livraison` @
`7010674`. VIR `a4c0172`, PGDR `1c5a5cc`, CPL `bc09253` : lus, **non modifiés** ;
`deploy/COMPOSITION.env` inchangé. Aucune durée décidée. Aucun push, aucune fusion, aucun
déploiement, aucune migration réelle, aucune suppression de donnée réelle, aucun appel extérieur.
Guide : `docs/GUIDE_MISE_EN_LIGNE.md` §8, §9 ; liste de réception : `docs/RECEPTION.md` 3.15a–j.

Étiquettes : [exécuté] [code] [documentation] [non vérifiable].

## 1. Commits

| Dépôt | Commit | Contenu |
|---|---|---|
| PI | `a01c82f` | `product_integration.conservation` (politique, identifiants, médias, journaux, sauvegardes, purge, CLI) ; schéma `pi_auth` v4 (trace) ; 410 « no longer kept » (identification, média) ; `purger.sh`, `sauvegarder.sh`, `restaurer.sh`, `nettoyer_sauvegardes.sh`, `lancer_montage.sh` ; tests |
| PI | commit de ce compte rendu | guide, liste de réception, compte rendu |

## 2. Ce qui est livré

- **Politique** [code] [exécuté] : `PI_CONSERVATION_{IDENTIFIANTS,DOSSIERS,MEDIAS,JOURNAUX,SAUVEGARDES}_JOURS`,
  jours entiers ou `illimitee`, absente = non définie ; `VIR_RETENTION_DAYS` reste propre à VIR.
  Point de départ des identifiants : `enregistrement_cpl` (seul implémenté ; création, dernière
  confirmation, dernière consultation listées ; choix du propriétaire).
- **Purge** [code] [exécuté] : simulation par défaut (même sans politique) ; exécution refusée sans
  politique complète et pour une durée de dossiers ; lots transactionnels ; arrêt propre ; reprise ;
  trace `pi_auth.conservation_operations` / `identifier_expunctions` sans valeur.
- **Identifiants** : `asset_identity_resolutions` et `vehicle_details` vidés et marqués ; artefacts
  `vir_resolution` **non vidés** : arrêt sur ce point (invariants CPL REQ-B6-053 à 059, guide §9.3).
- **Médias** par âge (pixels non vérifiables) ; **journaux** tournés ; **sauvegardes** à manifeste,
  nettoyage limité aux dossiers reconnus.
- **Restauration** : verrou de démarrage, sessions révoquées, purge avant réouverture, aucun
  redémarrage automatique.

## 3. Essais [exécuté]

Cluster PostgreSQL 16 dédié (port 55541, bases temporaires `pi01_test`, `pi_restore_cons_a`,
`pi_restore_cons_b`, `pi_restore_cons_nav`), garde réseau (toute connexion hors boucle locale
refusée), identifiants fictifs uniques, durées d'essai 30 jours (non approuvées).

| Suite | Résultat |
|---|---|
| PI pytest complet (`a01c82f`, montage vivant de développement) | **380 passed, 0 skipped, 0 failed** (371 + 9) |
| Tests de conservation depuis un clone neuf du commit | **17 passed** (3 fichiers conservation + 2 de non-régression) |
| Frontend : `tsc -b --noEmit` / vitest / `vite build` | OK / **52 passed** / OK |
| Navigateur (Chromium, lancement de production HTTPS, frontend construit) | **2 passed** : dossier après purge ; après restauration |
| Journaux du montage vivant et sorties des commandes | 0 VIN, 0 plaque |

Défauts trouvés : aucun dans le code livré ; trois erreurs des essais eux-mêmes corrigées (compte
attendu, double comptage d'un balayage, ordre sauvegarde/antidatage). Playwright A–P du frontend non
relancé (seul le message d'erreur a changé, couvert par vitest et le test navigateur).

## 4. Non fait ou non vérifiable

- Expurgation des artefacts `vir_resolution` : impossible sans évolution de CPL [non vérifiable].
- Suppression des dossiers et résultats : aucun mécanisme CPL ; seule `illimitee` est exécutable.
- `deploy/installer.sh` non relancé (pas de dépôt de roues hors ligne dans cette passe) ;
  composition inchangée, vérification par clone neuf du commit.
- Copie VIR « avant-restauration » de la base VIR : propre à VIR, non traitée.
- Durées et point de départ : décisions du propriétaire.

## 5. Suite — conservation 1/3 à 3/3 et contrôle navigateur (2026-10-20)

Les points 4 « expurgation des artefacts », « suppression des dossiers » et « copie VIR » ci-dessus
sont **levés**. Composition : PI `pi-conservation-integration`, CPL `cpl-conservation-plaque` @ `ced7e4b`
(migrations 030 REQ-B6-091 et 031 REQ-B5-116), PGDR `55f76ae`, VIR `a4c0172` (non modifié).

| Passe | Commits | Résultat |
|---|---|---|
| 1/3 plaque et VIN dans `vir_resolution` | CPL `253ff8f` ; PI `4de8136` | nouvelles écritures sans identifiants ; expurgation gouvernée tracée [exécuté] |
| 2/3 dossiers échus | CPL `ced7e4b` ; PI `c9c5653` | suppression gouvernée, une transaction par dossier, trace sans contenu [exécuté] |
| 3/3 intégration | PI `4e687aa` | relais fermé pour un dossier supprimé ; purge intégrée et ordonnée ; restauration verrouillée jusqu'aux migrations et à la conservation ; copies mises de côté recensées [exécuté] |
| Contrôle navigateur | PI commit de ce complément | 3.15r réussi (voir ci-dessous) [exécuté] |

**Contrôle navigateur** (Chromium, `scripts/lancer_montage.sh` en production HTTPS, frontend
construit, VIR simulé, PGDR avec notice FICTIVE) : un compte A avec deux dossiers et un résultat
confirmé chacun, un compte B avec un dossier. Une sauvegarde est prise alors que le second dossier
de A est échu (antidaté de 40 jours, durée d'essai 30 jours, non approuvée), puis la purge
opérateur le supprime. Dans le navigateur : le dossier conservé s'affiche pour A avec son résultat
inchangé ; le dossier supprimé répond « This item could not be found » ; B ne voit ni l'un ni
l'autre et garde son propre dossier. Rejoué après restauration de la sauvegarde ancienne dans une
base neuve (`deploy/restaurer.sh`, migrations, purge : « 1 dossier(s) échu(s) supprimé(s) ») et
démarrage du montage sur elle : même résultat. 2 passed. Aucun défaut trouvé : aucune correction de
code dans ce complément.

Reste [non vérifiable] : effacement physique (guide §9.6) ; durées et première exécution réelle
(migrations 030/031, expurgation, suppression) : étape de déploiement distincte, décisions du
propriétaire.
