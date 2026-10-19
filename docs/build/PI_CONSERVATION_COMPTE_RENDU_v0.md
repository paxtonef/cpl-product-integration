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
