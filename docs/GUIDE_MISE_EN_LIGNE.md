# Guide de mise en ligne — montage PI / VIR / PGDR / CPL

Guide unique d'installation et d'exploitation (préparation du 2026-10-19, actualisé au bloc 3B
le même jour, puis par la suite du bloc 3B « conservation et purge », branche PI
`pi-3b-conservation-purge`). Aucune valeur secrète ici ; les noms seuls. Ce guide décrit le fonctionnement
technique : il **n'approuve** ni une durée de conservation, ni des droits d'usage de
fournisseurs, ni l'activation d'un composant réel de tri (§9, §10, §11). Liste de réception :
`docs/RECEPTION.md`.

## 1. Composants et commits compatibles

| Composant | Révision | Remarque |
|---|---|---|
| PI (`cpl-product-integration`) | branche `pi-3b-conservation-purge` (depuis `pi-3b-reception-livraison` @ `7010674`, depuis `pi-3a-persistance-securite` @ `a325c23`, qui contient `pi-parcours-photo` @ `2036724` et `pi-preparation-production` @ `434d6c2`) ; révision installée relevée dans `$PREFIX/COMPOSITION.installee` | seule couche de composition |
| VIR | `a4c0172f02e5535d542ecc6f4d16e0c13f9c6b60` (`vir-v1-finalisation`) | non modifié |
| PGDR | `1c5a5cc041f66a959e5bb65918ca7e366223188e` (`v1-3b-reception`, depuis `v1-3a-securite` @ `48d5da4`, depuis `v1-propositions-photo` @ `7302c62`) | statut d'enregistrement du produit affiché sous la restitution ; marché de la notice documenté non vérifiable |
| CPL | `bc09253170256b9888c03249d90b7cac6751311b` (branche `cpl-source-veracity-029`) | migration 029 incluse ; schéma non modifié depuis |
| GGM | 1.0.0, roue SHA-256 `41459158…99a7` | fournie hors PyPI |
| Python | ≥ 3.14 (essais : 3.14.2) | |
| Dépendances Python | `deploy/requirements.lock` (39 paquets, versions exactes) | sans empreintes : les roues diffèrent selon la plateforme |
| Frontend | `frontend/package-lock.json` (`npm ci`) | construit à l'installation |

Les révisions VIR, PGDR, CPL et l'empreinte GGM sont dans `deploy/COMPOSITION.env` ;
l'installateur refuse toute autre révision.

## 2. Architecture d'exécution

```
Internet ──HTTPS──▶ PI public (uvicorn, 1 processus) : /  frontend construit
                                                       /api  API PI-05 (session + CSRF + Origine)
                                                       /health
                     │ boucle locale seulement
                     ├──▶ VIR  127.0.0.1:8001 (jeton de service X-VIR-Service-Token)
                     ├──▶ PGDR 127.0.0.1:8002 (jeton du passage Photo-First ; parcours des
                     │                         voyants /v1 relayé par PI, propriétaire seul)
                     └──▶ PostgreSQL (local) : CPL (schémas cpl, automotive) + pi_auth
```

- Seul le port public de PI est exposé. VIR et PGDR écoutent sur 127.0.0.1 (vérifié, §12) ;
  PostgreSQL doit n'écouter qu'en local (`listen_addresses = 'localhost'`, `pg_hba.conf`
  limité au rôle du service) — configuration du serveur PostgreSQL, à faire par l'exploitant.
- Le navigateur ne détient aucun secret : session dans un cookie `pi_session` HttpOnly,
  Secure, SameSite=Strict ; jeton CSRF dérivé de la session pour les requêtes d'écriture,
  y compris celles de la page des voyants (PI place le jeton dans la page relayée).
  Les jetons entre services (PI→VIR, PI→PGDR) restent côté serveur.
