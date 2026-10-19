# Guide de mise en ligne — montage PI / VIR / PGDR / CPL

Guide unique d'installation et d'exploitation (préparation du 2026-10-19). Aucune valeur
secrète ici ; les noms seuls. Ce guide décrit le fonctionnement technique : il **n'approuve**
ni une durée de conservation, ni des droits d'usage de fournisseurs (§10).

## 1. Composants et commits compatibles

| Composant | Révision | Remarque |
|---|---|---|
| PI (`cpl-product-integration`) | branche `pi-3a-persistance-securite` (depuis `pi-parcours-photo` @ `2036724`, qui contient `pi-preparation-production` @ `434d6c2` ; révision installée relevée dans `$PREFIX/COMPOSITION.installee`) | seule couche de composition |
| VIR | `a4c0172f02e5535d542ecc6f4d16e0c13f9c6b60` (`vir-v1-finalisation`) | non modifié |
| PGDR | `48d5da41db1066a57b7cb223ad00efd9cd03461e` (`v1-3a-securite`, depuis `v1-propositions-photo` @ `7302c62`) | images proposées (faux tri en essai signalé seulement), applicabilité sur critères réels, jeton CSRF de la page, journaux par gabarit |
| CPL | `bc09253170256b9888c03249d90b7cac6751311b` (branche `cpl-source-veracity-029`) | migration 029 incluse |
| GGM | 1.0.0, roue SHA-256 `41459158…99a7` | fournie hors PyPI |
| Python | ≥ 3.14 (essais : 3.14.2) | |
| Dépendances Python | `deploy/requirements.lock` (39 paquets, versions exactes) | sans empreintes : les roues diffèrent selon la plateforme |
| Frontend | `frontend/package-lock.json` (`npm ci`) | construit à l'installation |

Les révisions VIR, PGDR, CPL et l'empreinte GGM sont dans `deploy/COMPOSITION.env` ;
l'installateur refuse toute autre révision.

## 2. Architecture d'exécution

```
Internet ──HTTPS──▶ PI public (uvicorn, 1 processus) : /  frontend construit
                                                       /api  API PI-05 (session + CSRF)
                                                       /health
                     │ boucle locale seulement
                     ├──▶ VIR  127.0.0.1:8001 (jeton de service X-VIR-Service-Token)
                     ├──▶ PGDR 127.0.0.1:8002 (jeton du passage Photo-First ; parcours des
                     │                         voyants /v1 relayé par PI, propriétaire seul)
                     └──▶ PostgreSQL (local) : CPL (schémas cpl, automotive) + pi_auth
```

- Seul le port public de PI est exposé. VIR et PGDR écoutent sur 127.0.0.1 ; PostgreSQL doit
  n'écouter qu'en local (`listen_addresses = 'localhost'`, `pg_hba.conf` limité au rôle du
  service) — configuration du serveur PostgreSQL, à faire par l'exploitant.
