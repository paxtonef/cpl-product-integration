# Raccordement VIR / PGDR / CPL — reprise avec VIR V1 (compte rendu du 2026-10-15)

Étiquettes : **[exécuté]** constaté par exécution pendant cette passe ; **[code]** lu dans le
code ; **[documentation]** lu dans un document ; **[non vérifiable]**.

Aucun appel fournisseur réel, aucune migration réelle, aucun push, aucune fusion. Toutes les
exécutions : clones locaux (`git clone --local`) hors dépôts, environnements Python temporaires,
PostgreSQL 16 jetable (bases fictives), secrets fictifs générés à la volée, réseau extérieur
bloqué par `sandbox-exec` (boucle locale seule autorisée).

## 1. Réponse

**Le raccordement de septembre a été retrouvé : oui.** Il est porté par ce dépôt
(`cpl-product-integration`, PI-01 à PI-06 puis blocs A, B1, B1.5, B2-K, Photo-First), pas par
VIR, PGDR ou CPL.

- Commits : PI-01 `1050d53` (2026-09-09) → PI-06 intégré `a1acce4` (2026-09-12, « FIRST
  OPERATIONAL VIR/PGDR PRODUCT ACHIEVED ») → blocs A/B1/B1.5 (2026-09-15) → B2-K
  (2026-09-17) → `fae3cba` (2026-09-23, passage VIR → PGDR Photo-First). [code]
- Preuves de réception : `docs/build/PI_0{1..6}_*CLOSURE_RECORD_v0.md`,
  `*_INDEPENDENT_VERIFICATION_v0.md` (PI-06 : 12/12 e2e navigateur, 136/136 backend). [documentation]
- Tests d'intégration : `tests/` (188 tests à `fae3cba`), e2e `frontend/tests/e2e/` (12). [code]

**Fonctionne aujourd'hui : oui, après trois corrections dans PI** (§5), avec les versions
actuelles de VIR, PGDR et CPL — sous la condition des changements CPL non commités (§4). [exécuté]

## 2. Architecture retrouvée

```
Frontend React (PI-06, frontend/) ──/api──▶ PI-05 API (product_integration.api.app)
   PI-04 orchestration ─┬─ PI-01 client VIR ──HTTP + X-VIR-Service-Token──▶ VIR (uvicorn vir.api.routes:app)
                        ├─ PI-02 handoff_mapper.map_resolution (VIR → PGDR VehicleIdentityContext)
                        ├─ PI-03 adaptateur de session PGDR (en processus : pgdr.session_controller)
                        └─ CPL (en processus : app.cpl.*, PostgreSQL)
   Photo-First : photo_intake.request_photo_first_intake ──HTTP + X-PGDR-Identity-Handoff-Token──▶ PGDR web
```

- **CPL** (« Common Product Layer ») porte réellement, dans ce montage : Contact, Asset, Case et
  ses transitions, RunnerExecution / RunnerArtifact (résultats VIR et rapports PGDR gouvernés),
  AssetIdentityResolution, `automotive.vehicle_details`, et la connaissance constructeur B2-K
  (`manufacturer_knowledge_*`, lue par `knowledge/repository_adapter.py`). [code]