- **Origine (bloc 3B)** : toute écriture (POST, PUT, PATCH, DELETE), connexion comprise, est
  refusée (403) quand le navigateur la dit venue d'ailleurs : `Origin` autre que l'origine du
  produit (`PI_PUBLIC_ORIGIN`, sinon schéma et hôte vus par PI) ou `Sec-Fetch-Site` autre que
  `same-origin`. Les navigateurs envoient `Origin` sur chacune de ces requêtes ; une requête
  sans `Origin` (outil d'exploitation, test) reste soumise au jeton CSRF de la session. Les
  écritures relayées de la page des voyants exigent en plus la présence de l'`Origin` et un
  corps JSON.
- **Un seul processus PI** (`--workers 1`) : les diagnostics PGDR en cours vivent en mémoire.
- Parcours des voyants (PGDR /v1) : ouvert depuis un dossier par son propriétaire
  (`POST /api/cases/{id}/notice-parcours`), puis servi par PI sous `/api/v1…` ; PI vérifie
  à chaque requête que le parcours appartient à l'utilisateur connecté et ne relaie que les
  requêtes de la page (liste fermée). Un parcours **confirmé** est conservé dans CPL avec le
  dossier (sélection du conducteur, confirmation datée, notice et empreinte, Premier Constat,
  provenance, limites ; ni photo, ni réponse du tri, ni catalogue) et reste consultable après
  redémarrage tel qu'il a été confirmé (`GET /api/cases/{id}/notice-results`, écran
  « Confirmed results » du dossier). Un parcours inachevé est en mémoire, comme chez PGDR :
  perdu au redémarrage, jamais présenté comme repris ; l'utilisateur en ouvre un nouveau
  depuis le dossier. L'API doit rester servie sous `/api` (la page de PGDR appelle
  `/api/v1/parcours/…`).
- **Enregistrement du résultat (bloc 3B)** : la restitution porte le statut d'enregistrement
  du produit, affiché par la page sous les textes du constructeur. « Résultat enregistré »
  n'apparaît qu'après la validation de l'écriture dans CPL. Si CPL refuse, les textes du
  constructeur restent affichés avec « Résultat non enregistré » et un bouton « Réessayer
  l'enregistrement » : `POST /api/v1/parcours/{id}/record`, traité par PI seul (ni PGDR, ni
  tri, ni VIR), qui réécrit l'enregistrement gardé tel qu'il a été confirmé, sans doublon
  (clé d'idempotence tirée du contenu). Cet enregistrement non écrit est gardé en mémoire
  avec le parcours : un redémarrage le perd (le conducteur rouvre alors la notice).
  Détails : `docs/build/PI_PARCOURS_PHOTO_V1_COMPTE_RENDU_v0.md`,
  `docs/build/PI_BLOC_3A_COMPTE_RENDU_v0.md`, `docs/build/PI_BLOC_3B_COMPTE_RENDU_v0.md`.

## 3. Installation

Prérequis serveur : Python 3.14, Node.js + npm (construction du frontend), git, rsync,
PostgreSQL 16 (client `pg_dump`/`pg_restore` compris), accès à PyPI et au registre npm pendant
l'installation seulement (ou un dépôt de roues et un cache npm locaux, ci-dessous).

```bash
PREFIX=/opt/cpl-produit \
VIR_SRC=<dépôt ou URL git VIR> PGDR_SRC=<dépôt PGDR> CPL_SRC=<dépôt CPL> \
GGM_WHEEL=<chemin de ggm-1.0.0-py3-none-any.whl> \
<dépôt PI>/deploy/installer.sh
$PREFIX/venv/bin/pip check && cat $PREFIX/COMPOSITION.installee
```

Résultat : `$PREFIX/venv`, `$PREFIX/src/{vir,pgdr,cpl,pi}` (clones aux révisions exactes),
`$PREFIX/frontend-dist` (frontend de production, aucun serveur Vite), et
`$PREFIX/COMPOSITION.installee`. Les builds se font dans `$PREFIX/build`, jamais dans les
dépôts sources. L'installateur refuse un PREFIX déjà utilisé et un dépôt PI non commité ; les
fichiers non commités des dépôts sources (par exemple des courriers en cours dans VIR) ne sont
jamais copiés : seuls les commits de `deploy/COMPOSITION.env` le sont.

Sans réseau : pip lit `PIP_NO_INDEX=1` et `PIP_FIND_LINKS=<dépôt de roues>` (les 39 paquets du
verrou, plus les outils de construction setuptools, wheel, hatchling et ses dépendances
packaging, pathspec, pluggy, trove-classifiers, tomlkit) ; npm lit `npm_config_offline=true`
et `npm_config_cache=<cache>`. Installation vérifiée ainsi (§12).

## 4. Configuration et secrets (noms seulement)

Modèle : `deploy/secrets.env.exemple`. À fournir à l'exécution (gestionnaire de secrets ou
fichier `root:cpl-produit` 0640 hors dépôt, ex. `/etc/cpl-produit/montage.env`) :