- Le navigateur ne détient aucun secret : session dans un cookie `pi_session` HttpOnly,
  Secure, SameSite=Strict ; jeton CSRF dérivé de la session pour les requêtes d'écriture,
  y compris celles de la page des voyants (PI place le jeton dans la page relayée ; chaque
  écriture relayée exige ce jeton, l'origine exacte du produit et un corps JSON).
  Les jetons entre services (PI→VIR, PI→PGDR) restent côté serveur.
- **Un seul processus PI** (`--workers 1`) : les diagnostics PGDR en cours vivent en mémoire.
- Parcours des voyants (PGDR /v1) : ouvert depuis un dossier par son propriétaire
  (`POST /api/cases/{id}/notice-parcours`), puis servi par PI sous `/api/v1…` ; PI vérifie
  à chaque requête que le parcours appartient à l'utilisateur connecté et ne relaie que les
  requêtes de la page (liste fermée). Un parcours **confirmé** est conservé dans CPL avec le
  dossier (sélection du conducteur, confirmation datée, notice et empreinte, Premier Constat,
  provenance, limites ; ni photo, ni réponse du tri, ni catalogue) et reste consultable après
  redémarrage tel qu'il a été confirmé (`GET /api/cases/{id}/notice-results`). Un parcours
  inachevé est en mémoire, comme chez PGDR : perdu au redémarrage, jamais présenté comme
  repris ; l'utilisateur en ouvre un nouveau depuis le dossier.
  L'API doit rester servie sous `/api` (la page de PGDR appelle `/api/v1/parcours/…`).
  Détails : `docs/build/PI_PARCOURS_PHOTO_V1_COMPTE_RENDU_v0.md`,
  `docs/build/PI_BLOC_3A_COMPTE_RENDU_v0.md`.

## 3. Installation

Prérequis serveur : Python 3.14, Node.js + npm (construction du frontend), git, rsync,
PostgreSQL 16 (client `pg_dump`/`pg_restore` compris), accès à PyPI et au registre npm pendant
l'installation seulement.

```bash
PREFIX=/opt/cpl-produit \
VIR_SRC=<dépôt ou URL git VIR> PGDR_SRC=<dépôt PGDR> CPL_SRC=<dépôt CPL> \
GGM_WHEEL=<chemin de ggm-1.0.0-py3-none-any.whl> \
<dépôt PI>/deploy/installer.sh
```

Résultat : `$PREFIX/venv`, `$PREFIX/src/{vir,pgdr,cpl,pi}` aux révisions exactes,
`$PREFIX/frontend-dist` (frontend de production, aucun serveur Vite), et
`$PREFIX/COMPOSITION.installee`. Les builds se font dans `$PREFIX/build`, jamais dans les
dépôts sources. L'installateur refuse un PREFIX déjà utilisé et un dépôt PI non commité.

## 4. Configuration et secrets (noms seulement)

Modèle : `deploy/secrets.env.exemple`. À fournir à l'exécution (gestionnaire de secrets ou
fichier `root:cpl-produit` 0640 hors dépôt, ex. `/etc/cpl-produit/montage.env`) :

| Nom | Rôle |
|---|---|
| `DATABASE_URL` | base PostgreSQL CPL + pi_auth (`postgresql+psycopg2://…`) |
| `VIR_SERVICE_TOKEN` | jeton de service VIR (repris par PI comme `PI_VIR_SERVICE_TOKEN`) |
| `VIR_DATA_ENCRYPTION_KEY` | clé de chiffrement du stockage VIR (perte = données VIR illisibles) |
| `PGDR_IDENTITY_HANDOFF_TOKEN` | jeton du passage d'identité Photo-First PI→PGDR |
| `PI_LOGIN_THROTTLE_SECRET` | secret HMAC des compteurs de connexion (32 caractères au moins) ; sans lui PI refuse de démarrer |
| `PI_LOGIN_THROTTLE_SECRET_PREVIOUS` | ancien secret, pendant un renouvellement seulement (§5) |
| `PI_PUBLIC_ORIGIN` | origine exacte du produit (`https://<domaine>[:port]`) exigée des écritures du parcours des voyants ; à défaut, schéma et hôte vus par PI |
| `PI_TRUSTED_PROXIES` | seulement si un proxy TLS est placé devant PI : ses adresses ; absent, aucun en-tête `X-Forwarded-*` n'est cru |
| `PI_PUBLIC_HOST`, `PI_PUBLIC_PORT` | adresse publique d'écoute |
| `PI_TLS_CERT`, `PI_TLS_KEY` | certificat et clé TLS du domaine |
| `MONTAGE_DIR` | dossier d'exécution et de journaux (sans `.env`) |
| `VIR_DATABASE_PATH` | fichier SQLite de VIR (chemin absolu, persistant) |
| `PI05_MEDIA_STORAGE_DIR` | médias envoyés (persistant) |
| `PI_FRONTEND_DIST` | `$PREFIX/frontend-dist` (active le mode production) |
| `VIR_RETENTION_DAYS` | durée de conservation VIR : **décision du propriétaire, non prise** |

