# Clôture PI V1 — installation propre et réception finale locale

Date : 2026-10-20. Branche PI `pi-cloture-v1` (worktree dédié), depuis `pi-conservation-integration` @ `b1ad3b7`.
Aucune modification de `main`, aucune fusion, aucun push, aucun déploiement, aucune base réelle, aucun appel
extérieur (installation sans réseau, proxy mort pendant l'installation et les essais), aucun fournisseur réel.
Ce document est un descendant purement documentaire : il n'est pas dans la composition installée.

## 1. Composition

| Composant | Commit installé | Remarque |
|---|---|---|
| PI | `7620f3b31e700387760b42ebb16b2f23d1e60949` | `b1ad3b7` + correction de l'arrêt du montage (`5f5eabf`, §4) + composition PGDR (`7620f3b`) |
| CPL | `ced7e4b712e144f9fbff07fee17a6ae362ccc091` | migrations 030 et 031 ; non modifié |
| PGDR | `c94d54fd449f9c941390bbf1bf19cb576e08780f` | tête documentaire de `55f76ae` (seul `docs/CLOTURE_PGDR_V1.md` diffère) ; `757b4fb` dans l'historique ; non modifié |
| VIR | `a4c0172f02e5535d542ecc6f4d16e0c13f9c6b60` | code ; documentation de clôture `ac82781` (seul `docs/CLOTURE_VIR_V1.md` ajouté) ; non modifié |
| GGM | 1.0.0, SHA-256 `41459158…99a7` | roue de `deploy/COMPOSITION.env` |

`deploy/COMPOSITION.env` citait PGDR `55f76ae` ; l'installateur refuse toute autre révision, donc installer
`c94d54f` exige de le citer : fait dans `7620f3b`. Les paquets `pgdr` installés depuis `55f76ae` (première
installation, PI `b1ad3b7`) et depuis `c94d54f` (seconde, PI `7620f3b`) sont identiques fichier pour fichier.

## 2. Installation propre

Clones locaux neufs (PI : clone de travail détaché au commit ; VIR, PGDR, CPL : clones nus), PREFIX neuf
hors des arbres de travail, `deploy/installer.sh` livré, sans modification :

```bash
PIP_NO_INDEX=1 PIP_FIND_LINKS=<roues du verrou> npm_config_offline=true npm_config_cache=<cache npm> \
HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 \
PREFIX=<neuf> VIR_SRC=<clone nu VIR> PGDR_SRC=<clone nu PGDR> CPL_SRC=<clone nu CPL> \
GGM_WHEEL=<ggm-1.0.0-py3-none-any.whl> <clone PI>/deploy/installer.sh
```

Le dépôt de roues (39 paquets du verrou et outils de construction) et le cache npm sont des copies locales
d'essai, non livrées.

| Vérification | Résultat (deux installations : PI `b1ad3b7` puis `7620f3b`) |
|---|---|
| Installateur | code 0 |
| Versions | 39/39 exactement celles de `deploy/requirements.lock`, aucun paquet hors verrou ; fastapi 0.143.0, starlette 1.7.0, pydantic 2.14.0, SQLAlchemy 2.1.5 |
| `pip check` | « No broken requirements found » |
| Clones dans `$PREFIX/src` | révisions exactes, aucun changement local ; fichiers non commités des dépôts d'origine absents |
| Modules chargés | `app`, `pgdr`, `vir`, `product_integration`, `ggm` depuis `$PREFIX/venv` ; aucun `.pth` ni lien éditable |
| Dépendance aux arbres d'origine | aucun lien symbolique ni chemin vers les worktrees, leurs sources ou `node_modules` dans le venv et `frontend-dist` (`node_modules` seulement dans `$PREFIX/build`, construction interne) |
| Frontend | construit pour la production (`$PREFIX/frontend-dist`), identique entre les deux installations |
| `COMPOSITION.installee` | égal aux commits réellement installés et à l'empreinte GGM |
| Migrations (`deploy/migrer.sh upgrade` du PREFIX, base PostgreSQL neuve) | CPL `031 (head)`, `pi_auth` v4, `cpl.case_deletions` et `cpl.runner_artifact_redactions` présentes, aucun déclencheur |

## 3. Réception finale locale [exécuté]

Montage lancé depuis le PREFIX (`scripts/lancer_montage.sh`, mode production HTTPS, certificat d'essai,
frontend construit), PostgreSQL 16 temporaire dédié, base VIR temporaire chiffrée (0600 ; aucun VIN en clair
dans le fichier), secrets d'essai générés pour ce montage, VIR simulé, notice PGDR **FICTIVE**, aucun tri.
Navigateur réel (Chromium) comme client.

1. Comptes créés par la CLI installée ; mot de passe court refusé.
2. `/health` en HTTPS ; HTTP en clair refusé ; CSP, HSTS, `X-Frame-Options`, `nosniff` ; `/api/me` 401 sans
   session ; VIR et PGDR sur 127.0.0.1 seulement.
3. A : identification du véhicule (VIR simulé), notice fictive ouverte, sélection, confirmation,
   « Résultat enregistré », résultat dans le dossier. B : refusé sur le dossier de A.
4. Arrêt demandé : services arrêtés en 1 à 2 s, ports libérés, **code 0** (après correction, §4).
5. Redémarrage : résultat de A identique, identification affichée ; B toujours refusé, son dossier lisible.
6. Purge : simulation (8 catégories « aucune politique ») ; exécution refusée sans politique (code 2).
7. Sauvegarde (`deploy/sauvegarder.sh` : 0700/0400, manifeste) ; arrêt ; restauration dans une base neuve
   (`deploy/restaurer.sh` → `finir_restauration.sh` avec des durées d'essai de 30 jours, non approuvées) :
   migrations, sessions révoquées (4), conservation appliquée, verrou retiré, service non relancé ; copie VIR
   mise de côté (0600) avec son manifeste PI, médias mis de côté (0700).
8. Montage sur la base restaurée : ancienne session refusée (reconnexion), résultat de A identique, B refusé.
9. Journaux (230 lignes) et sorties : 0 VIN, 0 secret d'essai, 0 identifiant ni mot de passe de compte,
   0 `photo_base64`, 0 trace Python.

Suites : PI complète sur `7620f3b` (montage d'essai de développement) **420 passed, 0 failed, 0 skipped**
(415 + 2 contrôle navigateur des dossiers + 3 arrêt). CPL, PGDR, VIR : non modifiés, non relancés dans cette
passe (CPL 242 passed à `ced7e4b`).

## 4. Défaut trouvé et corrigé

| Défaut | Avant | Après | Test |
|---|---|---|---|
| Arrêt demandé du montage compté comme un échec | sur SIGTERM, `lancer_montage.sh` arrêtait les services mais ne sortait pas : code 143 (groupe de processus, comme `systemctl stop` avec `KillMode=control-group`) ou 1 avec « Un service du montage s'est arrêté » (signal au seul lanceur) ; systemd aurait marqué chaque arrêt normal en échec | INT/TERM : services arrêtés, sortie 0 ; un service tombé de lui-même termine toujours le montage en 1 (`Restart=on-failure`) | `tests/test_cloture_arret_normal.py` : 2 cas en échec avant, 3 réussis après ; `test_3b_arret_borne.py` et `test_3a_lancement_reel.py` réussis |

Commit `5f5eabf` ; installé et vérifié dans la seconde installation (trois arrêts, code 0 chaque fois).

## 5. Écarts à la consigne, et ce qui reste

- La composition réceptionnée devait rester `b1ad3b7`. Elle a été réceptionnée telle quelle (première
  installation, réception complète réussie, sauf l'arrêt en échec), puis la correction du §4 et la citation de
  PGDR `c94d54f` ont donné `7620f3b`, réceptionné à son tour. **À décider par le propriétaire : composition
  retenue `7620f3b` (recommandé) ou `b1ad3b7`.**
- La consigne reçue était tronquée au point 2 (« Les téléchargements de… ») : installation faite sans réseau.
- Non vérifiable ici : serveur, domaine et certificat réels, PostgreSQL et secrets de production ; durées de
  conservation ; première exécution réelle (migrations 030/031, expurgation, suppression) — étape de
  déploiement distincte ; fournisseurs VIR réels, analyse photo et tri réels (non autorisés).
