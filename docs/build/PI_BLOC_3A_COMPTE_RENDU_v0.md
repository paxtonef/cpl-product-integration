# Bloc 3A — persistance du parcours et correctifs de sécurité — compte rendu v0

Date : 2026-10-19. Branches : PI `pi-3a-persistance-securite` (depuis `pi-parcours-photo` @
`2036724`, qui contient `434d6c2`), PGDR `v1-3a-securite` (depuis `v1-propositions-photo` @
`7302c62`, commit `48d5da4`). CPL `cpl-source-veracity-029` @ `bc09253` et VIR
`vir-v1-finalisation` @ `a4c0172` : lus, non modifiés. Aucun push, aucune fusion, aucun appel
fournisseur ou modèle, aucune migration réelle.

## 1. Persistance du parcours photo (CPL, structures existantes)

- Un parcours **confirmé** est conservé par PI dans CPL, sans changer le schéma CPL : une
  `RunnerExecution` (`runner_type` `PGDR_V1_NOTICE`, sous le dossier, `initiated_by_contact_id`
  = propriétaire) et un artefact (schéma `pgdr_v1_premier_constat` v1, enregistré comme
  `vir_resolution`), admission, artefact et rapport `COMPLETED` dans **une seule transaction**
  (`product_integration.pgdr.notice_results`).
