# PI-06 Frontend Build Plan (HOW only — WHAT is already decided by PI_06_FRONTEND_JOURNEY_STRUCTURING_v0.md)

1. Framework: React 18 + Vite + TypeScript, client-side SPA (mandated by structuring §16).
2. Layout: frontend/ (new top-level dir in the same repo) — src/{api,routes,components,state}, tests/{unit,e2e}.
3. Browser routes (structuring §20): /, /register, /cases/:caseId, /cases/:caseId/clarification,
   /cases/:caseId/diagnostic, /cases/:caseId/result, /cases/:caseId/history.
4. Screens (structuring §3): Entry, Registration, VIRResolving(transient), VIRResult, VIRClarification,
   VIRRefusal, DiagnosticStart, DiagnosticQuestion, Result, CaseHistory — implemented as route components
   composing the canonical components below, state-driven per the navigation model (structuring §6).
5. State model: React Query-free — plain useState/useEffect + one small api/client fetch layer; no Redux/
   Zustand (structuring §17/§21 — backend is authoritative, no local cache of Case/execution truth).
6. API client boundary (structuring §18, PI-06-VF-01 accounted for): src/api/client.ts, one typed method per
   real PI-05 route — 11 methods total (createContact, getContact, registerVehicle, startCaseVIR,
   submitClarification, getCase, getCaseHistory, startDiagnostic, submitAnswer, getExecutionStatus,
   getArtifact) — the two contact methods the structuring's own summary omitted ARE included, per the build
   instruction's explicit §10 requirement.
7. Components (structuring §19, PI-06-VF-02 accounted for — actual list, 12 components): JourneyShell,
   RegistrationForm, VIRResolutionPanel, ClarificationForm, RefusalPanel, ComplaintForm, ConsentForm,
   DiagnosticQuestionForm, ExecutionStatusPanel, GaragePreparationReportView, CaseHistoryView, ErrorBanner.
8. Error normalization: src/api/errors.ts — maps real ProductAPIError bodies to a typed ApiError, per the
   structuring's §13 table.
9. Refresh/recovery: JourneyShell re-fetches GET /cases/:id + /cases/:id/history on every mount, applies the
   navigation model — never trusts route name alone (structuring §6/§14).
10. Tests: vitest for unit/component (navigation-model transforms, form validation), Playwright for the 11
    canonical acceptance journeys against real PI-05 (structuring §22).
11. Playwright/E2E setup: playwright.config.ts drives a real `uvicorn` PI-05 instance, real Postgres, real VIR
    (ASGI-mounted or subprocess), real PGDR — no mocked backend for definitive acceptance.
12. Anticipated files: ~25 source files (11 route/component files, api client, errors, types, App/main,
    config files) + Playwright spec files (one per acceptance journey area) + vitest spec files.
13. Sequence: API client + types -> routing shell + JourneyShell + navigation model -> registration/VIR half
    -> PGDR half -> history -> error UX + accessibility pass -> acceptance tests written last, against the
    completed build. (Matches structuring §27 exactly.)
