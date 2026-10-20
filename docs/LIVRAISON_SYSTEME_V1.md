# Livraison du système V1 — procès-verbal de livraison

**Statut : préparation.** Rien n'est publié, installé sur un serveur, migré, purgé ni mis en production par
ce document. Date : 2026-10-20. Descendant purement documentaire de la composition réceptionnée (il n'en fait
pas partie). Aucune des décisions D1 à D6 (§9) n'est prise.

Sommaire : 1 composition · 2 preuves acquises · 3 publication · 4 installation · 5 configuration et secrets ·
6 base neuve ou reprise · 7 conservation et amendements · 8 réception sur serveur et retour arrière ·
9 feuille des décisions · 10 limites de vérification.

## 1. Composition exacte et références de clôture

| Dépôt | Commit installé (composition) | Clôture | Branche de livraison locale | Contient la composition |
|---|---|---|---|---|
| PI `cpl-product-integration` | `7620f3b31e700387760b42ebb16b2f23d1e60949` | `801f2fb0bafc19e79f193ead63e59bc2d7e89518` (`docs/CLOTURE_PI_V1.md`) et ce document | `pi-cloture-v1` | oui : `b1ad3b7` et ses ancêtres (conservation 1/3 à 3/3, 3A, 3B, parcours, provenance), puis `5f5eabf`, `7620f3b`, `801f2fb` |
| CPL `cpl` | `ced7e4b712e144f9fbff07fee17a6ae362ccc091` | amendements `docs/build/B6_AMENDMENT_REQ_B6_091_…`, `docs/build/B5_AMENDMENT_REQ_B5_116_…` | `cpl-conservation-plaque` | oui : `bc09253` (029), `253ff8f` (030), `ced7e4b` (031) |
| PGDR `pgdr` | `c94d54fd449f9c941390bbf1bf19cb576e08780f` | même commit (`docs/CLOTURE_PGDR_V1.md`) | `v1-cloture` | oui : `757b4fb`, `55f76ae`, `c94d54f` |
| VIR `vehicle-identity-resolver` | `a4c0172f02e5535d542ecc6f4d16e0c13f9c6b60` | `ac82781e660fb7e1259bb577c4e5557b38afe5c0` (`docs/CLOTURE_VIR_V1.md`) | `vir-v1-cloture` (`vir-v1-finalisation` s'arrête à `a4c0172`) | oui |
| GGM | 1.0.0, SHA-256 `414591587d29adf756f16e39ad03cffe0fa2328c8a41e5bbf3ba6b0aa42799a7` | — | — | roue fournie hors PyPI |

`deploy/COMPOSITION.env` (à `7620f3b`) cite exactement VIR `a4c0172`, PGDR `c94d54f`, CPL `ced7e4b` et
l'empreinte GGM ; l'installateur refuse toute autre révision. VIR : publier `vir-v1-cloture` porte `ac82781`
(document de clôture) et contient `a4c0172`, qui reste la révision installée.

## 2. Preuves déjà acquises (citées, non relancées)

| Preuve | Où | Résultat |
|---|---|---|
| Installation propre par `deploy/installer.sh`, sans réseau, clones neufs, PREFIX neuf (deux fois : PI `b1ad3b7`, puis `7620f3b`) | `docs/CLOTURE_PI_V1.md` §2 | code 0 ; 39/39 versions du verrou ; `pip check` ; aucun lien vers les arbres d'origine ; `COMPOSITION.installee` conforme ; migrations CPL 031 et `pi_auth` v4 |
| Réception locale sur le montage installé (HTTPS, frontend construit, navigateur réel) | `docs/CLOTURE_PI_V1.md` §3 | comptes, isolement, parcours VIR → notice → résultat enregistré, redémarrage, sauvegarde, restauration, journaux sans secret |
| Arrêt demandé du montage = code 0 (défaut corrigé) | `docs/CLOTURE_PI_V1.md` §4 | 3 arrêts en code 0 sur l'installation corrigée |
| Suite PI à `7620f3b` | `docs/CLOTURE_PI_V1.md` §3 | 420 passed, 0 failed, 0 skipped |
| Suite CPL à `ced7e4b` | compte rendu de conservation | 242 passed |
| Clôture PGDR (`c94d54f`) | `docs/CLOTURE_PGDR_V1.md` (PGDR) | PGDR 1056 passed ; navigateur 10 passed |
| Clôture VIR (`ac82781`) | `docs/CLOTURE_VIR_V1.md` (VIR) | VIR clos au commit `a4c0172` ; contrôle de conservation 20/20 |
| Conservation CPL/PI, contrôle navigateur des dossiers supprimés | `docs/build/PI_CONSERVATION_COMPTE_RENDU_v0.md`, `docs/RECEPTION.md` 3.15a–r | réussi sur données fictives |

## 3. Procédure de publication (préparée, non faite)

> **Les quatre dépôts distants sont lisibles sans identifiants : publier rend le code public.**
> Décision du propriétaire **D1** (§9), non prise. Aucun `push`, même à blanc, n'a été fait.

Distants (`origin`, HTTPS GitHub, compte `paxtonef`), lus par `git fetch` dans des clones nus dédiés le
2026-10-20 :

| Dépôt | Distant | Commits de la composition déjà publiés | À publier | Relation à `main` distant |
|---|---|---|---|---|
| PI | `github.com/paxtonef/cpl-product-integration` (`main` `fae3cba`) | aucun | branche `pi-cloture-v1` (25 commits jusqu'à `801f2fb`, plus les commits de ce document) | avance rapide |
| CPL | `github.com/paxtonef/cpl` (`main` `3ccdf63`) | aucun | 3 commits | avance rapide |
| PGDR | `github.com/paxtonef/pgdr` (`main` `1eff89d`) | aucun | 8 commits | avance rapide |
| VIR | `github.com/paxtonef/vehicle-identity-resolver` (`main` `a342aba`) | aucun | 47 commits | avance rapide |

Aucune fusion n'est nécessaire au déploiement : l'installateur fixe chaque composant à son commit, et un clone
du distant contient toutes les branches publiées. Avancer `main` (D2) serait une avance rapide sans conflit,
sans réécriture d'historique.

**Contenu publié, vérifié** (arbres des branches et ajouts de tous les commits à publier) : aucune base,
aucune clé ni certificat, aucun `.env` (seulement `deploy/secrets.env.exemple`, noms vides, et les
`.env.example` de CPL et VIR déjà publiés, valeurs fictives) ; aucun PDF, aucune image, aucune notice
constructeur (la notice revue reste hors dépôt) ; aucune chaîne de forme VIN ou plaque autre que fictive ;
aucun motif de jeton ou de mot de passe. Les modifications non commitées des arbres de travail ne sont pas
publiées.

Commandes (épinglées par empreinte, après D1, depuis les dépôts d'origine qui portent ces branches) :

```bash
git -C ~/cpl push origin ced7e4b712e144f9fbff07fee17a6ae362ccc091:refs/heads/cpl-conservation-plaque
git -C ~/pgdr push origin c94d54fd449f9c941390bbf1bf19cb576e08780f:refs/heads/v1-cloture
git -C ~/vehicle-identity-resolver push origin ac82781e660fb7e1259bb577c4e5557b38afe5c0:refs/heads/vir-v1-cloture
git -C ~/pi01-main push origin <tête de pi-cloture-v1 au moment de la publication>:refs/heads/pi-cloture-v1
for r in cpl pgdr vehicle-identity-resolver cpl-product-integration; do git ls-remote https://github.com/paxtonef/$r.git; done
```

Étiquettes facultatives (D2), annotées : `v1-composition` → PI `7620f3b`, CPL `ced7e4b`, PGDR `c94d54f`,
VIR `a4c0172`
(`git -C <dépôt> tag -a v1-composition <commit> -m "Composition V1 réceptionnée" && git -C <dépôt> push origin v1-composition`).

## 4. Procédure d'installation

Installateur, verrou et guide réceptionnés (`deploy/installer.sh`, `deploy/requirements.lock`,
`docs/GUIDE_MISE_EN_LIGNE.md` §3). Prérequis serveur : Python 3.14, Node.js et npm, git, rsync,
PostgreSQL 16 (client `pg_dump`/`pg_restore`), roue GGM (empreinte §1). Utilisateur système dédié
`cpl-produit` ; `PREFIX=/opt/cpl-produit` (modèle de l'unité systemd).

**A. Avec accès aux dépôts de paquets (PyPI, npm) pendant l'installation** — **non exercée**.

```bash
git clone https://github.com/paxtonef/cpl-product-integration.git /srv/sources/pi
git -C /srv/sources/pi checkout --detach 7620f3b31e700387760b42ebb16b2f23d1e60949
PREFIX=/opt/cpl-produit \
VIR_SRC=https://github.com/paxtonef/vehicle-identity-resolver.git \
PGDR_SRC=https://github.com/paxtonef/pgdr.git CPL_SRC=https://github.com/paxtonef/cpl.git \
GGM_WHEEL=/srv/sources/ggm-1.0.0-py3-none-any.whl /srv/sources/pi/deploy/installer.sh
/opt/cpl-produit/venv/bin/pip check && cat /opt/cpl-produit/COMPOSITION.installee
```

Exige la publication (D1) ; sinon, des clones transférés aux mêmes commits.

**B. Sans réseau pendant l'installation** — **exercée sur macOS arm64 seulement** (deux fois, §2). Dépôt de
roues et cache npm préparés **pour la plateforme du serveur** (système, architecture, Python 3.14 : les roues
compilées et les binaires npm optionnels de Vite/esbuild/rollup en dépendent) :

```bash
# sur une machine de même plateforme, avec réseau :
pip download --only-binary=:all: --no-deps -d roues -r deploy/requirements.lock
pip download --only-binary=:all: --no-deps -d roues setuptools wheel hatchling packaging pathspec pluggy \
    trove-classifiers tomlkit
(cd frontend && npm ci --cache "$PWD/../cache-npm" --no-audit --no-fund)
# transfert : roues/, cache-npm/, la roue GGM et des clones nus des quatre dépôts aux commits retenus
# sur le serveur :
PIP_NO_INDEX=1 PIP_FIND_LINKS=/srv/roues npm_config_offline=true npm_config_cache=/srv/cache-npm \
PREFIX=/opt/cpl-produit VIR_SRC=/srv/sources/vir.git PGDR_SRC=/srv/sources/pgdr.git \
CPL_SRC=/srv/sources/cpl.git GGM_WHEEL=/srv/sources/ggm-1.0.0-py3-none-any.whl \
/srv/sources/pi/deploy/installer.sh
```

**Compatibilité Linux serveur : non exécutée.** Aucun de ces chemins n'est éprouvé sur le serveur.

## 5. Configuration de production et secrets attendus (sans valeurs)

Paramètres existants seulement (guide §4, `deploy/secrets.env.exemple`, unité
`deploy/systemd/cpl-produit.service`, VIR `docs/LIVRAISON_VIR_V1.md`), aucun mécanisme parallèle.

**Règle des secrets.** Saisis ou installés localement sur le serveur, dans
`/etc/cpl-produit/montage.env` (`root:cpl-produit`, 0640, hors dépôt ; lu par l'unité via
`EnvironmentFile=`) ou un gestionnaire de secrets : **jamais** dans le chat, Git, un argument de commande
ou un journal. Génération sur le serveur, sans affichage, par exemple :
`umask 077; python3 -c 'import secrets;print("PI_LOGIN_THROTTLE_SECRET="+secrets.token_urlsafe(48))' >> /etc/cpl-produit/montage.env`
(puis `chown root:cpl-produit` et `chmod 0640`). Mots de passe des comptes : saisis sans écho
(`create-account`, `--password-stdin` depuis un fichier protégé seulement).

**Modèle** (`/etc/cpl-produit/montage.env`, valeurs à fournir sur le serveur) :

```ini
# Serveur et accès public
PI_PUBLIC_HOST=                 # adresse d'écoute publique (ex. 0.0.0.0)
PI_PUBLIC_PORT=                 # 443 (CAP_NET_BIND_SERVICE prévu par l'unité) ou un port derrière un proxy TLS
PI_PUBLIC_ORIGIN=               # https://<domaine>[:port] exact
PI_TRUSTED_PROXIES=             # seulement si un proxy TLS est devant PI ; sinon absent
# HTTPS
PI_TLS_CERT=                    # certificat du domaine (lisible du seul service)
PI_TLS_KEY=                     # clé TLS (0600)
# PI_COOKIE_SECURE reste absent (1) : 0 est refusé en production
# PostgreSQL (compte de service, accès local seulement)
DATABASE_URL=                   # postgresql+psycopg2://<rôle>@/<base>?host=/var/run/postgresql (ou mot de passe local)
# Données persistantes
MONTAGE_DIR=/var/lib/cpl-produit/montage
VIR_DATABASE_PATH=/var/lib/cpl-produit/vir/vir.db
PI05_MEDIA_STORAGE_DIR=/var/lib/cpl-produit/medias
SAUVEGARDES_DIR=                # hors du serveur de préférence, accès restreint
PI_FRONTEND_DIST=/opt/cpl-produit/frontend-dist
# Secrets (générés sur le serveur)
VIR_SERVICE_TOKEN=              # jeton de service PI -> VIR (PI le reprend comme PI_VIR_SERVICE_TOKEN)
VIR_DATA_ENCRYPTION_KEY=        # clé de chiffrement du stockage VIR : perte = données VIR illisibles ; à sauvegarder à part
PGDR_IDENTITY_HANDOFF_TOKEN=    # passage d'identité PI -> PGDR
PI_LOGIN_THROTTLE_SECRET=       # HMAC de la limitation des connexions (32 caractères au moins)
PI_LOGIN_THROTTLE_SECRET_PREVIOUS=   # seulement pendant un renouvellement
# Sessions (valeurs du code si absentes : 30 min d'inactivité, 12 h au plus)
PI_SESSION_IDLE_MINUTES=
PI_SESSION_MAX_HOURS=
# Notice revue (hors dépôt) ; PGDR_V1_TRI, PGDR_V1_ESSAI_TRI, PGDR_V1_DEV_TRIAL ABSENTS en production
PGDR_V1_MANIFEST=
PGDR_V1_APPLICABILITE=          # facultatif
PGDR_V1_RATTACHEMENT=           # facultatif
# Conservation : aucune valeur décidée (D3)
VIR_RETENTION_DAYS=             # ATTENTION : absent, le code VIR applique 30 jours, NON APPROUVÉS par le propriétaire
PI_CONSERVATION_IDENTIFIANTS_JOURS=
PI_CONSERVATION_DOSSIERS_JOURS=
PI_CONSERVATION_MEDIAS_JOURS=
PI_CONSERVATION_JOURNAUX_JOURS=
PI_CONSERVATION_SAUVEGARDES_JOURS=
# VIR : mode des fournisseurs
VIR_PROVIDER_MODE=simulated     # « real » seulement après les conditions ci-dessous
VIR_WEB_DEV_MODE=false
```

Points de configuration :

- **Serveur et accès opérateur** : compte système `cpl-produit` sans connexion interactive ; accès opérateur
  (SSH par clé) hors de ce dépôt ; commandes d'exploitation lancées sur le serveur, jamais par le web.
- **Domaine et DNS** : enregistrement A/AAAA du domaine vers le serveur ; `PI_PUBLIC_ORIGIN` égal à
  l'origine exacte.
- **HTTPS** : terminé par PI lui-même (`PI_TLS_CERT`, `PI_TLS_KEY`) ou par un proxy TLS déclaré dans
  `PI_TRUSTED_PROXIES` ; renouvellement du certificat à la charge de l'exploitant (redémarrage de l'unité).
- **PostgreSQL** : écoute locale seulement (`listen_addresses = 'localhost'`, `pg_hba.conf` limité au rôle) ;
  rôle propriétaire de la base, sans superutilisateur.
- **Session et CSRF** : aucun secret à fournir (jeton de session aléatoire stocké condensé, jeton CSRF par
  session) ; la limitation des connexions utilise `PI_LOGIN_THROTTLE_SECRET`.
- **VIR et ses fournisseurs réels — préparé, non activé.** Aucune activation, aucun appel RegCheck ou
  Vincario, `rgm.yaml` non modifié. Les essais réussis (vrais adaptateurs sur **faux transports**) ne sont pas
  une approbation des droits d'usage. Un fournisseur réel ne serait appelé que si toutes ces conditions sont
  réunies :
  1. droits d'usage et contrats acquis (aujourd'hui **non acquis**) et décision du propriétaire ;
  2. autorisation de gouvernance VIR : entrée correspondante dans `rgm.yaml` (paquet VIR), par un commit VIR
     revu, donc une **nouvelle composition** — rien de tel n'existe ;
  3. `VIR_PROVIDER_MODE=real` (les adaptateurs simulés sont alors refusés) ;
  4. RegCheck : `VIR_REGCHECK_ENABLED=true`, `VIR_REGCHECK_USERNAME` (secret), `VIR_REGCHECK_ENDPOINT`
     (HTTPS), `VIR_REGCHECK_TIMEOUT_MS` facultatif ; Vincario : `VIR_VINCARIO_ENABLED=true`,
     `VIR_VINCARIO_API_KEY` et `VIR_VINCARIO_SECRET_KEY` (secrets), `VIR_VINCARIO_TIMEOUT_MS` facultatif.
  Tant que ces conditions ne sont pas remplies : `VIR_PROVIDER_MODE=simulated`, variables `VIR_REGCHECK_*` et
  `VIR_VINCARIO_*` absentes ; les résultats affichés portent la marque « simulé ».
- **PGDR en production** : le point d'entrée de production ne sert pas l'ancien dialogue ; le frontend est
  construit sans `VITE_PI_DIALOGUE_HISTORIQUE` ; aucun faux tri ni notice fictive (seule la notice revue,
  `PGDR_V1_MANIFEST`) ; sans notice applicable, PGDR affiche l'écran fixe « Notice indisponible pour ce
  véhicule » et les consignes de sécurité. Les fichiers de notice ne sont jamais publiés.

## 6. Base neuve ou reprise d'une base existante

Aucune base réelle n'a été ouverte. Toujours dans cet ordre, services arrêtés.

**Base neuve**

1. Rôle et base PostgreSQL protégés : `createuser --no-superuser --no-createdb --no-createrole cpl_produit` ;
   `createdb --owner cpl_produit cpl_produit` ; accès local seulement.
2. Secrets et modèle du §5 installés ; `MONTAGE_DIR`, `PI05_MEDIA_STORAGE_DIR`, dossier de
   `VIR_DATABASE_PATH` créés en 0700, propriété `cpl-produit`.
3. `deploy/migrer.sh upgrade` → CPL `031 (head)`, schéma `pi_auth` v4 (contrôle :
   `alembic current`, `SELECT max(version) FROM pi_auth.schema_version`).
4. Base VIR chiffrée : créée en 0600 au premier démarrage de VIR avec `VIR_DATA_ENCRYPTION_KEY` ; contrôle
   `vir check-storage` (« Ready to start: yes »).
5. Comptes : `$PREFIX/venv/bin/python -m product_integration.auth.cli create-account --login <identifiant>`
   (mot de passe saisi sans écho).
6. `conservation.cli controle` ; `deploy/purger.sh` en simulation ; démarrage par l'unité systemd.

**Base existante**

1. Arrêt : `systemctl stop cpl-produit` (code 0 attendu) ; aucune réouverture avant la fin.
2. Sauvegarde : `deploy/sauvegarder.sh` (PostgreSQL, VIR, médias ; manifeste, 0700/0400) et
   `vir backup <fichier protégé>` ; vérification : `shasum -a 256 -c SHA256SUMS`, et restauration d'essai sur
   une cible isolée (§8) avant toute migration réelle.
3. Migrations CPL/PI : `deploy/migrer.sh upgrade` (030 puis 031, `pi_auth` v4).
4. VIR, selon `docs/LIVRAISON_VIR_V1.md` §6 : `vir migrate-owners`, puis `vir migrate-storage` si l'ancienne
   table en clair existe, puis `vir check-storage` (« Ready to start: yes »).
5. Conservation : `conservation.cli controle` et `deploy/purger.sh` **en simulation seulement**.
6. Expurgation des artefacts échus, suppression des dossiers échus et purge réelles : **seulement après**
   approbation des durées (D3), des amendements (D4) et autorisation d'exécution (D6).

**Points de non-retour**

- Une expurgation (REQ-B6-091) ou une suppression de dossier (REQ-B5-116) est définitive : seule une
  sauvegarde antérieure garde les données, jusqu'à son échéance. Les descentes de 030 et 031 sont alors
  refusées ; aucun downgrade ne recrée des données supprimées ou expurgées.
- `vir migrate-storage` supprime l'ancienne table en clair après chiffrement ; la perte de
  `VIR_DATA_ENCRYPTION_KEY` rend les données VIR illisibles.
- La descente de 029 est documentée par CPL comme non totalement réversible.

## 7. Conservation et amendements à approuver

| Réglage | Point de départ | Durée configurée | À l'expiration | Décision attendue |
|---|---|---|---|---|
| `PI_CONSERVATION_IDENTIFIANTS_JOURS` (plaque et VIN dans CPL, artefacts `vir_resolution` compris) | `enregistrement_cpl` (seul implémenté ; autres possibles : dernière confirmation, dernière consultation) | **absente** | copies vidées ; artefacts expurgés (REQ-B6-091) ; « no longer kept » | durée ou `illimitee` ; point de départ |
| `PI_CONSERVATION_DOSSIERS_JOURS` (dossiers et données propres, résultats confirmés et Premiers Constats compris) | `creation_dossier` | **absente** | dossier supprimé (REQ-B5-116), **irréversible** ; 404 | durée ou `illimitee` |
| `PI_CONSERVATION_MEDIAS_JOURS` (médias envoyés ; liés à aucun dossier) | `envoi` | **absente** | fichiers supprimés, « no longer kept » | durée ou `illimitee` |
| `PI_CONSERVATION_JOURNAUX_JOURS` (journaux tournés) | dernière modification du fichier | **absente** | fichiers tournés supprimés (rotation : exploitant) | durée ou `illimitee` ; rotation |
| `PI_CONSERVATION_SAUVEGARDES_JOURS` (sauvegardes, médias et copie VIR mis de côté par une restauration) | date du manifeste | **absente** | dossiers ou copies reconnus supprimés ; non reconnus jamais | durée ou `illimitee` |
| `VIR_RETENTION_DAYS` (stockage VIR chiffré) | création de l'enregistrement VIR | **absente** ; **sans réglage explicite, le serveur purgerait VIR à 30 jours (défaut du code), durée non approuvée** | purge VIR à chaque écriture et `vir purge` | accepter ou remplacer les 30 jours |

Sans politique, la simulation fonctionne et l'exécution est refusée avant toute écriture ; une réouverture
après restauration reste bloquée. Commandes à planifier après D3 (ex. timer systemd quotidien) :
`deploy/purger.sh --executer` et `deploy/nettoyer_sauvegardes.sh --executer`, précédées de leur simulation.

**Amendements CPL à approuver (non approuvés)** — exceptions étroites et nommées à CPL existant (migrations
030 et 031, schéma seul), pas une reconstruction :

- **REQ-B6-091** : retrait de la plaque et du VIN des artefacts `vir_resolution` (nouvelles écritures sans
  identifiants ; anciens expurgés par une opération gouvernée, toutes versions liées) ; empreinte d'origine
  gardée comme trace, trace sans valeur, artefact altéré refusé. Irréversible pour les valeurs retirées.
- **REQ-B5-116** : suppression d'un dossier échu et de ses seules données propres ; compte, véhicule, autres
  dossiers, connaissances conservés ; trace technique sans contenu. Irréversible.

Aucun effacement physique n'est garanti (WAL, `VACUUM`, sauvegardes de l'hébergeur : guide §9.6).

## 8. Réception sur serveur et retour arrière

**Checklist** (à cocher sur le serveur ; aucun appel fournisseur réel n'en est une condition ; les
vérifications sans fournisseur utilisent VIR en mode simulé, marqué « simulé », sur un compte d'essai,
jamais présenté comme réel aux utilisateurs) :

- [ ] `cat $PREFIX/COMPOSITION.installee` = commits du §1 ; `pip check` sans erreur.
- [ ] Frontend en HTTPS sur le domaine ; HTTP en clair refusé ; en-têtes CSP, HSTS, `X-Frame-Options`, `nosniff`.
- [ ] VIR, PGDR et PostgreSQL non exposés (écoute 127.0.0.1 ou socket local ; contrôle `ss -ltnp`).
- [ ] Connexion de deux comptes ; chacun refusé (404) sur les dossiers de l'autre.
- [ ] Parcours VIR : identification, confirmation, correction, retrait, provenance par champ affichée.
- [ ] Parcours PGDR sans dialogue : notice revue, sélection, confirmation, « Résultat enregistré » ; véhicule
      sans notice applicable : écran fixe et consignes de sécurité.
- [ ] Redémarrage (`systemctl restart`, arrêt en code 0) : comptes, dossiers et résultats conservés.
- [ ] Journaux (`MONTAGE_DIR/*.log`) : aucun secret, mot de passe, VIN, plaque ni jeton.
- [ ] Sauvegarde puis restauration sur une cible isolée (autre base, autre `MONTAGE_DIR`) : verrou, migrations,
      sessions révoquées, données lisibles ; la production n'est pas touchée.
- [ ] Politique de conservation configurée (après D3), simulations relues, commandes planifiées.

**Retour arrière**

- Version applicative précédente : arrêter, réinstaller la composition précédente dans un PREFIX neuf
  (`deploy/installer.sh` depuis l'ancien commit PI), relancer.
- Compatibilité du schéma : une version précédente n'est compatible qu'avec son propre schéma ; si la
  descente est refusée (030 après une expurgation, 031 après une suppression) ou si le schéma diffère, une
  **restauration de la sauvegarde prise avant la migration** est nécessaire (`deploy/restaurer.sh`, guide §8).
- Toute migration et tout retour arrière exigent une sauvegarde préalable vérifiée.
- Aucune récupération des données purgées, expurgées ou supprimées, sauf par une sauvegarde antérieure.

## 9. Feuille des décisions du propriétaire (aucune n'est prise)

| Décision | Options | Conséquences |
|---|---|---|
| **D1** Publier | publier les quatre branches de livraison (§3) / ne pas publier | publier : code public (dépôts lisibles sans identifiants), installation A possible depuis GitHub ; ne pas publier : installation par clones transférés uniquement |
| **D2** Étiquettes et `main` | poser `v1-composition` ou non ; avancer `main` (avance rapide) ou le laisser | étiquettes : commits nommés et repérables ; `main` avancé : la composition devient la référence par défaut ; rien de cela n'est nécessaire au déploiement |
| **D3** Conservation | une durée en jours ou `illimitee` pour chacun des six réglages (§7) ; point de départ des identifiants ; accepter ou remplacer les 30 jours de VIR | sans décision : purge PI refusée (aucune suppression), mais VIR purgerait à 30 jours non approuvés ; une durée finie rend expurgation et suppression exécutables, de façon irréversible |
| **D4** Amendements CPL | approuver ou non REQ-B6-091 et REQ-B5-116 | approuvés : expurgation et suppression gouvernées utilisables ; non approuvés : ne pas exécuter la purge des artefacts ni des dossiers (le code reste installé, sans exécution) |
| **D5** Installation et infrastructure | A (réseau vers PyPI et npm) ou B (hors ligne, roues et cache préparés pour la plateforme) ; serveur, système, domaine, certificat, PostgreSQL, gestion des secrets, emplacement des sauvegardes | A : plus simple, exige la publication ou des clones ; B : prépare un dépôt de roues par plateforme ; dans les deux cas, chemin non encore éprouvé sur le serveur |
| **D6** Calendrier | fenêtre de migration réelle (030/031, après sauvegarde vérifiée) ; date de la première purge réelle | migration : service arrêté pendant la fenêtre, points de non-retour du §6 ; première purge : premières suppressions définitives |

Restent ouvertes, sans devenir de nouvelles exigences (guide §11) : fournisseurs VIR réels (droits non
acquis), analyse photo et tri réels (non autorisés), risque résiduel des essais de connexion, critère de
marché, validation des textes nouveaux.

## 10. Limites de vérification

- Installation **A** (avec réseau) : **non exercée**.
- Installation **B** (hors ligne) : **exercée sur macOS arm64 seulement**.
- **Compatibilité Linux serveur : non exécutée** ; aucun chemin n'est éprouvé sur le serveur.
- Droits d'écriture sur les distants : non vérifiés (aucun `push`).
- Serveur, domaine, certificat, PostgreSQL et secrets de production : non disponibles.
