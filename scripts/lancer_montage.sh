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
#   PI_LOGIN_THROTTLE_SECRET  secret HMAC des compteurs de connexion (32 caractères au moins) ;
#                             PI_LOGIN_THROTTLE_SECRET_PREVIOUS pendant un renouvellement
#   MONTAGE_DIR               dossier d'exécution et de journaux, sans .env
# Optionnelles : VIR_PROVIDER_MODE (défaut simulated), VIR_PORT (8001),
#   PGDR_PORT (8002), PI_PORT (8000), PI05_MEDIA_STORAGE_DIR (MONTAGE_DIR/media),
#   PI_PUBLIC_ORIGIN (origine exacte du produit, exigée de toute écriture envoyée par un
#   navigateur ; en développement derrière Vite : http://127.0.0.1:5173).
#
# Journaux : PI et PGDR sans journal d'accès d'uvicorn (--no-access-log, chemins et
# requêtes porteurs d'identifiants) ; chacun écrit un gabarit de route par requête.
# vir.log, pgdr.log et pi05.log (lignes d'audit comprises) sont complétés à chaque démarrage,
# jamais tronqués ; leur rotation et leur durée de conservation relèvent de l'exploitant.
#
# Mode production (PI_FRONTEND_DIST défini : frontend construit par
# deploy/installer.sh) : un seul point d'entrée public, HTTPS, servant le
# frontend et l'API sous /api ; VIR et PGDR restent sur la boucle locale.
#   PI_FRONTEND_DIST  dossier du frontend construit
#   PI_PUBLIC_HOST, PI_PUBLIC_PORT  adresse publique d'écoute (aucune valeur supposée)
#   PI_TLS_CERT, PI_TLS_KEY         certificat et clé TLS (fichiers lisibles du seul service)
#   PI_TRUSTED_PROXIES (facultative) adresses du seul proxy TLS placé devant PI : X-Forwarded-*
#                                   n'est cru que d'elles ; absente, aucun en-tête de proxy n'est cru.
# Le faux transport de tri de PGDR (PGDR_V1_TRI, PGDR_V1_ESSAI_TRI) et l'essai de
# développement (PGDR_V1_DEV_TRIAL) sont refusés en mode production.
# Un seul processus PI (sessions PGDR en mémoire, perdues au redémarrage).
set -euo pipefail
umask 077

for name in DATABASE_URL VIR_SERVICE_TOKEN VIR_DATA_ENCRYPTION_KEY VIR_DATABASE_PATH \
            PGDR_IDENTITY_HANDOFF_TOKEN PI_LOGIN_THROTTLE_SECRET MONTAGE_DIR; do
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
production=""
if [ -n "${PI_FRONTEND_DIST:-}" ]; then
  production=1
  for name in PI_PUBLIC_HOST PI_PUBLIC_PORT PI_TLS_CERT PI_TLS_KEY; do
    if [ -z "${!name:-}" ]; then
      echo "Variable manquante (mode production) : $name" >&2
      exit 2
    fi
  done
  if [ "${PI_COOKIE_SECURE:-1}" = "0" ]; then
    echo "PI_COOKIE_SECURE=0 interdit en mode production." >&2
    exit 2
  fi
  for name in PGDR_V1_TRI PGDR_V1_TRI_FAUX PGDR_V1_ESSAI_TRI PGDR_V1_DEV_TRIAL; do
    if [ -n "${!name:-}" ]; then
      echo "$name interdit en mode production (faux tri ou essai : jamais un composant de production)." >&2
      exit 2
    fi
  done
  if [ -n "${PI_TRUSTED_PROXIES:-}" ]; then
    proxy_flags=(--proxy-headers --forwarded-allow-ips "$PI_TRUSTED_PROXIES")
  else
    proxy_flags=(--no-proxy-headers)
  fi
fi

cd "$MONTAGE_DIR"
# Arrêt borné : un client qui laisse une connexion TLS inactive ouverte retiendrait l'arrêt 30 s (attente de
# sa fermeture TLS), au-delà du TimeoutStopSec=20 de l'unité ; chaque service s'arrête en 10 s au plus.
graceful=(--timeout-graceful-shutdown 10)
pids=()
trap 'kill "${pids[@]}" 2>/dev/null || true; wait 2>/dev/null || true' EXIT INT TERM

python -m uvicorn vir.api.routes:app --host 127.0.0.1 --port "$VIR_PORT" "${graceful[@]}" >> vir.log 2>&1 &
pids+=($!)
python -m uvicorn pgdr.web_app:app --host 127.0.0.1 --port "$PGDR_PORT" --no-access-log "${graceful[@]}" \
  >> pgdr.log 2>&1 &
pids+=($!)
if [ -n "$production" ]; then
  python -m uvicorn --factory product_integration.api.production:create_production_app \
    --host "$PI_PUBLIC_HOST" --port "$PI_PUBLIC_PORT" --workers 1 --no-server-header \
    --no-access-log "${graceful[@]}" "${proxy_flags[@]}" \
    --ssl-certfile "$PI_TLS_CERT" --ssl-keyfile "$PI_TLS_KEY" >> pi05.log 2>&1 &
  pi_health="https://127.0.0.1:${PI_PUBLIC_PORT}/health"
else
  python -m uvicorn product_integration.api.app:app --host 127.0.0.1 --port "$PI_PORT" --no-access-log \
    "${graceful[@]}" >> pi05.log 2>&1 &
  pi_health="http://127.0.0.1:${PI_PORT}/health"
fi
pids+=($!)

for url in "http://127.0.0.1:${VIR_PORT}/health" "http://127.0.0.1:${PGDR_PORT}/health" "$pi_health"; do
  ok=""
  for _ in $(seq 1 60); do
    # -k : sonde locale de santé seulement (certificat éventuellement auto-signé en essai)
    if curl -kfsS -o /dev/null "$url" 2>/dev/null; then ok=1; break; fi
    sleep 0.5
  done
  if [ -z "$ok" ]; then
    echo "Service non joignable : $url (voir les journaux dans $MONTAGE_DIR)" >&2
    exit 1
  fi
done
if [ -n "$production" ]; then
  echo "Montage prêt : https://${PI_PUBLIC_HOST}:${PI_PUBLIC_PORT}  VIR 127.0.0.1:${VIR_PORT} (${VIR_PROVIDER_MODE})  PGDR 127.0.0.1:${PGDR_PORT}"
else
  echo "Montage prêt : PI-05 http://127.0.0.1:${PI_PORT}  VIR :${VIR_PORT} (${VIR_PROVIDER_MODE})  PGDR :${PGDR_PORT}"
fi
# Si un service s'arrête, tout le montage s'arrête (code 1) : le superviseur
# (systemd, Restart=on-failure) relance l'ensemble. Compatible bash 3.2.
while :; do
  for pid in "${pids[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "Un service du montage s'est arrêté (voir les journaux dans $MONTAGE_DIR)." >&2
      exit 1
    fi
  done
  sleep 2
done