- Contenu : dossier et propriétaire ; résolution VIR d'ouverture (exécution, artefact,
  `resolution_id`) ; notice (document, titre, édition, langue, empreinte du contenu) ;
  `entry_ids` sélectionnés **par le conducteur** (`by: driver`, jamais une reconnaissance) ;
  confirmation explicite et sa date ; Premier Constat et sections exactes produits par PGDR pour
  les seules entrées choisies ; provenance ; limites. Jamais : photo, réponse du tri, images
  proposées, catalogue, identifiant de parcours (liens d'images réécrits en empreinte).
- Déclenchement : réponse de PGDR en phase `restitution` après `/confirm` (ou `/clarify`,
  `/condition`, qui suivent une confirmation) ; chaque restitution distincte est un
  enregistrement. Idempotence : clé dérivée du contenu (double clic, requêtes concurrentes =
  un enregistrement).
- Lecture : `GET /api/cases/{id}/notice-results`, propriétaire seul (autrui : `404`),
  CPL seul — ni PGDR, ni tri ; fidèle à ce qui a été confirmé, une notice plus récente ne le
  remplace pas. Frontend : « Confirmed results » dans le dossier.
- Parcours inachevé au redémarrage : inconnu (« Parcours inconnu ou expiré. Rouvrez la notice
  depuis votre dossier : un nouveau parcours commencera. ») ; la réouverture crée un nouveau
  parcours depuis le début, jamais présenté comme repris.
- Décision d'implémentation à valider : si CPL refuse l'enregistrement, rien n'est écrit et le
  conducteur voit tout de même les textes du constructeur (une ligne de journal fixe le signale).

## 2. Compteurs de connexion

- HMAC-SHA256 avec `PI_LOGIN_THROTTLE_SECRET` (≥ 32 caractères, fourni à l'exécution ; absent
  du dépôt et des journaux) ; sans lui, l'entrée de production refuse de démarrer.
- Renouvellement : ancien secret dans `PI_LOGIN_THROTTLE_SECRET_PREVIOUS` (verrous maintenus,
  jamais écrit) ; retiré, ses compteurs ne comptent plus et sont purgés à échéance. Aucun compte
  bloqué par un renouvellement. Schéma `pi_auth` v3 : suppression des anciens compteurs SHA-256.
- `X-Forwarded-*` : `--no-proxy-headers` sauf `PI_TRUSTED_PROXIES` (vérifié sur le vrai
  lancement : un `X-Forwarded-For` venu d'un pair non configuré ne contourne pas le verrou).
- **Risque résiduel, non déclaré accepté par le propriétaire** : un essai réparti sur de
  nombreuses origines bloque le compte visé 15 min pour toutes les origines après 100 échecs.

## 3. Audit des mots de passe

Avant : sous uvicorn, les lignes `logger.info` étaient perdues (aucun gestionnaire). Après :
`product_integration.audit`, gestionnaire propre sur la sortie d'erreur ; une ligne par
changement (utilisateur) et réinitialisation (opérateur), succès et échecs (`refused`,
`refused_policy`, `refused_unknown_login`, `refused_input`, `failure`), avec date, opération,
résultat, acteur et cible opaques (`account:<id>`, `operator`, `-`). Jamais mot de passe, jeton,
cookie, identifiant de connexion ni adresse. Account, Contact, objets, refus de l'ancien mot de
passe, révocation et transaction unique : inchangés et retestés.

## 4. CSRF du relais PGDR

Le CSRF existant de PI remplace la protection précédente : PI place le jeton de la session dans
la page relayée (`<meta name="csrf-token">`), la page de PGDR l'envoie en `X-CSRF-Token` sur
chaque écriture (PGDR `48d5da4`), PI le compare à celui de la session. Chaque écriture relayée
exige aussi : `Origin` égale à l'origine du produit (`PI_PUBLIC_ORIGIN`, sinon schéma et hôte
vus par le serveur ; `X-Forwarded-Host` jamais lu), `Sec-Fetch-Site` same-origin s'il est
présent, corps JSON ; méthodes GET/POST seules ; propriétaire vérifié à chaque requête.
SameSite et `Sec-Fetch-Site` sont conservés sans être suffisants seuls. Aucun jeton de service
dans le navigateur ; CSP de la page inchangée (empreinte du script, `default-src 'none'`).
En développement derrière Vite, `PI_PUBLIC_ORIGIN=http://127.0.0.1:5173`.

## 5. Journaux

PI, entrée publique et PGDR lancés avec `--no-access-log` ; un middleware par service écrit
méthode, gabarit de route ou libellé fixe, statut, durée ; une exception = sa classe seule et un
500 simple. VIR non modifié (son journal d'accès reste celui d'uvicorn).

## 6. Applicabilité (PGDR)

Défaut démontré et corrigé : l'ouverture reposait sur le statut global (`resolved` seul), et une
identité `resolved` dont VIR déclarait la génération non résolue ou le modèle contradictoire
ouvrait un parcours ; la période de la notice était ignorée. Désormais : statut à identité unique
(résolu ou provisoire), puis constructeur, modèle, génération établis par VIR, véhicule de la
notice, période de la notice si elle en déclare une. Notice non établie refusée hors essai de
développement ; aucun choix par défaut ; configuration inchangée. Marché : aucun champ de marché
dans le format de notice ni dans l'identité transmise — critère **non vérifiable** en l'état.

## 7. Garde-fou du tri (PGDR)

Faux transport accepté depuis la configuration seulement pour un essai signalé
(`PGDR_V1_ESSAI_TRI=1`, bandeau permanent sur chaque écran) ; sinon refusé, catalogue complet avec
explication. `scripts/lancer_montage.sh` refuse `PGDR_V1_TRI*`, `PGDR_V1_ESSAI_TRI` et
`PGDR_V1_DEV_TRIAL` en mode production.

## 8. Vérification [exécuté]

Cluster PostgreSQL 16 dédié (port 55497), garde réseau (hors boucle locale refusé), notice
FICTIVE, faux tri seulement.

| Suite | Résultat |
|---|---|
| PI pytest (dont 43 nouveaux, lancement réel compris) | 353 passed, 0 skipped |
| PGDR pytest (dont 24 nouveaux) | 1017 passed, 0 skipped |
| Frontend : unitaires, typage, build | 50 passed ; OK |
| Playwright A→M, O1–O4 (essai signalé de faux tri) | 15 passed (13 au premier passage ; M — variable d'essai manquante — et O1 — message attendu modifié par le §1 — repassés ensuite avec O) |
| Playwright P (tri en panne ; tri absent) | 1 + 1 passed |

Chaque nouveau test a été exécuté avant correction (échec) puis après (succès) ; les tests du
lancement réel l'ont été contre `2036724`/`7302c62` (6 échecs) puis la branche 3A (6 succès).

## 9. Reporté (non fait)

- Playwright N (VIR réel sur faux transports) non relancé ; aucun e2e TypeScript pour l'écran
  « Confirmed results » (unitaires seulement ; parcours confirmé et redémarrage vérifiés par le
  test du lancement réel).
- Journal d'accès de VIR non modifié.
- Les autres routes d'écriture du produit gardent le seul jeton CSRF (pas de contrôle d'`Origin`).
- Décision du propriétaire sur le risque résiduel du §2 et sur le comportement du §1 quand CPL
  refuse l'enregistrement.
