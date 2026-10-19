#!/usr/bin/env bash
# Sauvegarde cohérente : PostgreSQL (CPL + pi_auth), base VIR (sauvegarde protégée
# de VIR), médias PI. Destination : un dossier neuf en 0700, avec empreintes.
#   DEST=<dossier neuf> deploy/sauvegarder.sh
# Services arrêtés de préférence (sinon : pg_dump reste cohérent, VIR copie à chaud
# par sa propre commande, les médias peuvent manquer un envoi en cours).
set -euo pipefail
umask 077
for name in PREFIX DATABASE_URL VIR_DATABASE_PATH VIR_DATA_ENCRYPTION_KEY PI05_MEDIA_STORAGE_DIR DEST; do
  if [ -z "${!name:-}" ]; then echo "Variable manquante : $name" >&2; exit 2; fi
done
[ ! -e "$DEST" ] || { echo "DEST existe déjà" >&2; exit 2; }
mkdir -p "$DEST"
pg_url="${DATABASE_URL/+psycopg2/}"
pg_dump --format=custom --no-owner --file "$DEST/postgresql.dump" "$pg_url"
"$PREFIX/venv/bin/vir" backup "$DEST/vir.db" >/dev/null
tar -C "$PI05_MEDIA_STORAGE_DIR" -cf "$DEST/medias.tar" .
(cd "$DEST" && shasum -a 256 postgresql.dump vir.db medias.tar > SHA256SUMS)
cp "$PREFIX/COMPOSITION.installee" "$DEST/" 2>/dev/null || true
echo "Sauvegarde : $DEST"