| Nom | Rôle |
|---|---|
| `DATABASE_URL` | base PostgreSQL CPL + pi_auth (`postgresql+psycopg2://…`) |
| `VIR_SERVICE_TOKEN` | jeton de service VIR (repris par PI comme `PI_VIR_SERVICE_TOKEN`) |
| `VIR_DATA_ENCRYPTION_KEY` | clé de chiffrement du stockage VIR (perte = données VIR illisibles) |
| `PGDR_IDENTITY_HANDOFF_TOKEN` | jeton du passage d'identité Photo-First PI→PGDR |
| `PI_LOGIN_THROTTLE_SECRET` | secret HMAC des compteurs de connexion (32 caractères au moins) ; sans lui PI refuse de démarrer et `reset-password` refuse de s'exécuter |
| `PI_LOGIN_THROTTLE_SECRET_PREVIOUS` | ancien secret, pendant un renouvellement seulement (§5) |
| `PI_PUBLIC_ORIGIN` | origine exacte du produit (`https://<domaine>[:port]`) exigée de **toute** écriture envoyée par un navigateur (§2) ; à défaut, schéma et hôte vus par PI — à fixer dès qu'un proxy réécrit l'hôte |
| `PI_TRUSTED_PROXIES` | seulement si un proxy TLS est placé devant PI : ses adresses ; absent, aucun en-tête `X-Forwarded-*` n'est cru |
| `PI_PUBLIC_HOST`, `PI_PUBLIC_PORT` | adresse publique d'écoute |
| `PI_TLS_CERT`, `PI_TLS_KEY` | certificat et clé TLS du domaine |
| `MONTAGE_DIR` | dossier d'exécution et de journaux (sans `.env`) |
| `VIR_DATABASE_PATH` | fichier SQLite de VIR (chemin absolu, persistant) |
| `PI05_MEDIA_STORAGE_DIR` | médias envoyés (persistant) |
| `PI_FRONTEND_DIST` | `$PREFIX/frontend-dist` (active le mode production) |
| `VIR_RETENTION_DAYS` | durée de conservation VIR (stockage VIR seulement) : **décision du propriétaire, non prise** (§9) |
| `PI_CONSERVATION_IDENTIFIANTS_JOURS`, `PI_CONSERVATION_DOSSIERS_JOURS`, `PI_CONSERVATION_MEDIAS_JOURS`, `PI_CONSERVATION_JOURNAUX_JOURS`, `PI_CONSERVATION_SAUVEGARDES_JOURS` | politique de conservation par catégorie (§9) : nombre entier de jours ou `illimitee` ; **aucune valeur décidée, aucune par défaut** |
| `SAUVEGARDES_DIR` | dossier des sauvegardes de `deploy/sauvegarder.sh` (§8) |

Notice des voyants (lus par PGDR, voir le README de PGDR) : `PGDR_V1_MANIFEST` (notice revue,
hors dépôt) et ses fichiers facultatifs `PGDR_V1_*`. **`PGDR_V1_TRI` doit rester absent en
production** : le seul transport de tri existant est un faux transport d'essai, que PGDR
n'accepte que pour un essai signalé (`PGDR_V1_ESSAI_TRI=1`, bandeau permanent) et que
`scripts/lancer_montage.sh` refuse en mode production (comme `PGDR_V1_DEV_TRIAL`) ; sans lui,
la photo reste sur l'appareil et le catalogue complet est affiché avec son explication.

Facultatifs : `PI_SESSION_IDLE_MINUTES` (30), `PI_SESSION_MAX_HOURS` (12),
`VIR_PROVIDER_MODE` (`simulated` ; seul mode démontré). `PI_COOKIE_SECURE=0` est refusé en
production. En développement derrière Vite (`changeOrigin`), `PI_PUBLIC_ORIGIN=http://127.0.0.1:5173`
est nécessaire à toute écriture.

Stockage et permissions : utilisateur système dédié (`cpl-produit`), `umask 077` (scripts et
unité), `MONTAGE_DIR`, médias et base VIR en 0700/0600, frontend construit en lecture seule.

## 5. Création de compte et mots de passe

Pas d'inscription publique, aucun compte ni mot de passe par défaut.

