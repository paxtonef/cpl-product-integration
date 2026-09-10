# cpl-product-integration

Product-integration composition layer for CPL + VIR (+ PGDR, later PI units).
Not part of CPL, VIR, or PGDR — this repository exists solely to compose
their existing, independently-governed interfaces into an operational
product journey, per `CPL_VIR_PGDR_PRODUCT_INTEGRATION_REALITY_CHECK_v0.md`
(CPL governance @ 306f373).

This `main` branch is the canonical integration trunk. It did not exist
before PI-01's integration — created here as an orphan root, then merged
with the fully verified `pi-01-vf-01-repair-candidate` branch, preserving
that branch's complete history (build → initial verification → repair →
re-verification) rather than rewriting or squashing it.