- **PI** est la seule couche de composition ; VIR, PGDR et CPL ne s'importent pas entre eux
  (constat d'autonomie du 2026-10-15, reconduit). [exécuté]
- Rôle de `~/pi01-integration` : clone antérieur figé sur `pi-01-vf-01-repair-candidate`
  (`fddab0a`), ancêtre de `main` ici ; pas d'environnement propre. [code]

## 3. Versions

| | Septembre (réception PI-01…PI-06) | Septembre (dernier état, 2026-09-23) | Compatible aujourd'hui (cette passe) |
|---|---|---|---|
| VIR | `a342aba` | `a342aba` (main) | `a4c0172` (`vir-v1-finalisation`, 46 commits après) |
| PGDR | `0580b1a` | `33e7a0c` | `7b863c0` (`v1-premier-constat`) |
| CPL | `6181dab` | `3ccdf63` + changements non commités (migration 029) | `3ccdf63` + les mêmes changements (« tel quel ») |
| GGM | — | — | 1.0.0 canonique, SHA-256 `41459158…99a7` |
| PI | `a1acce4` | `fae3cba` | branche `pi-raccord-vir-v1` (§7) |

Sources : `docs/build/PI_0*_*.md` (empreintes VIR/PGDR/CPL), messages de commit. [documentation]
L'environnement `~/pi01-main/venv` d'origine utilise le GGM 1.2.0 non canonique ; cette passe
utilise 1.0.0, exigé par PGDR depuis `4549258`. [exécuté]

## 4. Changements CPL non commités : ils font partie du raccordement

Les 2 fichiers modifiés et la migration `029_owner_attested_unverified_freshness.py` non suivie
de `~/cpl` sont la correction « source-veracity » du 2026-09-23 (PI `b73c6c6`, PGDR `33e7a0c`).
Sans eux, la suite PI donne **16 échecs** (15 B2-K + passage Photo-First :
`CheckViolation mfr_knowledge_documents_freshness_chk`) ; avec eux, 0. [exécuté]
Ils ont été copiés dans une copie de travail, l'original n'a pas été touché ; tous les résultats
ci-dessous portent sur CPL « tel quel ».

## 5. Régressions constatées et corrigées (toutes dans PI)

Chaque correction a un test qui échouait avant et passe après (VIR actuel). [exécuté]

| # | Régression (cause, date) | Couche corrigée | Test : avant → après |
|---|---|---|---|
| 1 | VIR exige `X-VIR-Service-Token` sur toute l'API (`7075bea`, 9 oct.) : client PI sans jeton → 503 → 62 échecs | PI-01 `vir/client.py` (jeton `PI_VIR_SERVICE_TOKEN`, jamais dans un message d'erreur) | `test_vir_service_token.py` : erreur d'import / `test_vir_client.py` 6 échecs → 12/12 |
| 2 | VIR exige un pays d'immatriculation explicite, VIN compris, sans repli France (`9d625d2`, 9 oct.) : PI ne le transmettait pas pour un VIN et forçait « FR » pour une plaque | PI-05 `api/routes.py` (transmis tel que choisi, plus de défaut) ; PI-06 `Registration.tsx` (choix obligatoire, aucun pays présélectionné) | `test_vir_registration_country.py` 2 échecs → 4/4 ; `StartCaseForm.test.tsx` 4 échecs → 4/4 ; e2e 7 échecs → 12/12 |
| 3 | VIR refuse une réponse de clarification inapplicable (`VIR-ERR-016`, `6bdd958`) : PI-05 laissait remonter l'exception → **500** | PI-05 `api/routes.py` (erreur typée `VIR_TECHNICAL_FAILURE` 502 avec `vir_error_code`, rien d'enregistré) | `test_vir_clarification_refusal.py` exception non traitée → réussi |
| 4 | Confirmation conducteur (VIR V1) : une valeur confirmée seule remplit `vehicle_identity` ; le miroir PI perdait `method` et PGDR la recevait comme connue (promotion de fait) | PI-01 `vir/schemas.py` (conserve la provenance VIR V1, jamais les valeurs brutes fournisseur) ; PI-02 `handoff_mapper.map_resolution` (règle VIR `epistemic_status` : valeur confirmée seule → inconnue pour PGDR, ajoutée à `unresolved_fields`) | `test_pgdr_handoff_confirmation.py` 2 échecs → 5/5 |

Adaptations de tests au contrat actuel (sans assouplissement, assertions aussi précises) :
pays « FR » explicite dans les requêtes fictives ; codes d'erreur VIR actuels
(`VIR-ERR-011`/`VIR-ERR-014` au lieu de `VIR-ERR-001`) ; e2e B ne répond plus « unknown » comme
VIN (refusé à juste titre par VIR V1) et vérifie désormais qu'aucune erreur n'apparaît.

Point d'entrée de lancement (le lancement de septembre exigeait une entrée du fichier hosts et
VIR sur le port 80) : `PI_VIR_BASE_URL` (défaut inchangé, `test_deps_vir_base_url.py` 1 échec →
2/2) et `scripts/lancer_montage.sh`.

## 6. Passages de relais — sept changements de format VIR (`TRANSFERT_DIAGNOSTIC_VIR.md` §6)