```bash
$PREFIX/venv/bin/python -m product_integration.auth.cli create-account --login <identifiant> [--display-name "<nom>"]
# mot de passe saisi deux fois sans écho (12 caractères au moins, différent de l'identifiant) ;
# --password-stdin lit une ligne sur l'entrée standard (provisionnement scripté)
```

Autres commandes : `disable-account` / `enable-account --login …` (sessions supprimées à la
désactivation), `purge-sessions` (sessions expirées et compteurs d'échecs échus). Un nom
« admin » ne donne aucun droit particulier.

Mot de passe : l'utilisateur le change lui-même (page « Change password » : mot de passe actuel
exigé). L'opérateur le réinitialise avec `reset-password --login <identifiant>` (saisie masquée
deux fois, ou `--password-stdin`), **dans l'environnement du service** (`PI_LOGIN_THROTTLE_SECRET`
compris, pour effacer les compteurs du compte) : sans ce secret la commande refuse avant toute
saisie (code 2, ligne d'audit `result=refused_config`), rien n'est modifié. Changements et
réinitialisations, réussis ou refusés, laissent une ligne
`audit date=… operation=… result=… actor=… target=…` (compte `account:<id>`, `operator` ou `-`)
dans le journal du service (`pi05.log`) ou sur la sortie d'erreur de la commande ; jamais de mot
de passe, jeton, cookie, identifiant de connexion ni adresse. Dans les deux cas toutes les
sessions du compte sont révoquées ; le compte et le contact CPL gardent leurs identifiants,
rien n'est désactivé ni recréé. Ne plus désactiver puis recréer un compte pour changer un mot de
passe : cela crée un nouveau contact sans ses dossiers.

Essais de mot de passe : 5 échecs par couple identifiant/origine, 50 par origine, 100 par
identifiant toutes origines, sur 15 min, chacun bloquant 15 min. Les compteurs ne gardent que
des HMAC (secret `PI_LOGIN_THROTTLE_SECRET`), ni identifiant ni adresse. Renouvellement du
secret : nouveau secret dans `PI_LOGIN_THROTTLE_SECRET`, ancien dans
`PI_LOGIN_THROTTLE_SECRET_PREVIOUS` pendant au moins 30 minutes (les verrous en cours restent
appliqués, aucun compte n'est bloqué par le renouvellement), puis retirer l'ancien ; ses
compteurs cessent de compter et `purge-sessions` les supprime. L'origine est l'adresse vue par
PI-05 : sans proxy, `scripts/lancer_montage.sh` lance PI avec `--no-proxy-headers` ; derrière un
proxy TLS, définir `PI_TRUSTED_PROXIES` (le script passe `--proxy-headers
--forwarded-allow-ips=<ces adresses>`), sinon toutes les connexions partagent l'adresse du proxy.
**Risque résiduel, non accepté à ce jour par le propriétaire** : un essai réparti sur de
nombreuses origines contre un même identifiant bloque ce compte 15 min pour toutes les origines,
titulaire compris, après 100 échecs.

## 6. Lancement, santé, arrêt, redémarrage

```bash
deploy/migrer.sh upgrade                     # avant le premier lancement (§7)
scripts/lancer_montage.sh                    # avec PI_FRONTEND_DIST : mode production
curl -fsS https://<domaine>:<port>/health    # {"status":"ok"} ; 503 si la base est injoignable
```

Arrêt : SIGTERM au script (ou `systemctl stop cpl-produit`) ; chaque service s'arrête en 10 s
au plus (`--timeout-graceful-shutdown 10`), même si un client laisse une connexion TLS inactive
ouverte (sans cette borne, l'arrêt attendait 30 s, au-delà du `TimeoutStopSec=20` de l'unité).

Journaux : `MONTAGE_DIR/pi05.log`, `pgdr.log`, `vir.log`, **complétés à chaque démarrage, jamais
tronqués** (avant le bloc 3B, chaque redémarrage les effaçait, lignes d'audit comprises).
PI et PGDR sont lancés sans journal d'accès d'uvicorn (`--no-access-log`) ; chaque requête
laisse une ligne avec le gabarit de route (ex. `POST /api/v1/parcours/{pid}{sub_path:path} 200`)
ou un libellé fixe, jamais le chemin réel, la requête, un en-tête ou un corps ; une exception
laisse sa seule classe et une réponse 500 simple. Le journal d'accès de VIR (`vir.log`) n'a pas
été modifié. Rotation : à la charge de l'exploitant (ex. logrotate avec `copytruncate`) ; suppression des
fichiers tournés échus par la purge (`PI_CONSERVATION_JOURNAUX_JOURS`, §9), durée non décidée.

Unité systemd modèle : `deploy/systemd/cpl-produit.service`
(`systemctl start|stop|restart|status cpl-produit`). Le script arrête tout le montage si l'un
des trois services s'arrête ; `Restart=on-failure` relance l'ensemble.

Au redémarrage : comptes, sessions web, dossiers, résultats confirmés, historiques et médias sont
conservés ; **un diagnostic PGDR en attente de réponse est perdu** — la réponse suivante est
refusée par `409 PROCESS_LOCAL_STATE_UNAVAILABLE`, l'exécution reste lisible (BLOCKED) ; un
parcours des voyants inachevé, et un résultat confirmé que CPL n'a pas enregistré, sont perdus
(le conducteur rouvre la notice depuis le dossier).

## 7. Migrations et retour arrière

Toujours précédées d'une sauvegarde (§8).

```bash
deploy/migrer.sh upgrade          # CPL jusqu'à 029 (head), puis schéma pi_auth
deploy/migrer.sh downgrade 028    # supprime pi_auth (comptes et sessions), puis CPL → 028
```

La descente de 029 est documentée par CPL comme non totalement réversible (états
`OWNER_ATTESTED_UNVERIFIED`). Base VIR existante : ordre de `docs/LIVRAISON_VIR_V1.md` §6
(dépôt VIR) — `vir backup`, `vir migrate-owners`, `vir migrate-storage`, `vir check-storage`.
Retour arrière du code : arrêter, réinstaller la composition précédente dans un PREFIX neuf
(`deploy/installer.sh` depuis l'ancien commit PI), restaurer si besoin la sauvegarde prise
avant la migration (§8), relancer.

## 8. Sauvegarde et restauration

```bash
SAUVEGARDES_DIR=<dossier> deploy/sauvegarder.sh   # → SAUVEGARDES_DIR/pi-sauvegarde-<AAAAMMJJTHHMMSSZ>/
DEST=<dossier neuf> deploy/sauvegarder.sh         # hors du nettoyage : jamais supprimée par les scripts
SOURCE=<dossier> deploy/restaurer.sh              # SERVICES ARRÊTÉS ; vérifie les empreintes
deploy/nettoyer_sauvegardes.sh [--executer]       # sauvegardes échues ; simulation par défaut
```

Une sauvegarde contient `postgresql.dump`, `vir.db` (sauvegarde VIR, chiffrée ; la clé n'y est
pas), `medias.tar`, `SHA256SUMS`, `COMPOSITION.installee` et un `MANIFESTE` (format
`pi-sauvegarde-1`, date de création UTC, liste exacte des fichiers). Dossier en 0700, fichiers en
lecture seule (0400).

**Nettoyage** (`nettoyer_sauvegardes.sh`, durée `PI_CONSERVATION_SAUVEGARDES_JOURS` depuis la date
du manifeste) : ne supprime que les dossiers `pi-sauvegarde-<horodatage>` placés directement dans
`SAUVEGARDES_DIR` et les dossiers de médias mis de côté par la restauration
(`<PI05_MEDIA_STORAGE_DIR>.avant-restauration-<horodatage>`, manifeste `pi-avant-restauration-1`),
et seulement si le manifeste et le contenu correspondent exactement ; un dossier contenant autre
chose (fichier, sous-dossier, lien, clé) est « non reconnu », signalé et conservé. Aucun
répertoire n'est vidé de façon générique. Sans politique : la simulation le dit, l'exécution est
refusée. La copie de la base VIR mise de côté par VIR (`<base VIR>.avant-restauration-<horodatage>`)
appartient à VIR : non traitée, suppression manuelle selon la même règle.

**Les anciennes sauvegardes gardent les données qu'elles contiennent (plaque et VIN compris)
jusqu'à leur propre échéance** : purger les données actives ne les efface pas, et aucune
suppression immédiate n'est promise.

**Restauration** : remplace les objets PostgreSQL sauvegardés, fait restaurer VIR par sa propre
commande, met de côté le dossier de médias actuel (avec son manifeste, jamais supprimé ici) et
contrôle le stockage VIR. Exige `MONTAGE_DIR`, `VIR_RETENTION_DAYS` et la politique (§9). Avant
toute réouverture :

1. `MONTAGE_DIR/RESTAURATION_A_PURGER` est posé dès le début ; `scripts/lancer_montage.sh` refuse
   de démarrer tant qu'il existe ;
2. le schéma PI est mis à jour (sauvegarde antérieure aux tables de traçage) ;
3. `conservation.cli apres-restauration` révoque **toutes les sessions web** (les accès ne sont
   pas restaurés : chacun se reconnecte), puis exécute la purge : les identifiants déjà échus
   (l'échéance part de la date d'enregistrement, conservée dans la sauvegarde) sont vidés de
   nouveau, les médias échus supprimés ; puis `purge-sessions` et `vir purge` ;
4. le verrou n'est retiré qu'en cas de succès ; sinon (politique absente, erreur) le message
   « politique de conservation NON appliquée : service fermé » est affiché et le verrou reste.

Le script ne relance jamais le service : l'exploitant vérifie, puis le démarre explicitement.
Vérifié (§12) : restauration dans une base neuve, purge avant ouverture, dossier lisible dans le
navigateur, identification « no longer kept », session antérieure refusée.

## 9. Conservation des données — politique et purge

Aucune durée n'est décidée par ce guide ni par le code. Chaque catégorie a son réglage explicite ;
absent, il vaut « non définie » (jamais un nombre) : la simulation dit « aucune politique, rien ne
serait supprimé », l'exécution est refusée avant toute écriture. `VIR_RETENTION_DAYS` ne règle que
le stockage VIR et n'est jamais repris pour une autre catégorie.

| Catégorie | Réglage | Unité | Point de départ (implémenté) | Mécanisme |
|---|---|---|---|---|
| Plaque et VIN et leurs copies dans CPL | `PI_CONSERVATION_IDENTIFIANTS_JOURS` | jours de 24 h (UTC) ou `illimitee` | `enregistrement_cpl` : date d'écriture dans CPL de l'enregistrement d'identification qui porte la copie | purge (§9.2) |
| Dossiers et résultats (dont Premiers Constats) | `PI_CONSERVATION_DOSSIERS_JOURS` | idem | création du dossier | **aucune suppression possible** : CPL n'en prévoit aucune ; seule `illimitee` est exécutable, une durée est refusée |
| Médias envoyés | `PI_CONSERVATION_MEDIAS_JOURS` | idem | `envoi` (date de l'envoi) | purge par âge ; fichiers supprimés, référence gardée « no longer kept » |
| Journaux tournés | `PI_CONSERVATION_JOURNAUX_JOURS` | idem | dernière modification du fichier | suppression des seuls fichiers `pi05.log`, `pgdr.log`, `vir.log` suivis d'un suffixe de rotation (`.1`, `.2.gz`, `-AAAAMMJJ[.gz]`) ; les journaux actifs ne sont jamais touchés |
| Sauvegardes et médias mis de côté | `PI_CONSERVATION_SAUVEGARDES_JOURS` | idem | date de création du manifeste | `deploy/nettoyer_sauvegardes.sh` (§8) |
| VIR : demandes, résolutions, preuves (chiffrées) | `VIR_RETENTION_DAYS` (réglage existant de VIR) | jours | création, échéance fixée à la création | purge VIR à chaque écriture et `vir purge` ; **30 jours par défaut du code VIR, non approuvés** |
| Sessions web, compteurs de connexion | `PI_SESSION_*` | minutes / heures | — | `purge-sessions` |

Points de départ possibles pour les identifiants : création (enregistrement), dernière
confirmation par le conducteur, dernière consultation. **Un seul est implémenté,
`enregistrement_cpl` ; le choix reste au propriétaire.** Une confirmation, correction ou un retrait
du conducteur écrit un nouvel enregistrement qui ouvre sa propre période (l'ancien suit la sienne).
La dernière consultation n'est enregistrée nulle part aujourd'hui.

### 9.1 Plaque et VIN dans CPL — emplacements

Relevé sur la base d'essai (toutes les colonnes texte, JSON et tableaux des schémas `cpl`,
`automotive`, `pi_auth`, après identification par VIN et par plaque, clarification, confirmation,
Premier Constat) :

| Emplacement | Contenu | Traitement par la purge |
|---|---|---|
| `cpl.asset_identity_resolutions.canonical_identity_payload` (une par résultat VIR enregistré, y compris confirmations, corrections, retraits) | `identifiers.vin`, `identifiers.registration_number` | vidés (null) ; `identifiers_not_kept` liste les champs retirés ; pays d'immatriculation, autres champs, statut, provenance et liens conservés |
| `automotive.vehicle_details` | `vin_display`, `registration_display` | vidés quand aucun enregistrement d'identification encore dans sa période ne porte la même valeur ; marque, modèle, pays, `source_resolution_id` conservés |
| `cpl.runner_artifacts.payload`, artefacts `vir_resolution` | identité, candidats, `field_evidence[]` | **non vidés** (§9.3) |

Ni `pi_auth`, ni les Premiers Constats (`pgdr_v1_premier_constat`), ni le passage vers PGDR, ni les
journaux ne contiennent plaque ou VIN. Les copies dans le stockage VIR suivent `VIR_RETENTION_DAYS`.

### 9.2 Commandes

```bash
deploy/purger.sh                 # simulation : nombres par catégorie, rien n'est modifié (même sans politique)
deploy/purger.sh --executer      # exécution : purge de conservation, puis purge-sessions et vir purge
$PREFIX/venv/bin/python -m product_integration.conservation.cli controle   # contrôle de préparation
deploy/nettoyer_sauvegardes.sh [--executer]                                # sauvegardes (§8)
```

Exécution : par lots (`--lot`, 200 par défaut), chacun dans sa transaction ; sur une erreur, le
lot en cours est annulé, les précédents restent, la commande s'arrête (code 1, classe de l'erreur
seulement) et la relance reprend le reste ; une deuxième exécution ne refait rien. Chaque
exécution laisse une trace dans `pi_auth.conservation_operations` (politique, nombres, issue) et
chaque copie vidée une ligne dans `pi_auth.identifier_expunctions` (noms des champs, opération) —
jamais une valeur. Sorties : catégories et nombres seulement.

Consultation après purge : le dossier, son historique et ses résultats confirmés restent lisibles
par leur propriétaire (404 pour autrui) ; les détails d'identité répondent « plus conservés »
(410 `VIR_RESULT_NOT_KEPT`, message du frontend « no longer kept »), même si VIR garde encore son
résultat ; une confirmation ou clarification est refusée de même, rien n'est écrit. Un média purgé
répond 410 `MEDIA_NOT_KEPT` (« This photo is no longer kept »). Les textes du constructeur et la
sélection du conducteur ne sont pas modifiés.

Médias : la purge par âge **ne garantit pas** l'absence de plaque ou de VIN dans les images encore
conservées (contenu des pixels non vérifiable).

Contrôle de préparation : signale toute catégorie non définie, une durée pour les dossiers,
`VIR_RETENTION_DAYS` absent, un verrou de restauration, et rappelle la limite des artefacts. En mode
production, `scripts/lancer_montage.sh` l'exécute et affiche un avertissement si la configuration
est incomplète (sans bloquer : les durées ne sont pas décidées).

### 9.3 Artefacts `vir_resolution` — expurgation impossible sans évolution de CPL

Arrêt sur ce point, conformément à la consigne : CPL conserve chaque ligne d'artefact en entier
(REQ-B6-058), ne corrige un contenu que par remplacement (supersession), qui garde l'ancienne
ligne (REQ-B6-057/059), et signale tout contenu qui ne correspond plus à son `content_hash` sans
jamais le corriger (REQ-B6-053 à 055). Vider la plaque et le VIN d'un artefact casserait ces
invariants ; aucune requête directe ni désactivation de protection n'a été employée. Conséquence :
**après purge, les artefacts `vir_resolution` échus gardent plaque et VIN dans PostgreSQL et dans
les sauvegardes.** Ils ne sont pas servis par le produit (la route des artefacts retire déjà les
identifiants) ; la purge les compte (« artefact(s) vir_resolution échu(s) gardent plaque et VIN »).
Les lever demande une décision du propriétaire et une évolution de CPL (par exemple une expurgation
gouvernée, avec trace et empreinte recalculée déclarée, au sens de la réserve « separate retention
policy » de B4 §63), hors de cette passe.

## 10. Limites effectives

- **Analyse photo indisponible.** Aucun fournisseur vision qualifié ni autorisé (chantier
  Vision clos par le propriétaire le 2026-09-30, 7 configurations sur 7 désactivées). Le
  frontend l'indique ; PGDR répond `photo_analysis_unavailable` au passage Photo-First. Passage
  vers un fournisseur vision non implémenté : confidentialité de bout en bout non démontrée ;
  le contenu des pixels (plaque ou VIN visibles) n'est pas vérifiable.
- **Images proposées à partir de la photo** (parcours /v1, décision du propriétaire du
  2026-10-19) : raccordées et vérifiées sur **faux transport de tri uniquement** ; qualité
  réelle du tri non démontrée, composant réel non autorisé. En production : tri absent,
  catalogue complet avec explication.
- **Marché de la notice : non vérifiable.** Ni la notice (manifeste, revue) ni l'identité VIR
  ne portent de marché ; le critère n'est jamais présenté comme satisfait et n'est pas déduit
  du pays d'immatriculation. Aucune règle existante de PGDR n'en fait une condition
  d'ouverture (identité, véhicule et période de la notice, `applicability_established` de la
  revue) : selon les règles actuelles, cette incertitude ne bloque pas l'ouverture. En faire
  une condition est une décision du propriétaire ; aucune règle n'a été ajoutée.
- PGDR : sessions de diagnostic et parcours des voyants en mémoire, un seul processus, perdus
  au redémarrage ; le résultat d'un parcours confirmé est conservé dans CPL.
- VIR : mode `simulated` seul démontré ; vrais adaptateurs RegCheck et Vincario vérifiés sur
  faux transports seulement ; aucun fournisseur réel consulté.
- Textes nouveaux du produit (« Résultat enregistré… », « Résultat non enregistré… »,
  « Réessayer l'enregistrement », message « no longer kept ») : rédigés pour ce bloc, non
  validés par le propriétaire.
- Limitation des essais par identifiant et origine, par origine et par identifiant (§5) ;
  risque résiduel d'un essai réparti sur de nombreuses origines (§5), non accepté à ce jour.
- Pays d'immatriculation : France seule (registre VIR actuel).
- Dépendances verrouillées par version, sans empreintes de fichiers.
- Partage d'un véhicule : seul le modèle CPL existant (relations contact–véhicule) le
  permet ; aucun écran de partage n'existe. Un dossier n'est visible que de son contact
  principal.

## 11. Conditions externes restantes

1. Serveur et système d'exploitation, nom de domaine, certificat TLS du domaine, port public.
2. Instance PostgreSQL de production (accès local seulement) et emplacement des sauvegardes.
3. Gestionnaire de secrets (ou fichier protégé) pour les valeurs du §4.
4. Décisions du propriétaire sur la conservation (§9) : durée VIR (`VIR_RETENTION_DAYS`, les
   30 jours par défaut **ne sont pas une durée approuvée**), plaque et VIN (et point de départ),
   dossiers (illimitée ou évolution de CPL), médias, journaux, sauvegardes ; sort des artefacts
   `vir_resolution` (§9.3, évolution de CPL).
5. Droits d'usage et contrats des fournisseurs VIR (RegCheck, Vincario) : **non acquis** ;
   tant qu'ils ne le sont pas, VIR reste en mode simulé ; aucune activation réelle autorisée.
6. Décision de fusion des branches PI (`pi-3b-reception-livraison`), PGDR (`v1-3b-reception`)
   et CPL (`cpl-source-veracity-029`) ; migration réelle de la base jusqu'à 029.
7. Analyse photo : nouveau mandat, qualification et autorisation distinctes (§10) ; de même
   pour tout composant réel de tri des images proposées (fournisseur, conservation, contrat,
   évaluation de la qualité sur notice réelle).
8. Décisions du propriétaire : risque résiduel des essais de connexion (§5) ; critère de
   marché (§10) ; validation des textes nouveaux (§10).

## 12. Vérification de la livraison (bloc 3B)

Conservation et purge : `docs/build/PI_CONSERVATION_COMPTE_RENDU_v0.md`.

Installation par `deploy/installer.sh` depuis les dépôts d'origine aux commits de
`deploy/COMPOSITION.env`, sans réseau, dans un PREFIX neuf, puis migrations sur bases
temporaires, lancement de production HTTPS, parcours complet, mots de passe, arrêt,
sauvegarde, restauration dans une base neuve, purge, journaux. Résultats et commandes :
`docs/build/PI_BLOC_3B_COMPTE_RENDU_v0.md` ; liste de réception : `docs/RECEPTION.md`.
