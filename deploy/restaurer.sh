#!/usr/bin/env bash
# Restauration d'une sauvegarde de deploy/sauvegarder.sh. SERVICES ARRÊTÉS.
#   SOURCE=<dossier de sauvegarde> deploy/restaurer.sh
# Remplace le contenu de la base PostgreSQL (objets sauvegardés), la base VIR
# (VIR met l'actuelle de côté) et les médias (dossier actuel renommé, non supprimé).
set -euo pipefail
umask 077
for name in PREFIX DATABASE_URL VIR_DATABASE_PATH VIR_DATA_ENCRYPTION_KEY PI05_MEDIA_STORAGE_DIR SOURCE; do
  if [ -z "${!name:-}" ]; then echo "Variable manquante : $name" >&2; exit 2; fi
done
(cd "$SOURCE" && shasum -a 256 -c SHA256SUMS >/dev/null) || { echo "Empreintes de la sauvegarde incorrectes" >&2; exit 1; }
pg_url="${DATABASE_URL/+psycopg2/}"
pg_restore --clean --if-exists --no-owner --single-transaction --dbname "$pg_url" "$SOURCE/postgresql.dump"
"$PREFIX/venv/bin/vir" restore "$SOURCE/vir.db" >/dev/null
"$PREFIX/venv/bin/vir" check-storage >/dev/null
if [ -d "$PI05_MEDIA_STORAGE_DIR" ]; then
  mv "$PI05_MEDIA_STORAGE_DIR" "$PI05_MEDIA_STORAGE_DIR.avant-restauration-$(date +%Y%m%d%H%M%S)"
fi
mkdir -p "$PI05_MEDIA_STORAGE_DIR"
tar -C "$PI05_MEDIA_STORAGE_DIR" -xf "$SOURCE/medias.tar"
echo "Restauration terminée depuis $SOURCE"
