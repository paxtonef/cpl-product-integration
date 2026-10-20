# Liste de réception — blocs 1, 2 et 3

Actualisée le 2026-10-19 (bloc 3B, puis conservation et purge : PI `pi-3b-conservation-purge`), sur la composition de `deploy/COMPOSITION.env` : PI
`pi-3b-reception-livraison`, PGDR `1c5a5cc`, VIR `a4c0172`, CPL `bc09253`. Lignes 3.15e et 3.15k–3.15r
actualisées le 2026-10-20 (conservation 1/3 à 3/3 et contrôle navigateur) : PI `pi-conservation-integration`,
PGDR `55f76ae`, VIR `a4c0172`, CPL `ced7e4b` (migrations 030 et 031). Données et comptes
fictifs, bases PostgreSQL temporaires (cluster dédié), réseau extérieur bloqué (garde des
essais : toute connexion hors boucle locale refusée), aucun fournisseur réel, aucun tri réel.

Étiquettes : **[exécuté]** vérifié par un essai de ce bloc ; **[code]** assuré par le code et
ses tests ; **[documentation]** décrit seulement ; **[non vérifiable]** ne peut pas être établi
avec ce qui existe.

- Bloc 1 — comptes et VIR dans le produit (`pi-preparation-production` @ `434d6c2`).
- Bloc 2 — parcours des voyants avec images proposées (PI `2036724`, PGDR `7302c62`).
- Bloc 3 — 3A persistance et sécurité (PI `a325c23`, PGDR `48d5da4`) et 3B réception commune et
  livraison (PI `d9f8fdd`, `281d243`, PGDR `1c5a5cc`).

Preuves : « PW » = Playwright du frontend (`frontend/tests/e2e`, lettre de la spec) ; « T » =
fichier de `tests/` de PI ; « P » = fichier de `tests/` de PGDR ; « V » = vérification de
l'installation (`docs/build/PI_BLOC_3B_COMPTE_RENDU_v0.md` §4). Résultats chiffrés : même
compte rendu, §3.

## Bloc 1 — comptes et VIR dans le produit

| # | Contrôle | Résultat | Preuve | Étiquette |
|---|---|---|---|---|
| 1.1 | Connexion par compte, sessions, refus sans session ni CSRF | réussi | PW A, L ; T `test_pi05_authentication.py` ; V | [exécuté] |
| 1.2 | Pays d'immatriculation choisi explicitement ; VIN sans pays refusé | réussi | PW A, N ; T `test_vir_registration_country.py` | [exécuté] |
| 1.3 | Plaque et VIN | réussi (VIN et plaque, vrais adaptateurs sur faux transports) | PW N (2 tests) ; V | [exécuté] |
| 1.4 | Consentement requis avant toute consultation | réussi ; aucune consultation sans consentement (compteur des faux transports) | PW N | [exécuté] |
| 1.5 | Résultat VIR : inconnus, provenance, contradictions, données marquées simulées | réussi | PW N ; T `test_vir_product.py` | [exécuté] |
| 1.6 | Confirmation, correction, retrait | réussi | PW N ; T `test_vir_product.py` | [exécuté] |
| 1.7 | Aucune consultation cachée au rafraîchissement, au rechargement, aux confirmations | réussi : exactement 1 consultation par identification (VIN : Vincario ; plaque : RegCheck), 0 ensuite | PW N (journal des faux transports) | [exécuté] |
| 1.8 | Clarification inconnue refusée avant VIR | réussi | PW B ; T `test_vir_clarification_refusal.py` | [exécuté] |
| 1.9 | Identité ou passage PI-02 insuffisant → refus gouverné | réussi | PW C ; T `test_pgdr_handoff_mapper.py` | [exécuté] |
| 1.10 | Diagnostic, questions, escalade, panne technique, reprise | réussi | PW D, E, F, I, J, K | [exécuté] |
| 1.11 | Historique, rafraîchissement, retour au dossier | réussi | PW G, H | [exécuté] |
| 1.12 | Changement de mot de passe (utilisateur) ; réinitialisation (opérateur) | réussi ; refus net sans le secret du service (défaut corrigé en 3B) | PW M ; T `test_account_password.py`, `test_3b_cli_reset_sans_secret.py` ; V | [exécuté] |
| 1.13 | Refus croisés entre deux comptes (identiques à « inexistant ») | réussi | PW L ; T `test_product_api.py`, `test_notice_parcours.py` ; V | [exécuté] |
| 1.14 | Identification purgée par VIR : « plus conservée », jamais « panne » | réussi (défaut corrigé en 3B) | T `test_3b_vir_echu.py` ; unitaire `ErrorBanner` ; V | [exécuté] |
| 1.15 | Fournisseurs VIR réels | non consultés ; autorisation non acquise | — | [non vérifiable] |