Notice des voyants (lus par PGDR, voir le README de PGDR) : `PGDR_V1_MANIFEST` (notice revue,
hors dépôt) et ses fichiers facultatifs `PGDR_V1_*`. **`PGDR_V1_TRI` doit rester absent en
production** : le seul transport de tri existant est un faux transport d'essai, que PGDR
n'accepte que pour un essai signalé (`PGDR_V1_ESSAI_TRI=1`, bandeau permanent) et que
`scripts/lancer_montage.sh` refuse en mode production (comme `PGDR_V1_DEV_TRIAL`) ; sans lui,
la photo reste sur l'appareil et le catalogue complet est affiché avec son explication.

Facultatifs : `PI_SESSION_IDLE_MINUTES` (30), `PI_SESSION_MAX_HOURS` (12),
`VIR_PROVIDER_MODE` (`simulated` ; seul mode démontré). `PI_COOKIE_SECURE=0` est refusé en
production.

Stockage et permissions : utilisateur système dédié (`cpl-produit`), `umask 077` (scripts et
unité), `MONTAGE_DIR`, médias et base VIR en 0700/0600, frontend construit en lecture seule.

## 5. Création du compte initial

Pas d'inscription publique, aucun compte ni mot de passe par défaut.

```bash
$PREFIX/venv/bin/python -m product_integration.auth.cli create-account --login <identifiant> [--display-name "<nom>"]
# mot de passe saisi deux fois sans écho (12 caractères au moins, différent de l'identifiant)
```

Autres commandes : `disable-account` / `enable-account --login …` (sessions supprimées à la
désactivation), `purge-sessions` (sessions expirées et compteurs d'échecs échus). Un nom
« admin » ne donne aucun droit particulier.

Mot de passe : l'utilisateur le change lui-même (page « Change password » : mot de passe actuel
exigé). L'opérateur le réinitialise avec
`reset-password --login <identifiant>` (saisie masquée deux fois, ou `--password-stdin`) ; la
ligne d'audit (identifiant de compte seul, jamais le mot de passe ni l'identifiant de connexion)
sort sur la sortie d'erreur. Changements et réinitialisations, réussis ou refusés, laissent une
ligne `audit date=… operation=… result=… actor=… target=…` (compte `account:<id>`, `operator`
ou `-`) dans le journal du service (`pi05.log`) ou sur la sortie d'erreur de la commande ; jamais
de mot de passe, jeton, cookie, identifiant de connexion ni adresse. Dans les deux cas toutes les sessions du compte sont révoquées ; le
compte et le contact CPL gardent leurs identifiants, rien n'est désactivé ni recréé. Ne plus
désactiver puis recréer un compte pour changer un mot de passe : cela crée un nouveau contact
sans ses dossiers.

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

Journaux : PI et PGDR sont lancés sans journal d'accès d'uvicorn (`--no-access-log`) ; chaque
requête laisse une ligne avec le gabarit de route (ex. `POST /api/v1/parcours/{pid}{sub_path:path} 200`)
ou un libellé fixe, jamais le chemin réel, la requête, un en-tête ou un corps ; une exception
laisse sa seule classe et une réponse 500 simple. Le journal d'accès de VIR (`vir.log`) n'a
pas été modifié.

Unité systemd modèle : `deploy/systemd/cpl-produit.service`
(`systemctl start|stop|restart|status cpl-produit`). Le script arrête tout le montage si l'un
des trois services s'arrête ; `Restart=on-failure` relance l'ensemble.

Au redémarrage : comptes, sessions web, dossiers, résultats, historiques et médias sont
conservés ; **un diagnostic PGDR en attente de réponse est perdu** — la réponse suivante est
refusée par `409 PROCESS_LOCAL_STATE_UNAVAILABLE`, l'exécution reste lisible (BLOCKED).

## 7. Migrations et retour arrière

Toujours précédées d'une sauvegarde (§8).

