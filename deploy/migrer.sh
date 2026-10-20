#!/usr/bin/env bash
# Migrations du montage (base PostgreSQL de CPL + schéma pi_auth de PI).
#   deploy/migrer.sh upgrade            CPL jusqu'à head (030), puis pi_auth
#   deploy/migrer.sh downgrade <rev>    pi_auth supprimé (comptes et sessions perdus),
#                                       puis CPL redescendu à <rev> (ex. 028)
# Toujours précédé d'une sauvegarde (deploy/sauvegarder.sh). Variables : PREFIX, DATABASE_URL.
set -euo pipefail
for name in PREFIX DATABASE_URL; do
  if [ -z "${!name:-}" ]; then echo "Variable manquante : $name" >&2; exit 2; fi
done
py="$PREFIX/venv/bin/python"
cpl="$PREFIX/src/cpl"
alembic() { (cd "$cpl" && "$PREFIX/venv/bin/alembic" -c alembic.ini "$@"); }

case "${1:-}" in
  upgrade)
    "$py" - <<'PY'
from sqlalchemy import text
from app.db.engine import engine
with engine.begin() as conn:
    conn.execute(text("CREATE SCHEMA IF NOT EXISTS cpl"))
    conn.execute(text("CREATE SCHEMA IF NOT EXISTS automotive"))
PY
    alembic upgrade head
    "$py" -m product_integration.auth.cli migrate
    ;;
  downgrade)
    rev="${2:?révision CPL cible requise, ex. 028}"
    "$py" -m product_integration.auth.cli downgrade --confirm-drop-pi-auth
    alembic downgrade "$rev"
    ;;
  *) echo "usage : $0 upgrade | downgrade <révision CPL>" >&2; exit 2 ;;
esac
alembic current 2>/dev/null | tail -1