## Bloc 2 — parcours des voyants, images proposées

| # | Contrôle | Résultat | Preuve | Étiquette |
|---|---|---|---|---|
| 2.1 | Photo → propositions (faux transport, essai signalé) → sélection → notice → Premier Constat | réussi | PW O ; T `test_notice_parcours.py` ; P `test_v1_propositions_e2e.py` | [exécuté] |
| 2.2 | Propositions non reconnues → catalogue complet → sélection | réussi | PW O ; T, P | [exécuté] |
| 2.3 | Tri absent / en panne / réponse invalide → catalogue expliqué (repli) | réussi (absent et panne en navigateur) | PW P ×2 ; T, P | [exécuté] |
| 2.4 | Aucune image reconnue → issue de sécurité existante | réussi | PW O ; T, P | [exécuté] |
| 2.5 | Identité ou notice insuffisante → refus, aucune notice supposée | réussi | T `test_notice_parcours.py` (G) ; P `test_v1_3a_applicabilite.py` | [exécuté] |
| 2.6 | Images de notice servies au seul propriétaire, CSP de la page | réussi | V ; T `test_3a_lancement_reel.py` | [exécuté] |
| 2.7 | Qualité réelle du tri | non démontrée ; composant réel non autorisé | — | [non vérifiable] |
| 2.8 | Marché de la notice | non vérifiable ; non présenté comme satisfait ; non bloquant selon les règles existantes | README PGDR ; guide §10 | [documentation] [non vérifiable] |

## Bloc 3 — persistance, sécurité, réception commune et livraison

