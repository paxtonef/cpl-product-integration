#!/usr/bin/env bash
# Purge : sessions web expirées (PI) et enregistrements VIR dont la conservation
# est échue. La durée de conservation VIR n'est PAS décidée : VIR_RETENTION_DAYS
# doit être fixé explicitement par le propriétaire (aucune valeur supposée ici).
# Les dossiers, résultats et médias CPL/PI ne sont pas purgés (aucune règle décidée).
set -euo pipefail
for name in PREFIX DATABASE_URL VIR_DATABASE_PATH VIR_DATA_ENCRYPTION_KEY VIR_RETENTION_DAYS; do
  if [ -z "${!name:-}" ]; then echo "Variable manquante : $name" >&2; exit 2; fi
done
"$PREFIX/venv/bin/python" -m product_integration.auth.cli purge-sessions
"$PREFIX/venv/bin/vir" purge
