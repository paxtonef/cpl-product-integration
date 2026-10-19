# Guide de mise en ligne — montage PI / VIR / PGDR / CPL

Guide unique d'installation et d'exploitation (préparation du 2026-10-19, actualisé au bloc 3B
le même jour). Aucune valeur secrète ici ; les noms seuls. Ce guide décrit le fonctionnement
technique : il **n'approuve** ni une durée de conservation, ni des droits d'usage de
fournisseurs, ni l'activation d'un composant réel de tri (§9, §10, §11). Liste de réception :
`docs/RECEPTION.md`.

## 1. Composants et commits compatibles

| Composant | Révision | Remarque |
|---|---|---|
| PI (`cpl-product-integration`) | branche `pi-3b-reception-livraison` (depuis `pi-3a-persistance-securite` @ `a325c23`, qui contient `pi-parcours-photo` @ `2036724` et `pi-preparation-production` @ `434d6c2`) ; révision installée relevée dans `$PREFIX/COMPOSITION.installee` | seule couche de composition |
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
| `VIR_RETENTION_DAYS` | durée de conservation VIR : **décision du propriétaire, non prise** (§9) |

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
été modifié. Rotation : à la charge de l'exploitant (ex. logrotate avec `copytruncate`) ; durée
de conservation des journaux : décision restante (§9).

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
DEST=<dossier neuf> deploy/sauvegarder.sh     # postgresql.dump + vir.db (sauvegarde VIR) + medias.tar + SHA256SUMS
SOURCE=<dossier> deploy/restaurer.sh          # SERVICES ARRÊTÉS ; vérifie les empreintes
```

La restauration remplace les objets PostgreSQL sauvegardés, fait restaurer VIR par sa propre
commande (base actuelle mise de côté en `<base>.avant-restauration-<horodatage>`), renomme le
dossier de médias actuel (`<dossier>.avant-restauration-<horodatage>`, jamais supprimé), puis
contrôle le stockage VIR. Vérifié dans une base neuve (§12) : dossiers, résultats confirmés,
provenance et droits identiques (le propriétaire lit, un autre compte reçoit 404).

Après restauration d'une sauvegarde ancienne, les données purgées depuis réapparaissent :
lancer `deploy/purger.sh` aussitôt (VIR purge aussi à sa première écriture). Les copies
« avant-restauration » contiennent les données de production : elles font partie du cycle des
sauvegardes (§9) et sont à supprimer selon la même règle.

## 9. Conservation des données — bilan

Aucune durée n'est décidée par ce guide. « Durée configurée » = ce que fait le code aujourd'hui.

| Données | Où | Durée configurée aujourd'hui | Mécanisme | Décision restante |
|---|---|---|---|---|
| VIR : demandes, résolutions, preuves (chiffrées) | `VIR_DATABASE_PATH` | `VIR_RETENTION_DAYS`, **30 jours par défaut du code, non approuvés** ; échéance fixée à la création (changer la durée ne modifie pas les enregistrements existants) | purge automatique à chaque écriture VIR ; `vir purge` (via `deploy/purger.sh`, qui refuse tant que `VIR_RETENTION_DAYS` n'est pas fixé) | durée VIR |
| CPL : dossiers, exécutions, artefacts (dont la résolution VIR avec plaque et VIN), résolutions d'identité, `vehicle_details`, résultats confirmés du parcours | PostgreSQL (`cpl`, `automotive`) | aucune limite | aucun | durée et règle de suppression ; plaque et VIN (§9.1) |
| PI : comptes, empreintes de mots de passe | PostgreSQL (`pi_auth`) | tant que le compte existe | aucun | règle pour les comptes inactifs |
| PI : sessions web | PostgreSQL (`pi_auth.web_sessions`) | 30 min d'inactivité, 12 h au plus (`PI_SESSION_*`) ; lignes expirées gardées jusqu'à la purge | `purge-sessions` (dans `deploy/purger.sh`) | fréquence de la purge |
| PI : compteurs de connexion (HMAC) | PostgreSQL (`pi_auth.login_throttle`) | fenêtre de 15 min | `purge-sessions` | — |
| Médias envoyés | `PI05_MEDIA_STORAGE_DIR` | aucune limite | aucun | durée |
| Photo du parcours des voyants | non conservée (ni PI, ni PGDR, ni CPL) | — | — | — |
| Parcours inachevé ; résultat non enregistré | mémoire de PI et PGDR | jusqu'au redémarrage (1000 parcours au plus) | — | — |
| Journaux | `MONTAGE_DIR/{pi05,pgdr,vir}.log` | aucune limite (complétés) | rotation par l'exploitant | durée |
| Sauvegardes et copies « avant-restauration » | `DEST` de `sauvegarder.sh`, à côté de la base VIR et du dossier de médias | aucune limite | suppression manuelle | lieu, durée, nombre |

- **30 jours ne sont pas une durée approuvée** (dépôt VIR, `docs/LIVRAISON_VIR_V1.md` §7).
- **Supprimer des données actives n'efface pas les sauvegardes.** Une sauvegarde contient la
  base PostgreSQL entière (CPL avec plaque et VIN, `pi_auth` avec empreintes de mots de passe et
  de sessions), la base VIR (chiffrée ; la clé n'y est pas) et les médias. Elle vit jusqu'à sa
  suppression manuelle ; restaurée, elle réintroduit ce qui avait été purgé (§8). La durée des
  sauvegardes doit donc être décidée avec celle des données, et la purge relancée après toute
  restauration.
- Après la purge VIR, le dossier reste lisible ; les détails d'identité répondent « plus
  conservés » (410 `VIR_RESULT_NOT_KEPT`, message dédié dans le frontend), une confirmation est
  refusée de même, rien n'est écrit ; les résultats confirmés restent dans CPL.
- Purge essayée sur données fictives (§12) : refus sans `VIR_RETENTION_DAYS` ; une session
  expirée et un enregistrement VIR échu supprimés ; CPL, médias et sauvegarde inchangés.

### 9.1 Plaque et VIN dans CPL — décision du propriétaire

Relevé sur la base d'essai (requêtes sur toutes les colonnes texte et JSON des schémas `cpl`,
`automotive`, `pi_auth`) ; le schéma CPL n'est pas modifié :

| Emplacement | Contenu |
|---|---|
| `cpl.runner_artifacts.payload`, artefacts `vir_resolution` (un par résultat VIR enregistré, y compris après confirmation, correction ou retrait) | `vehicle_identity.identifiers.vin`, `vehicle_identity.identifiers.registration_number` ; et dans `field_evidence[]` : `resolved_value`, `sources[].reported_value`, `sources[].source_value` |
| `cpl.asset_identity_resolutions.canonical_identity_payload` (résolution d'identité consommée pour l'actif) | `identifiers.vin`, `identifiers.registration_number` |
| `automotive.vehicle_details` | `vin_display`, `registration_display` (avec `registration_country`) |

Ni `pi_auth`, ni les résultats du parcours des voyants (`pgdr_v1_premier_constat`), ni le
passage d'identité vers PGDR ne les contiennent. Conservation actuelle : **sans limite**, hors
de toute purge, indépendante de la purge VIR (VIR peut avoir supprimé sa résolution alors que
CPL en garde la copie), et incluse dans chaque sauvegarde. À décider par le propriétaire, avec
la durée de conservation : garder ou non ces identifiants dans CPL, combien de temps, et selon
quelle règle de suppression (aucune n'existe dans CPL aujourd'hui).

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
   30 jours par défaut **ne sont pas une durée approuvée**), CPL (dont plaque et VIN, §9.1),
   médias, journaux, sauvegardes.
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

Installation par `deploy/installer.sh` depuis les dépôts d'origine aux commits de
`deploy/COMPOSITION.env`, sans réseau, dans un PREFIX neuf, puis migrations sur bases
temporaires, lancement de production HTTPS, parcours complet, mots de passe, arrêt,
sauvegarde, restauration dans une base neuve, purge, journaux. Résultats et commandes :
`docs/build/PI_BLOC_3B_COMPTE_RENDU_v0.md` ; liste de réception : `docs/RECEPTION.md`.