| # | Contrôle | Résultat | Preuve | Étiquette |
|---|---|---|---|---|
| 3.1 | Confirmation → résultat conservé dans CPL, une transaction, sans doublon | réussi | T `test_3a_persistance_parcours.py` ; V | [exécuté] |
| 3.2 | Écran « Confirmed results » : fidèle après redémarrage complet, propriétaire, refus d'un autre compte | réussi (navigateur, frontend construit, HTTPS) | T `test_3b_reception_navigateur.py` | [exécuté] |
| 3.3 | Échec d'enregistrement CPL : textes visibles, « Résultat non enregistré », nouvelle tentative sans diagnostic, tri ni fournisseur, sans doublon, jamais d'annonce avant confirmation | réussi (API et navigateur ; refus réel de PostgreSQL en navigateur) | T `test_3b_enregistrement_echec.py`, `test_3b_reception_navigateur.py` ; P `test_v1_3b_enregistrement_page.py` | [exécuté] |
| 3.4 | Origine contrôlée sur toutes les routes d'écriture (connexion comprise) | réussi (routes prises dans l'application) | T `test_3b_origine_ecritures.py`, `test_3a_csrf_relais.py` ; V | [exécuté] |
| 3.5 | CSRF du produit sur le relais PGDR | réussi | T `test_3a_csrf_relais.py` ; P `test_v1_3a_csrf_page.py` ; V | [exécuté] |
| 3.6 | Compteurs de connexion HMAC, `X-Forwarded-For` non cru | réussi | T `test_3a_throttle_hmac.py`, `test_3a_lancement_reel.py` | [exécuté] |
| 3.7 | Journaux sans fuite (gabarits de route, exception = classe) | réussi ; 0 VIN, plaque, mot de passe, identifiant, jeton, secret, trace | T `test_3a_lancement_reel.py` ; V ; examen des journaux des montages e2e | [exécuté] |
| 3.8 | Journaux conservés au redémarrage (défaut corrigé en 3B) | réussi | T `test_3b_arret_borne.py` | [exécuté] |
| 3.9 | Arrêt borné sous l'unité systemd (défaut corrigé en 3B) | réussi : 10 s avec une connexion TLS inactive (30 s avant) | T `test_3b_arret_borne.py` ; V | [exécuté] |
| 3.10 | Installation propre depuis les commits, hors ligne | réussi ; `pip check` sans erreur ; clones sans modification | V | [exécuté] |
| 3.11 | Migrations sur base temporaire, retour arrière 028 → 029 | réussi | V | [exécuté] |
| 3.12 | Démarrage, santé, HTTPS, `/api`, en-têtes, services internes non exposés | réussi | V | [exécuté] |
| 3.13 | Sauvegarde → restauration (base neuve) → résultats, provenance et droits conservés | réussi | V | [exécuté] |
| 3.14 | Purge sur données fictives ; sauvegardes intactes | réussi | V | [exécuté] |
| 3.15 | Bilan de conservation ; plaque et VIN dans CPL | documenté ; aucune durée décidée | guide §9, §9.1 | [documentation] |
| 3.15a | Politique explicite par catégorie, sans durée par défaut ni reprise de `VIR_RETENTION_DAYS` ; contrôle de préparation | réussi | T `test_conservation_purge.py` (politique, contrôle) | [exécuté] |
| 3.15b | Simulation sans politique : « rien ne serait supprimé » ; exécution refusée, rien écrit | réussi | T `test_conservation_purge.py` | [exécuté] |
| 3.15c | Purge des identifiants échus : résolutions et `vehicle_details` vidées (copies multiples, anciennes versions), marquées « non conservées », provenance, liens, dossiers, Premiers Constats et droits intacts ; trace sans valeur ; 2ᵉ exécution sans effet | réussi | T `test_conservation_purge.py` | [exécuté] |
| 3.15d | Erreur en cours de purge : lot annulé, arrêt propre, relance qui termine | réussi | T `test_conservation_purge.py` | [exécuté] |
| 3.15e | Artefacts `vir_resolution` : nouveaux enregistrés sans plaque ni VIN ; anciens expurgés à l'échéance par l'opération CPL REQ-B6-091 (trace sans valeur, intégrité « expurgé autorisé », artefact altéré refusé) | réussi (levée par CPL `253ff8f`) | guide §9.3 ; T `test_conservation_artefacts.py`, `test_conservation_integration.py` | [exécuté] |
| 3.15f | Médias par âge ; référence « no longer kept » ; pixels non vérifiés | réussi (âge) | T `test_conservation_purge.py` ; unitaire `ErrorBanner` | [exécuté] [non vérifiable] (pixels) |
| 3.15g | Journaux tournés échus supprimés, journaux actifs intacts | réussi | T `test_conservation_purge.py` | [exécuté] |
| 3.15h | Sauvegardes : manifeste, 0700/0400, sans clé ; seules les sauvegardes échues reconnues supprimées, le reste intact | réussi | T `test_conservation_sauvegardes.py` | [exécuté] |
| 3.15i | Restauration ancienne : verrou, démarrage refusé sans purge, sessions révoquées, identifiants échus vidés avant réouverture | réussi | T `test_conservation_sauvegardes.py` | [exécuté] |
| 3.15j | Navigateur : dossier après purge et après restauration (identification « no longer kept », résultats confirmés intacts, session antérieure refusée) | réussi | T `test_conservation_navigateur.py` | [exécuté] |
| 3.15k | Suppression d'un dossier échu et de ses données propres (opération CPL REQ-B5-116) ; compte, véhicule, autres dossiers, connaissances conservés ; dossier dans sa période inchangé ; reprise après erreur ; 2ᵉ exécution sans effet | réussi | T `test_conservation_dossiers.py` ; CPL `test_b5_case_deletion.py` | [exécuté] |
| 3.15l | Relais des parcours : dossier supprimé refusé aussitôt, PGDR non appelé, rien enregistré ; autre utilisateur refusé | réussi | T `test_conservation_dossiers.py` | [exécuté] |
| 3.15m | Purge intégrée : une simulation pour toutes les catégories ; ordre expurgation → dossiers → identifiants → médias → journaux ; refus sans politique | réussi | T `test_conservation_integration.py`, `test_conservation_purge.py` | [exécuté] |
| 3.15n | Sauvegarde prise après purge sans valeurs retirées ni dossier supprimé ; ancienne sauvegarde gardée jusqu'à son échéance | réussi | T `test_conservation_integration.py` | [exécuté] |
| 3.15o | Restauration d'une sauvegarde en 030 : verrou jusqu'aux migrations (031) et à la conservation ; sessions révoquées même sans politique ; sans politique, verrou et message | réussi | T `test_conservation_integration.py` | [exécuté] |
| 3.15p | Copies mises de côté : médias 0700 ; copie VIR reconnue par manifeste PI et nettoyée ; copie sans manifeste ou altérée signalée, jamais supprimée ; aucune copie PostgreSQL | réussi | T `test_conservation_integration.py` ; guide §9.5 | [exécuté] |
| 3.15q | Effacement physique (WAL, `VACUUM`, supports de l'hébergeur, anciennes sauvegardes) | non garanti, documenté | guide §9.6 | [non vérifiable] |
| 3.15r | Navigateur, montage réel : dossier conservé visible de son propriétaire avec son résultat ; dossier supprimé introuvable ; autre utilisateur refusé ; idem après restauration d'une sauvegarde ancienne puis purge | réussi | T `test_conservation_navigateur_dossiers.py` | [exécuté] |
| 3.16 | Durées de conservation (et point de départ des identifiants), activation réelle (fournisseurs, tri) | décisions du propriétaire, non prises | guide §9, §11 | [non vérifiable] |
