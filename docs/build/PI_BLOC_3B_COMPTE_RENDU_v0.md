# Bloc 3B — réception commune et livraison — compte rendu v0

Date : 2026-10-19. Branches : PI `pi-3b-reception-livraison` (depuis `pi-3a-persistance-securite`
@ `a325c23`), PGDR `v1-3b-reception` (depuis `v1-3a-securite` @ `48d5da4`). VIR `a4c0172` et CPL
`bc09253` : lus, non modifiés (schéma CPL inchangé). Aucun push, aucune fusion, aucun
déploiement, aucune migration réelle, aucun appel à un fournisseur, un modèle ou un service
extérieur. Liste de réception : `docs/RECEPTION.md` ; guide : `docs/GUIDE_MISE_EN_LIGNE.md`.

## 1. Commits

| Dépôt | Commit | Contenu |
|---|---|---|
| PGDR | `1c5a5cc` | page /v1 : statut d'enregistrement du produit sous la restitution, nouvelle tentative ; README : marché de la notice non vérifiable |
| PI | `d9f8fdd` | « Résultat non enregistré » et `POST /v1/parcours/{id}/record` ; Origine sur toutes les écritures ; réception navigateur ; compteur des consultations VIR pour la spec N ; défaut `reset-password` sans secret ; composition PGDR `1c5a5cc` |
| PI | `281d243` | défauts trouvés à la livraison : arrêt borné, journaux conservés au redémarrage, identification VIR échue (410) |
| PI | commit de ce compte rendu | guide, liste de réception, compte rendu (documentation seule) |

`deploy/COMPOSITION.env` : VIR `a4c0172f…`, PGDR `1c5a5cc0…`, CPL `bc092531…`, GGM `41459158…`.
Installation vérifiée au commit `281d243` ; le commit suivant ne touche que `docs/`.

## 2. Changements et défauts

### 2.1 Échec d'enregistrement CPL (point 3) [code] [exécuté]

- La restitution relayée porte `product_record` : `recorded` (« Résultat enregistré dans votre
  dossier… ») seulement après la validation de l'écriture CPL ; sinon `not_recorded`
  (« Résultat non enregistré… ») avec `retry` et le libellé « Réessayer l'enregistrement ».
  Les textes du constructeur sont toujours renvoyés et affichés.