```bash
deploy/migrer.sh upgrade          # CPL jusqu'à 029 (head), puis schéma pi_auth
deploy/migrer.sh downgrade 028    # supprime pi_auth (comptes et sessions), puis CPL → 028
```

La descente de 029 est documentée par CPL comme non totalement réversible (états
`OWNER_ATTESTED_UNVERIFIED`). Base VIR existante : ordre de `docs/LIVRAISON_VIR_V1.md` §6
(dépôt VIR) — `vir backup`, `vir migrate-owners`, `vir migrate-storage`, `vir check-storage`.

## 8. Sauvegarde et restauration

```bash
DEST=<dossier neuf> deploy/sauvegarder.sh     # postgresql.dump + vir.db (sauvegarde VIR) + medias.tar + SHA256SUMS
SOURCE=<dossier> deploy/restaurer.sh          # SERVICES ARRÊTÉS ; vérifie les empreintes
```

La restauration remplace les objets PostgreSQL sauvegardés, fait restaurer VIR par sa propre
commande (base actuelle mise de côté), renomme le dossier de médias actuel (jamais supprimé),
puis contrôle le stockage VIR. Purge : `deploy/purger.sh` (sessions expirées ; enregistrements
VIR échus, refusée tant que `VIR_RETENTION_DAYS` n'est pas fixé). Dossiers, résultats et
médias CPL/PI ne sont pas purgés : aucune règle n'est décidée.

## 9. Limites effectives

- **Analyse photo indisponible.** Aucun fournisseur vision qualifié ni autorisé (chantier
  Vision clos par le propriétaire le 2026-09-30, 7 configurations sur 7 désactivées). Le
  frontend l'indique ; PGDR répond `photo_analysis_unavailable` au passage Photo-First. Passage
  vers un fournisseur vision non implémenté : confidentialité de bout en bout non démontrée ;
  le contenu des pixels (plaque ou VIN visibles) n'est pas vérifiable.
- **Images proposées à partir de la photo** (parcours /v1, décision du propriétaire du
  2026-10-19) : raccordées et vérifiées sur **faux transport de tri uniquement** ; qualité
  réelle non démontrée, composant réel non autorisé. En production : tri absent, catalogue
  complet avec explication.
- PGDR : sessions de diagnostic et parcours des voyants en mémoire, un seul processus, perdus
  au redémarrage ; le résultat d'un parcours confirmé est conservé dans CPL.
- VIR : mode `simulated` seul démontré ; aucun fournisseur réel consulté.
- Limitation des essais par identifiant et origine, par origine et par identifiant (§5) ;
  risque résiduel d'un essai réparti sur de nombreuses origines (§5), non accepté à ce jour.
- Pays d'immatriculation : France seule (registre VIR actuel).
- Dépendances verrouillées par version, sans empreintes de fichiers.
- Partage d'un véhicule : seul le modèle CPL existant (relations contact–véhicule) le
  permet ; aucun écran de partage n'existe. Un dossier n'est visible que de son contact
  principal.

## 10. Conditions externes restantes

1. Serveur et système d'exploitation, nom de domaine, certificat TLS du domaine, port public.
2. Instance PostgreSQL de production (accès local seulement) et emplacement des sauvegardes.
3. Gestionnaire de secrets (ou fichier protégé) pour les valeurs du §4.
4. Décision du propriétaire sur la durée de conservation (`VIR_RETENTION_DAYS`) : la valeur
   par défaut de VIR (30 jours) **n'est pas une durée approuvée**.
5. Droits d'usage et contrats des fournisseurs VIR (RegCheck, Vincario) : **non acquis** ;
   tant qu'ils ne le sont pas, VIR reste en mode simulé.
6. Décision de fusion des branches PI (`pi-preparation-production`) et CPL
   (`cpl-source-veracity-029`) ; migration réelle de la base jusqu'à 029.
7. Analyse photo : nouveau mandat, qualification et autorisation distinctes (§9) ; de même
   pour tout composant réel de tri des images proposées (fournisseur, conservation, contrat,
   évaluation de la qualité sur notice réelle).
