#!/usr/bin/env bash
# Lance le montage existant VIR + PGDR + PI-05 sur la boucle locale.
#
# Prérequis : un environnement Python où sont installés VIR, PGDR (+ GGM 1.0.0),
# CPL (cpl-b2) et ce dépôt ; une base PostgreSQL déjà migrée par la chaîne CPL
# (alembic upgrade head) ; le frontend se lance à part (frontend/, npm run dev).
#
# Variables obligatoires (aucune valeur n'est affichée) :
#   DATABASE_URL              base PostgreSQL de CPL
#   VIR_SERVICE_TOKEN         jeton de l'API de service VIR (transmis à PI-05)
#   VIR_DATA_ENCRYPTION_KEY   clé de chiffrement du stockage VIR
#   VIR_DATABASE_PATH         fichier SQLite de VIR (chemin absolu)
#   PGDR_IDENTITY_HANDOFF_TOKEN  jeton du passage d'identité photo VIR -> PGDR
#   MONTAGE_DIR               dossier d'exécution et de journaux, sans .env
# Optionnelles : VIR_PROVIDER_MODE (défaut simulated), VIR_PORT (8001),
#   PGDR_PORT (8002), PI_PORT (8000), PI05_MEDIA_STORAGE_DIR (MONTAGE_DIR/media).
set -euo pipefail

for name in DATABASE_URL VIR_SERVICE_TOKEN VIR_DATA_ENCRYPTION_KEY VIR_DATABASE_PATH \
            PGDR_IDENTITY_HANDOFF_TOKEN MONTAGE_DIR; do
  if [ -z "${!name:-}" ]; then
    echo "Variable manquante : $name" >&2
    exit 2
  fi
done
if [ -e "$MONTAGE_DIR/.env" ]; then
  echo "MONTAGE_DIR ne doit pas contenir de .env (lu par VIR et CPL)." >&2
  exit 2
fi

VIR_PORT="${VIR_PORT:-8001}"
PGDR_PORT="${PGDR_PORT:-8002}"
PI_PORT="${PI_PORT:-8000}"
export VIR_PROVIDER_MODE="${VIR_PROVIDER_MODE:-simulated}"
export PI_VIR_BASE_URL="http://127.0.0.1:${VIR_PORT}"
export PI_VIR_SERVICE_TOKEN="$VIR_SERVICE_TOKEN"
export PI_PGDR_BASE_URL="http://127.0.0.1:${PGDR_PORT}"
export PI_PGDR_IDENTITY_HANDOFF_TOKEN="$PGDR_IDENTITY_HANDOFF_TOKEN"
export PI05_MEDIA_STORAGE_DIR="${PI05_MEDIA_STORAGE_DIR:-$MONTAGE_DIR/media}"

cd "$MONTAGE_DIR"
pids=()
trap 'kill "${pids[@]}" 2>/dev/null || true; wait 2>/dev/null || true' EXIT INT TERM

python -m uvicorn vir.api.routes:app --host 127.0.0.1 --port "$VIR_PORT" > vir.log 2>&1 &
pids+=($!)
python -m uvicorn pgdr.web_app:app --host 127.0.0.1 --port "$PGDR_PORT" > pgdr.log 2>&1 &
pids+=($!)
python -m uvicorn product_integration.api.app:app --host 127.0.0.1 --port "$PI_PORT" > pi05.log 2>&1 &
pids+=($!)

for url in "http://127.0.0.1:${VIR_PORT}/health" "http://127.0.0.1:${PGDR_PORT}/health" \
           "http://127.0.0.1:${PI_PORT}/openapi.json"; do
  ok=""
  for _ in $(seq 1 60); do
    if curl -fsS -o /dev/null "$url" 2>/dev/null; then ok=1; break; fi
    sleep 0.5
  done
  if [ -z "$ok" ]; then
    echo "Service non joignable : $url (voir les journaux dans $MONTAGE_DIR)" >&2
    exit 1
  fi
done
echo "Montage prêt : PI-05 http://127.0.0.1:${PI_PORT}  VIR :${VIR_PORT} (${VIR_PROVIDER_MODE})  PGDR :${PGDR_PORT}"
wait
