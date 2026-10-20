# Livraison coordonnée V1 — préparation du déploiement

Date : 2026-10-20. Document de préparation : **rien n'est publié, migré ni mis en production par ce document**.
La publication Git, l'installation serveur, les migrations réelles et la mise en production attendent les
décisions du §6. Descendant purement documentaire de la composition réceptionnée (il n'en fait pas partie).

## 1. Composition réceptionnée

| Dépôt | Commit installé (composition) | Documentation de clôture | Branche de livraison locale | Contient la composition |
|---|---|---|---|---|
| PI `cpl-product-integration` | `7620f3b31e700387760b42ebb16b2f23d1e60949` | `801f2fb0bafc19e79f193ead63e59bc2d7e89518` (`docs/CLOTURE_PI_V1.md`) et ce document | `pi-cloture-v1` | oui : `b1ad3b7` et ses ancêtres (conservation 1/3 à 3/3, 3A, 3B, parcours, provenance), puis `5f5eabf`, `7620f3b`, `801f2fb` |
| CPL `cpl` | `ced7e4b712e144f9fbff07fee17a6ae362ccc091` | (amendements dans `docs/build/`) | `cpl-conservation-plaque` | oui : `bc09253` (029), `253ff8f` (030), `ced7e4b` (031) |
| PGDR `pgdr` | `c94d54fd449f9c941390bbf1bf19cb576e08780f` | même commit (`docs/CLOTURE_PGDR_V1.md`) | `v1-cloture` | oui : `757b4fb`, `55f76ae`, `c94d54f` |
| VIR `vehicle-identity-resolver` | `a4c0172f02e5535d542ecc6f4d16e0c13f9c6b60` | `ac82781e660fb7e1259bb577c4e5557b38afe5c0` (`docs/CLOTURE_VIR_V1.md`) | `vir-v1-cloture` (`vir-v1-finalisation` s'arrête à `a4c0172`) | oui |

`deploy/COMPOSITION.env` (à `7620f3b`) cite exactement VIR `a4c0172`, PGDR `c94d54f`, CPL `ced7e4b`, GGM
`41459158…99a7`. VIR : publier `vir-v1-cloture` porte `ac82781` (document de clôture) et contient `a4c0172` ;
l'installateur continue d'installer `a4c0172`, la composition n'est pas modifiée.

## 2. Publication Git (préparée, non faite)

Distants (`origin`, HTTPS GitHub, compte `paxtonef`) : lus par `git fetch` dans des clones nus dédiés le
2026-10-20. **Les quatre dépôts sont lisibles sans identifiants : publier rend ces commits publics.**

| Dépôt | Distant | Commits de la composition déjà publiés | À publier (branche de livraison) | Relation à `main` distant |
|---|---|---|---|---|
| PI | `github.com/paxtonef/cpl-product-integration` (`main` `fae3cba`) | aucun | 26 commits (25 jusqu'à `801f2fb`, plus ce document) | avance rapide depuis `main` |
| CPL | `github.com/paxtonef/cpl` (`main` `3ccdf63`) | aucun | 3 commits | avance rapide |
| PGDR | `github.com/paxtonef/pgdr` (`main` `1eff89d` ; `v1-premier-constat` `7b863c0`) | aucun | 8 commits | avance rapide |
| VIR | `github.com/paxtonef/vehicle-identity-resolver` (`main` `a342aba`) | aucun | 47 commits | avance rapide |

Aucune fusion n'est nécessaire au déploiement (l'installateur fixe chaque composant à son commit ; un clone
du distant contient toutes les branches publiées). Si le propriétaire veut aussi avancer `main`, ce serait
une avance rapide sans conflit (vérifié par `merge-base`), sans réécriture d'historique.

**Contenu publié, vérifié** (arbres des branches et tous les ajouts des commits à publier) : aucune base
(`.db`, dump), aucune clé ni certificat, aucun `.env` (seulement `deploy/secrets.env.exemple`, noms vides, et
les `.env.example` de CPL et VIR déjà publiés, valeurs fictives), aucun PDF, aucune image, aucune notice
constructeur (la notice revue reste hors dépôt, `PGDR_V1_MANIFEST`) ; fichiers relatifs à Peugeot déjà
publiés sur `main` ; aucune chaîne de forme VIN ou plaque autre que fictive (`VF3ZZZZZZZZZZZZZZ`,
`AB-123-CD`) ; aucun motif de jeton ou de mot de passe. Non publiés : les modifications non commitées des
arbres de travail (dont les courriers VIR en cours et les changements locaux de `~/cpl`).

Commandes exactes (épinglées par empreinte ; à lancer seulement après la décision D1, depuis les dépôts
d'origine, qui portent ces branches) :

```bash
git -C ~/cpl push origin ced7e4b712e144f9fbff07fee17a6ae362ccc091:refs/heads/cpl-conservation-plaque
git -C ~/pgdr push origin c94d54fd449f9c941390bbf1bf19cb576e08780f:refs/heads/v1-cloture
git -C ~/vehicle-identity-resolver push origin ac82781e660fb7e1259bb577c4e5557b38afe5c0:refs/heads/vir-v1-cloture
git -C ~/pi01-main push origin <tête de pi-cloture-v1, rapportée avec ce document>:refs/heads/pi-cloture-v1
# vérification après publication :
for r in cpl pgdr vehicle-identity-resolver cpl-product-integration; do git ls-remote https://github.com/paxtonef/$r.git; done
```

Étiquettes facultatives (décision D2), annotées, sur les commits de la composition :
`v1-composition` → PI `7620f3b`, CPL `ced7e4b`, PGDR `c94d54f`, VIR `a4c0172`
(`git -C <dépôt> tag -a v1-composition <commit> -m "Composition V1 réceptionnée" && git -C <dépôt> push origin v1-composition`).

## 3. Conservation : décisions à présenter

| Réglage | Point de départ | Durée configurée | À l'expiration | Décision attendue |
|---|---|---|---|---|
| `PI_CONSERVATION_IDENTIFIANTS_JOURS` (plaque et VIN dans CPL, artefacts `vir_resolution` compris) | `enregistrement_cpl` : création de l'enregistrement d'identification (seul implémenté ; autres possibles : dernière confirmation, dernière consultation) | **absente** | copies vidées (résolutions, fiche véhicule) ; artefacts expurgés par REQ-B6-091 ; l'identification répond « no longer kept » | durée, ou `illimitee` ; point de départ |
| `PI_CONSERVATION_DOSSIERS_JOURS` (dossiers et données propres, résultats confirmés et Premiers Constats compris) | `creation_dossier` | **absente** | dossier supprimé avec ses données propres par REQ-B5-116, **irréversible** ; 404 ensuite | durée, ou `illimitee` |
| `PI_CONSERVATION_MEDIAS_JOURS` (médias envoyés ; liés à aucun dossier) | `envoi` | **absente** | fichiers supprimés, référence « no longer kept » | durée, ou `illimitee` |
| `PI_CONSERVATION_JOURNAUX_JOURS` (journaux tournés de `MONTAGE_DIR`) | dernière modification du fichier | **absente** | fichiers tournés supprimés (rotation elle-même : exploitant) | durée, ou `illimitee` ; rotation |
| `PI_CONSERVATION_SAUVEGARDES_JOURS` (sauvegardes, médias et copie VIR mis de côté par une restauration) | date du manifeste | **absente** | dossiers ou copies reconnus supprimés ; non reconnus jamais | durée, ou `illimitee` |
| `VIR_RETENTION_DAYS` (stockage VIR chiffré) | création de l'enregistrement VIR | **absente** dans la configuration ; **le code VIR applique 30 jours par défaut, non approuvés** | purge VIR à chaque écriture et `vir purge` | accepter ou remplacer les 30 jours |

Sans politique, la simulation de la purge fonctionne et son exécution est refusée avant toute écriture ;
la réouverture après restauration reste bloquée (verrou). Sessions web : durées de session existantes
(`PI_SESSION_IDLE_MINUTES` 30, `PI_SESSION_MAX_HOURS` 12 par défaut), hors de ces décisions.

**Amendements CPL à approuver (non approuvés à ce jour)** — exceptions étroites et nommées, ajoutées à CPL
existant (migrations 030 et 031, schéma seul), pas une reconstruction :

- **REQ-B6-091** (`docs/build/B6_AMENDMENT_REQ_B6_091_…`) : retrait de la plaque et du VIN des artefacts
  `vir_resolution` (nouvelles écritures sans identifiants ; anciens expurgés par une opération gouvernée,
  toutes versions liées) ; empreinte d'origine gardée comme trace, empreinte recalculée, trace sans valeur ;
  artefact altéré refusé. **Irréversible** pour les valeurs retirées (seules les sauvegardes antérieures les
  gardent jusqu'à leur échéance) ; descente de 030 refusée après une expurgation.
- **REQ-B5-116** (`docs/build/B5_AMENDMENT_REQ_B5_116_…`) : suppression d'un dossier échu et de ses seules
  données propres (exécutions, artefacts, résolutions, décisions, événements) ; compte, véhicule, autres
  dossiers, connaissances conservés ; dossier dont dépend une donnée extérieure reporté ; trace technique sans
  contenu. **Irréversible** ; descente de 031 refusée après une suppression.

Aucun effacement physique n'est garanti (WAL, `VACUUM`, sauvegardes de l'hébergeur : guide §9.6).

## 4. Installation serveur

Même installateur, même verrou, même guide (§3 à §8 de `docs/GUIDE_MISE_EN_LIGNE.md`). Prérequis : Python
3.14, Node.js et npm, git, rsync, PostgreSQL 16 (client `pg_dump`/`pg_restore`), roue
`ggm-1.0.0-py3-none-any.whl` (SHA-256 `414591587d29adf756f16e39ad03cffe0fa2328c8a41e5bbf3ba6b0aa42799a7`).

**A. Avec accès aux dépôts de paquets (PyPI, npm) pendant l'installation**

```bash
git clone https://github.com/paxtonef/cpl-product-integration.git /srv/sources/pi
git -C /srv/sources/pi checkout --detach 7620f3b31e700387760b42ebb16b2f23d1e60949
PREFIX=/opt/cpl-produit \
VIR_SRC=https://github.com/paxtonef/vehicle-identity-resolver.git \
PGDR_SRC=https://github.com/paxtonef/pgdr.git CPL_SRC=https://github.com/paxtonef/cpl.git \
GGM_WHEEL=/srv/sources/ggm-1.0.0-py3-none-any.whl /srv/sources/pi/deploy/installer.sh
/opt/cpl-produit/venv/bin/pip check && cat /opt/cpl-produit/COMPOSITION.installee
```

Exige la publication (§2) ; sinon, remplacer les URL par des clones transférés (mêmes commits).

**B. Sans réseau pendant l'installation** (dépôt de roues et cache npm préparés ailleurs, **pour la plateforme
du serveur** : système, architecture et Python 3.14 identiques — les roues compilées et les binaires npm
optionnels de Vite/esbuild/rollup en dépendent)

```bash
# sur une machine de même plateforme, avec réseau :
pip download --only-binary=:all: --no-deps -d roues -r deploy/requirements.lock
pip download --only-binary=:all: --no-deps -d roues setuptools wheel hatchling packaging pathspec pluggy \
    trove-classifiers tomlkit
(cd frontend && npm ci --cache "$PWD/../cache-npm" --no-audit --no-fund)
# transfert : roues/, cache-npm/, la roue GGM et des clones (nus) des quatre dépôts aux commits retenus
# sur le serveur :
PIP_NO_INDEX=1 PIP_FIND_LINKS=/srv/roues npm_config_offline=true npm_config_cache=/srv/cache-npm \
PREFIX=/opt/cpl-produit VIR_SRC=/srv/sources/vir.git PGDR_SRC=/srv/sources/pgdr.git \
CPL_SRC=/srv/sources/cpl.git GGM_WHEEL=/srv/sources/ggm-1.0.0-py3-none-any.whl \
/srv/sources/pi/deploy/installer.sh
```

Vérification déjà faite (clôture PI V1, `docs/CLOTURE_PI_V1.md`) : B exécuté deux fois sur macOS arm64
(Python 3.14.2), code 0, 39/39 versions, `pip check`, migrations 031, réception navigateur. Non vérifié :
A (aucun téléchargement de paquets dans ce bloc) et B sur la plateforme du serveur (inconnue).

Après l'installation, dans l'ordre (guide) : secrets (§4, fichier 0640 hors dépôt), notice revue
`PGDR_V1_MANIFEST` hors dépôt, `PGDR_V1_TRI` absent ; **sauvegarde** puis `deploy/migrer.sh upgrade`
(CPL jusqu'à 031, `pi_auth` v4 ; sur une base existante, base VIR selon `docs/LIVRAISON_VIR_V1.md` §6) ;
comptes (§5) ; unité systemd (§6) ; `conservation.cli controle` ; `deploy/purger.sh` en simulation ;
la première exécution réelle de la purge est une étape distincte, après les décisions du §3.

## 5. Ce qui n'a pas pu être vérifié

- Droits d'écriture sur les distants (aucun `push`, même à blanc).
- Installation A (accès PyPI/npm) et installation sur la plateforme du serveur.
- Serveur, domaine, certificat, PostgreSQL et secrets de production.

## 6. Décisions manquantes du propriétaire

- **D1** Publication : rendre publics les commits listés (dépôts lisibles sans identifiants) ; branches
  `pi-cloture-v1`, `cpl-conservation-plaque`, `v1-cloture`, `vir-v1-cloture`.
- **D2** Étiquettes `v1-composition` (facultatives) ; avancer `main` ou non (avance rapide possible).
- **D3** Durées de conservation des six réglages du §3, point de départ des identifiants, acceptation ou
  remplacement des 30 jours de VIR.
- **D4** Approbation des amendements REQ-B6-091 et REQ-B5-116.
- **D5** Mode d'installation A ou B ; plateforme, serveur, domaine, certificat, PostgreSQL de production,
  gestion des secrets, emplacement des sauvegardes.
- **D6** Fenêtre de migration réelle (030/031) précédée d'une sauvegarde, et date de la première purge réelle.
- Restent ouvertes (guide §11) : fournisseurs VIR réels (non acquis : VIR reste simulé), analyse photo et tri
  (non autorisés), risque résiduel des essais de connexion, critère de marché, validation des textes nouveaux.