Le consommateur réel n'est **pas** le transfert `GET …/handoff/diagnostic`
(`DiagnosticIdentityContext`) : PI-04 reconstruit la `VehicleIdentityResolution` depuis l'artefact
CPL et appelle `map_resolution` (`case_orchestration.py`, `photo_intake.py`) ;
`map_diagnostic_context` n'est appelé que par des tests. [code] Preuve d'exécution : sondage de la
chaîne réelle VIR (ASGI) → client et miroir PI → charge d'artefact → `map_resolution` → PGDR
`VehicleApplicabilityContext`, avec une confirmation conducteur fictive, et le test
`test_pgdr_handoff_confirmation.py`. [exécuté]

| Changement | Lu / ignoré / refusé par le consommateur réel | Preuve |
|---|---|---|
| `user_confirmation` (méthode de provenance) | **lu par PI-02** (après correction 4), pour retenir la valeur confirmée seule ; **non transmis** à PGDR (aucun champ de provenance dans `VehicleIdentityContext`) | sondage : méthodes `decode`, `user_confirmation` côté VIR ; avant correction : absentes du miroir |
| `user_confirmed_fields` | **ignoré** (conservé dans l'artefact CPL depuis la correction 4, lu par personne) | champ absent du miroir avant ; aucune lecture dans PI ni PGDR |
| `exact_engine_code_known` | **ignoré** (transfert non consommé) | présent dans le transfert, aucune lecture |
| clés `vehicle` (`engine_code`, `transmission_gears`, `drivetrain`) | transfert : **ignoré** ; mêmes valeurs via la résolution (`engine.engine_code`, `transmission.gears`, `drivetrain`) : **lues** par PGDR (`VehicleApplicabilityContext`), valeur confirmée seule retenue | sondage : « valeur » dans `VehicleApplicabilityContext` ; via `map_diagnostic_context` les clés plates `engine_code`/`transmission_gears` ne seraient pas lues |
| `vehicle_field_paths` | **ignoré** | aucune lecture |
| `divergent_evidence` | **ignoré** ; les contradictions passent par `resolution.contradictions` (chemins de champ, lus) | aucune lecture |
| `field_epistemic_status` | **ignoré** dans le transfert ; la même règle VIR (`epistemic_status`) est appliquée par PI-02 sur les preuves de la résolution | code `handoff_mapper._confirmation_only_fields` |

Aucun de ces champs n'est **refusé** (aucun rejet de validation). Statut : VIR plafonne à
`provisionally_resolved` une identité qui repose sur une confirmation ; le statut est transmis
tel quel. [exécuté] `model_year` est désormais conservé dans l'artefact mais n'est pas lu par
PGDR. [code]

Autres points des relais :
- Identifiants : pays d'immatriculation choisi par l'utilisateur, transmis à VIR. La
  `vehicle_identity` transmise à PGDR contient `identifiers` (VIN, plaque) — comportement de
  septembre, non modifié ; PGDR ne les reprend pas dans `VehicleApplicabilityContext`. [exécuté]
- Authentification : VIR par jeton de service (401 sans jeton) ; PGDR Photo-First par
  `X-PGDR-Identity-Handoff-Token` (403 avec un mauvais jeton) ; **PI-05 n'a aucune
  authentification** et accorde toutes les autorités CPL à chaque requête (`deps.py`, choix
  documenté de PI-05). [exécuté] [code]

## 7. Vision

- PGDR : aucun fournisseur vision câblé (`PhotoWiring` vide) ; le passage Photo-First en direct
  répond `photo_analysis_unavailable`. [exécuté]
- Contexte textuel : `VehicleApplicabilityContext` est une liste fermée sans plaque, VIN ni
  donnée de carte grise ; l'adaptateur autonome `~/pgdr-vision-adapter` refuse tout contexte
  (audit du 2026-10-15). [code] [exécuté]
- **Passage vers un fournisseur vision non implémenté : confidentialité de bout en bout non
  démontrée.** Le contenu des pixels (plaque ou VIN visibles sur la photo) : [non vérifiable].

## 8. Réception commune (montage actuel, base fictive neuve)

| Contrôle | Résultat |
|---|---|
| Suite PI complète contre le montage vivant | **207 passed, 0 failed, 0 skipped** [exécuté] |
| Frontend : `tsc -b --noEmit` / vitest / `vite build` | PASS / 19 passed / 54 modules [exécuté] |
| Parcours navigateur Playwright (A…K, vrais PI-05, VIR, PGDR, PostgreSQL) | **12/12, deux fois** [exécuté] |
| Photo-First PI → PGDR en direct | refus gouverné `photo_analysis_unavailable` ; mauvais jeton → 403 [exécuté] |
| Fournisseurs réels | aucun : VIR en mode `simulated`, réseau extérieur bloqué [exécuté] |
| Journaux (511 lignes) : jetons, VIN/plaque/nom fictifs, en-tête de jeton, traces d'exception | 0 [exécuté] |
| Autonomie des runners (audit du 2026-10-15, reconduit) | VIR 826 + 3 (boucle locale) ; CPL 228 ; aucun import croisé [exécuté] |
| PGDR complet, hors réseau, dépendances de build préparées (dépôt de roues local, `GGM_WHEEL_PATH`) | **911 passed, 0 skipped** (empaquetage 11/11) [exécuté] |
| Jeu de septembre (PI `fae3cba`, VIR `a342aba`, PGDR `33e7a0c`) | 174 passed ; 14 exigent un PI-05 vivant joignable seulement via l'entrée hosts de septembre [exécuté] |

## 9. Lancement du montage

```bash
python3.14 -m venv .venv-montage
.venv-montage/bin/pip install ~/ggm/release/ggm-1.0.0-py3-none-any.whl
.venv-montage/bin/pip install -e "<VIR>[dev]" -e <PGDR> -e "<CPL>[dev]" -e "<PI>[dev]"
source .venv-montage/bin/activate
# base PostgreSQL de CPL (migration jusqu'à 029, changements CPL inclus)
(cd <CPL> && DATABASE_URL=postgresql+psycopg2://… alembic -c alembic.ini upgrade head)
# services (variables : voir l'en-tête du script ; MONTAGE_DIR sans .env)
DATABASE_URL=… VIR_SERVICE_TOKEN=… VIR_DATA_ENCRYPTION_KEY=… VIR_DATABASE_PATH=… \
PGDR_IDENTITY_HANDOFF_TOKEN=… MONTAGE_DIR=… <PI>/scripts/lancer_montage.sh
# frontend
(cd <PI>/frontend && npm ci && npx vite --host 127.0.0.1 --port 5173)
```

Tests : `pytest tests` (PI, mêmes `DATABASE_URL` et `PI05_MEDIA_STORAGE_DIR` que le montage) ;
`npx playwright test` (frontend ; Vite démarré sur 127.0.0.1 — Vite 5 n'écoute que sur `::1`
par défaut sur ce poste).

## 10. Prérequis restant réellement nécessaires avant mise en ligne

1. **CPL** : le propriétaire commite les changements « source-veracity » (2 fichiers + migration
   029) ; migration de la base réelle jusqu'à 029.
2. **PI** : décision de fusion de `pi-raccord-vir-v1` ; PI-05 sans authentification ni
   autorisation par utilisateur — à ne pas exposer tel quel.
3. **Secrets** (gestionnaire de secrets) : `VIR_SERVICE_TOKEN` = `PI_VIR_SERVICE_TOKEN`,
   `VIR_DATA_ENCRYPTION_KEY`, `PGDR_IDENTITY_HANDOFF_TOKEN` ; adresse `PI_VIR_BASE_URL`.
4. **VIR** : mode `simulated` seul démontré ; fournisseurs réels soumis aux conditions de
   `docs/LIVRAISON_VIR_V1.md` §11 (contrats, `rgm.yaml`) ; durée de conservation à fixer.
5. **PGDR** : sessions en mémoire, un seul processus ; GGM 1.0.0 fourni hors PyPI.
6. **Vision** : aucun fournisseur raccordé (§7).
7. **Décision** : transmission des identifiants (VIN, plaque) dans `vehicle_identity` vers PGDR.
8. **Frontend** : la liste des pays (France seule) reflète le registre VIR actuel ; à mettre à
   jour si VIR active d'autres pays.