- L'enregistrement refusé reste avec le parcours (mémoire de PI). `POST
  /api/v1/parcours/{id}/record` : PI seul, aucun appel à PGDR, au tri ni à VIR ; même clé
  d'idempotence (aucun doublon) ; propriétaire, session, jeton CSRF, Origine exacte, JSON ;
  409 si rien n'a été confirmé ; 404 « parcours inconnu » pour autrui ou après redémarrage.
- PGDR (`1c5a5cc`) affiche le statut sous la restitution (`role=alert` si non enregistré) ;
  servie seule, la page ne dit rien d'un enregistrement.
- Décision restante : validation des textes nouveaux par le propriétaire.

### 2.2 Origine (point 5) [code] [exécuté]

`product_integration.api.origin` : toute écriture (POST, PUT, PATCH, DELETE), connexion comprise,
refusée (403 `CSRF_REJECTED`) si `Origin` diffère de l'origine du produit ou si
`Sec-Fetch-Site` n'est pas `same-origin`. Sans `Origin` (outils, tests), le jeton CSRF reste
exigé : un navigateur envoie toujours `Origin` sur ces requêtes (`fetch` en mode cors, ce qu'utilise
le frontend). Le relais garde l'exigence d'`Origin`. Le test prend les routes d'écriture dans
l'application elle-même (15 routes, relais compris, 5 en-têtes étrangers chacune) : une route ajoutée plus tard
est couverte.

### 2.3 Marché de la notice (point 4) [documentation] [non vérifiable]

Aucun champ de marché dans le manifeste, la revue ni l'identité VIR : critère non vérifiable,
jamais présenté comme satisfait, non déduit du pays d'immatriculation. `git grep` de PGDR :
aucune règle (code, README, proposition de contrat VIR → PGDR non validée) ne fait du marché une
condition d'ouverture. Selon les règles existantes l'incertitude **ne bloque pas** l'ouverture
(identité, véhicule et période de la notice, `applicability_established`). Aucune règle ajoutée
ni assouplie ; décision du propriétaire. Documenté : README PGDR, guide §10.

### 2.4 Défauts trouvés pendant la réception et la livraison (test, puis correction)

| Défaut | Constat | Correction | Test |
|---|---|---|---|
| `reset-password` sans `PI_LOGIN_THROTTLE_SECRET` | trace Python après la saisie du mot de passe | refus avant la saisie, code 2, audit `refused_config`, rien modifié | `test_3b_cli_reset_sans_secret.py` |
| Arrêt retenu par une connexion TLS inactive | 30,0 s (> `TimeoutStopSec=20` de l'unité) | `--timeout-graceful-shutdown 10` sur les trois services | `test_3b_arret_borne.py` (10 s) |
| Journaux effacés au redémarrage | `lancer_montage.sh` écrivait avec `>` : audit et trace d'une panne perdus | écriture en ajout | `test_3b_arret_borne.py` |
| Identification purgée par VIR | détails et confirmations : 502 « panne VIR » | 410 `VIR_RESULT_NOT_KEPT`, message frontend dédié, rien écrit | `test_3b_vir_echu.py`, unitaire `ErrorBanner` |

Chaque test a été exécuté en échec avant sa correction, puis en réussite. Les nouveaux tests 3B
ont aussi été exécutés contre l'état 3A (`a325c23`/`48d5da4`) : 10 échecs sur 13 (les 3 autres
vérifient des refus déjà assurés par 3A ; le test « après redémarrage » échoue parce qu'il
enchaîne sur le premier).

### 2.5 Dépôt de roues hors ligne (essai)

Faute de réseau, les 39 paquets du verrou ont été reconstitués en roues depuis des installations
locales aux versions exactes (contenu pris dans leur `RECORD`), plus setuptools, wheel, hatchling
et ses dépendances (dont tomlkit, manquant au premier essai : échec de construction de PGDR,
corrigé en ajoutant la roue). Rien de ce dépôt n'est livré.

## 3. Réception commune [exécuté]

Cluster PostgreSQL 16 dédié (port 55531, bases temporaires `pi01_test`, `pi_e2e`, `pi_install`,
`pi_restore`), garde réseau (toute connexion hors boucle locale refusée), notice FICTIVE, comptes
fictifs, faux transport de tri en essai signalé seulement, VIR simulé ou vrais adaptateurs
RegCheck/Vincario sur faux transports (résultats marqués simulés).

| Suite | Résultat |
|---|---|
| PI pytest (`281d243`), contre un montage vivant | **371 passed, 0 skipped, 0 failed** (353 en 3A + 18) |
| PGDR pytest (`1c5a5cc`) | **1019 passed, 0 skipped** (1017 en 3A + 2) |
| Frontend : `tsc -b --noEmit` / vitest / `vite build` | OK / **51 passed** / OK (59 modules) |
| Playwright A→M, O1–O4 (Vite, faux tri en essai signalé) | **18 passed** |
| Playwright P (tri absent) ; P (faux tri en panne) | **1 passed ; 1 passed** |
| Playwright N (VIR mode réel, vrais adaptateurs, faux transports) | **2 passed** ; consultations : exactement `vincario` (VIN) puis `regcheck` (plaque), 0 au refus de consentement, aux confirmations, correction, retrait, rafraîchissement, rechargement |
| Réception navigateur sur le lancement de production (HTTPS, frontend construit) | **3 passed** (`test_3b_reception_navigateur.py`) |
| Journaux des montages d'essai (1 055 lignes) | 0 VIN, plaque, mot de passe, identifiant, cookie, jeton, secret fictif, identifiant de parcours, `photo_base64`, trace |

Premier passage A→M et O : 18 réussis. Un second passage immédiat a échoué sur M seul (le mot de
passe du compte C avait été changé au premier) ; remis par `reset-password`, puis 18 réussis.
Ce second passage a révélé le défaut de `reset-password` sans secret (§2.4). Les specs N et P,
prises une fois par erreur dans un filtre du montage « faux tri », ont échoué faute de leurs
variables, comme prévu ; elles ont été lancées ensuite sur leurs montages.

Parcours manuel couvert : connexion ; pays explicite, plaque et VIN ; consentement ; résultat VIR
(inconnus, provenance, contradictions) ; confirmation, correction, retrait ; photo → propositions
(faux) → sélection ; non reconnues → catalogue ; tri absent, en panne, invalide → repli ; aucune
image → issue de sécurité ; identité ou notice insuffisante → refus ; confirmation → notice →
Premier Constat ; historique → redémarrage → résultat ; sauvegarde → restauration → résultat et
droits ; mots de passe ; clarification inconnue refusée avant VIR ; refus croisés ; journaux.

## 4. Livraison : installation et exploitation vérifiées [exécuté]

```bash
PIP_NO_INDEX=1 PIP_FIND_LINKS=<roues> npm_config_offline=true npm_config_cache=<cache> \
PREFIX=<neuf> VIR_SRC=~/vehicle-identity-resolver PGDR_SRC=~/pgdr CPL_SRC=~/cpl \
GGM_WHEEL=<ggm-1.0.0-py3-none-any.whl> deploy/installer.sh
```

Installation : code 0 ; `pip check` sans erreur ; fastapi 0.143.0, starlette 1.7.0, pydantic
2.14.0 (verrou) ; clones `vir a4c0172`, `pgdr 1c5a5cc`, `cpl bc09253`, `pi 281d243` sans
modification ; les courriers non commités de VIR absents du clone ; aucun chemin de travail
ni de scratchpad dans le code installé ; modules chargés depuis le PREFIX. Puis 19 contrôles,
tous réussis, sur l'installation (script d'essai, données fictives) :

1. migrations : base neuve → 029 + `pi_auth` ; 2. retour arrière 028 puis 029 ;
3. création de comptes (mot de passe court refusé) ; 4. `/health` en HTTPS, HTTP en clair
refusé ; 5. frontend construit, CSP, HSTS, X-Frame-Options, nosniff, Referrer-Policy, `/api/me`
401 ; 6. VIR et PGDR sur 127.0.0.1 seulement, routes internes non exposées ; 7. page des voyants
sous `/api/v1`, jeton CSRF, CSP à empreinte ; 8. 4 images de notice au seul propriétaire,
contenu égal à l'empreinte ; 9. POST relayés : Origine et CSRF exigés, « Résultat enregistré » ;
10. résultat lu par le propriétaire, 404 pour autrui ; 11. changement et réinitialisation de mot
de passe ; 12. arrêt (10,1 s avec une connexion TLS inactive ; 30,2 s avant correction) ;
13. sauvegarde ; 14. restauration dans une base neuve : résultat, provenance, dossier identiques,
droits conservés, médias restaurés ; 15. nouveau parcours après restauration ; 16. purge refusée
sans `VIR_RETENTION_DAYS` ; 17. purge (valeur d'essai 30, pas une décision) : 1 session expirée et
1 enregistrement VIR échu supprimés, CPL, médias et sauvegarde inchangés (empreintes) ; 18. après
purge VIR, dossier et résultat confirmé intacts ; 19. journaux (161 lignes) sans donnée sensible.

## 5. Conservation [documentation]

Bilan complet : guide §9 (VIR, CPL/PI, médias, sessions, journaux, sauvegardes : où, durée
configurée, mécanisme, décision restante) ; plaque et VIN dans CPL : guide §9.1 (artefacts
`vir_resolution`, `asset_identity_resolutions.canonical_identity_payload`,
`automotive.vehicle_details`), conservés sans limite, hors purge, dans chaque sauvegarde —
décision du propriétaire. Aucune durée décidée ; 30 jours (défaut VIR) non approuvés.

## 6. Ce qui reste

- Décisions du propriétaire : durées de conservation (toutes catégories) et sort de la plaque et
  du VIN dans CPL ; critère de marché ; textes nouveaux ; risque résiduel des essais de connexion.
- Externe : serveur, domaine, certificat, PostgreSQL de production, secrets, sauvegardes ;
  droits d'usage RegCheck/Vincario (non acquis) ; décisions de fusion et migration réelle.
- Non démontré : qualité réelle du tri (faux transport seul) ; fournisseurs VIR réels.
- Non activé ni autorisé : composant réel de tri ; fournisseurs réels.
