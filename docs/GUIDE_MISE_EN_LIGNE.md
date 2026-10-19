# Guide de mise en ligne — montage PI / VIR / PGDR / CPL

Guide unique d'installation et d'exploitation (préparation du 2026-10-19). Aucune valeur
secrète ici ; les noms seuls. Ce guide décrit le fonctionnement technique : il **n'approuve**
ni une durée de conservation, ni des droits d'usage de fournisseurs (§10).

## 1. Composants et commits compatibles

| Composant | Révision | Remarque |
|---|---|---|
| PI (`cpl-product-integration`) | branche `pi-preparation-production` (révision installée relevée dans `$PREFIX/COMPOSITION.installee`) | seule couche de composition |
| VIR | `a4c0172f02e5535d542ecc6f4d16e0c13f9c6b60` (`vir-v1-finalisation`) | non modifié |
| PGDR | `7b863c0bcef8fc1244c47b54a51e9cf4daa5e209` (`v1-premier-constat`) | non modifié |
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
                     ├──▶ PGDR 127.0.0.1:8002 (jeton du passage Photo-First)
                     └──▶ PostgreSQL (local) : CPL (schémas cpl, automotive) + pi_auth
```

- Seul le port public de PI est exposé. VIR et PGDR écoutent sur 127.0.0.1 ; PostgreSQL doit
  n'écouter qu'en local (`listen_addresses = 'localhost'`, `pg_hba.conf` limité au rôle du
  service) — configuration du serveur PostgreSQL, à faire par l'exploitant.
- Le navigateur ne détient aucun secret : session dans un cookie `pi_session` HttpOnly,
  Secure, SameSite=Strict ; jeton CSRF dérivé de la session pour les requêtes d'écriture.
  Les jetons entre services (PI→VIR, PI→PGDR) restent côté serveur.
- **Un seul processus PI** (`--workers 1`) : les diagnostics PGDR en cours vivent en mémoire.

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
| `PI_PUBLIC_HOST`, `PI_PUBLIC_PORT` | adresse publique d'écoute |
| `PI_TLS_CERT`, `PI_TLS_KEY` | certificat et clé TLS du domaine |
| `MONTAGE_DIR` | dossier d'exécution et de journaux (sans `.env`) |
| `VIR_DATABASE_PATH` | fichier SQLite de VIR (chemin absolu, persistant) |
| `PI05_MEDIA_STORAGE_DIR` | médias envoyés (persistant) |
| `PI_FRONTEND_DIST` | `$PREFIX/frontend-dist` (active le mode production) |
| `VIR_RETENTION_DAYS` | durée de conservation VIR : **décision du propriétaire, non prise** |

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
sort sur la sortie d'erreur. Dans les deux cas toutes les sessions du compte sont révoquées ; le
compte et le contact CPL gardent leurs identifiants, rien n'est désactivé ni recréé. Ne plus
désactiver puis recréer un compte pour changer un mot de passe : cela crée un nouveau contact
sans ses dossiers.

Essais de mot de passe : 5 échecs par couple identifiant/origine, 50 par origine, 100 par
identifiant toutes origines, sur 15 min, chacun bloquant 15 min. L'origine est l'adresse vue par
PI-05 : derrière un proxy TLS, lancer uvicorn avec `--proxy-headers --forwarded-allow-ips=<proxy>`,
sinon toutes les connexions partagent l'adresse du proxy.

## 6. Lancement, santé, arrêt, redémarrage

```bash
deploy/migrer.sh upgrade                     # avant le premier lancement (§7)
scripts/lancer_montage.sh                    # avec PI_FRONTEND_DIST : mode production
curl -fsS https://<domaine>:<port>/health    # {"status":"ok"} ; 503 si la base est injoignable
```

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
- PGDR : sessions de diagnostic en mémoire, un seul processus, perdues au redémarrage.
- VIR : mode `simulated` seul démontré ; aucun fournisseur réel consulté.
- Verrouillage d'un compte 15 min après 5 échecs de connexion (aucune limitation par adresse :
  un tiers peut bloquer temporairement un compte dont il connaît l'identifiant).
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
7. Analyse photo : nouveau mandat, qualification et autorisation distinctes (§9).
