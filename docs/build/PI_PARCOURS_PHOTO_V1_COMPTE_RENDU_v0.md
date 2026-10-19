# Parcours photo convenu — raccordement PI ↔ PGDR /v1 (bloc 2) — compte rendu v0

Date : 2026-10-19. Branches : PI `pi-parcours-photo` (depuis `pi-preparation-production` @ `434d6c2`),
PGDR `v1-propositions-photo` (depuis `v1-premier-constat` @ `7b863c0`). Aucun push, aucune fusion.

## 1. Décision appliquée

Décision du propriétaire du 2026-10-19 : 1 à 3 images proposées sont autorisées comme aide à la
sélection ; le catalogue complet reste accessible à tout moment. Elle prévaut sur PGDR-V1-02
(mise à jour dans `outils/preparation_v1/config/pgdr_cbs_requirements.yaml` de PGDR). L'ancien
chantier vision (clos le 2026-09-30) reste clos ; le script `trier_images.py` (ordre complet) n'est
pas raccordé : le parcours a son propre contrat strict (`pgdr.v1_propositions`).

## 2. Parcours

1. Dossier (propriétaire) → « Open the manufacturer notice » → `POST /api/cases/{id}/notice-parcours`
   (session + CSRF). PI relit l'artefact VIR du dossier, applique `map_resolution()` (identité
   filtrée : ni plaque, ni VIN, ni date de carte grise ; une valeur seulement confirmée par le
   conducteur est transmise comme inconnue), puis `POST /api/v1/vir-handoff` de PGDR (jeton).
   PGDR ouvre le parcours ou refuse avec sa propre raison (`vehicle_identity_insufficient`,
   `notice_unavailable`, `vehicle_not_supported`, `applicability_not_confirmed`), affichée telle
   quelle ; aucune notice n'est supposée.
2. Page /v1 de PGDR servie par PI (`/api/v1?p=…`) : consentement du parcours, photo facultative.
3. Avec un transport de tri : accord séparé nommant le destinataire ; la page réencode la photo
   (pixels seuls), PI retire les métadonnées restantes (`strip_metadata` de PGDR), PGDR les retire
   encore avant le transport. 1 à 3 images proposées, dans l'ordre de la notice, aucune
   présélection, ni score, ni classement ; « Aucune ne correspond : voir toutes les images de la
   notice ».
4. Sélection et confirmation explicites (étapes existantes) → texte exact de la notice et Premier
   Constat existants (moteur de sécurité, R-5, abstentions et vérification humaine inchangés).
5. Sans tri, tri en panne, réponse invalide (plus de 3, hors catalogue, champ en plus comme un
   score), aucune proposition, photo illisible : catalogue complet dans l'ordre de la notice avec
   l'explication correspondante. Ce repli ne dit rien de la qualité du tri.

## 3. Droits et protections (PI)

- Registre `parcours → (dossier, contact)` en mémoire (`product_integration.pgdr.notice_parcours`) ;
  toute requête relayée vérifie la session et le propriétaire ; un parcours d'autrui reçoit la même
  réponse qu'un parcours inexistant (`404`, « Parcours inconnu ou expiré. »).
- Liste fermée des requêtes relayées (celles de la page) ; ni `vir-handoff`, ni `essai-dev`.
- Requêtes d'écriture relayées : cookie SameSite=Strict, corps JSON uniquement (415 sinon),
  `Sec-Fetch-Site` same-origin s'il est présent (403 sinon), identifiant de parcours imprévisible
  dans le chemin. La page de PGDR n'envoie pas l'en-tête CSRF de PI : ces protections le remplacent
  pour ces seules routes ; l'ouverture garde le CSRF de PI.
- Page relayée avec sa propre CSP (empreinte SHA-256 du script de la page, `default-src 'none'`,
  `frame-ancestors 'none'`), `Referrer-Policy: no-referrer`, `Cache-Control: no-store` partout.
- Corps relayés bornés (21,5 Mo) avant tout appel à PGDR ; client HTTP vers PGDR sans proxy
  d'environnement (`trust_env=False`). PI ne stocke pas la photo.
- Images du catalogue (notice privée) et résultat : servis au seul propriétaire du parcours.

## 4. Vérification [exécuté]

Bases PostgreSQL temporaires (cluster 16 dédié, port 55491), garde réseau (connexions hors boucle
locale refusées), notice FICTIVE, faux transport de tri uniquement.

| Suite | Résultat |
|---|---|
| PI pytest (dont `tests/test_notice_parcours.py`, 22) | 310 passed, 0 skipped |
| PGDR pytest (dont propositions 73 + navigateur 9) | 993 passed, 0 skipped |
| Frontend : typage, unitaires, build | OK ; 48 passed ; build OK |
| Playwright A→M, O1–O4 (faux tri) | 18 passed |
| Playwright P (tri absent ; faux tri en panne) | 1 + 1 passed |
| Playwright N (VIR réel sur faux transports) | 2 passed |
| Journaux du montage (VIN, plaque, photo, jetons, mots de passe, traces) | 0 occurrence |

Scénarios : C photo → propositions → sélection → notice → Premier Constat ; D propositions non
reconnues → catalogue → sélection ; E tri absent / en panne / réponse invalide → catalogue
expliqué ; F aucune image → écran rouge existant ; G identité provisoire, valeur seulement
confirmée, notice d'un autre véhicule, applicabilité non confirmée, notice absente → refus ;
refus croisés entre deux utilisateurs (API et navigateur).

## 5. Limites

- **Tri : qualité réelle non démontrée, composant réel non autorisé.** Seul le faux transport
  existe ; `PGDR_V1_TRI` doit rester absent en production.
- Les métadonnées sont retirées, pas les identifiants visibles dans les pixels.
- Registre PI et parcours PGDR en mémoire : perdus au redémarrage ; un seul processus.
- Le parcours n'enregistre ni exécution ni artefact CPL (résultat non persisté).
- Les identifiants opaques de parcours (`V1-…`) figurent dans les journaux d'accès uvicorn
  (chemins de requête), comme avant pour PGDR ; inutilisables sans la session du propriétaire.
- L'API doit être servie sous `/api` (chemins fixes de la page de PGDR).
- `deploy/COMPOSITION.env` désigne la révision PGDR qui contient `pgdr.v1_propositions`.
