#!/usr/bin/env bash
# Sauvegarde cohérente : PostgreSQL (CPL + pi_auth), base VIR (sauvegarde protégée
# de VIR), médias PI. Destination : un dossier neuf en 0700, fichiers en lecture seule (0400),
# empreintes (SHA256SUMS) et MANIFESTE (format, date de création, fichiers) qui permet à
# deploy/nettoyer_sauvegardes.sh de la reconnaître ; aucune clé n'y est copiée.
#   SAUVEGARDES_DIR=<dossier> deploy/sauvegarder.sh   → SAUVEGARDES_DIR/pi-sauvegarde-<AAAAMMJJTHHMMSSZ>
#   DEST=<dossier neuf> deploy/sauvegarder.sh         → hors du nettoyage (jamais supprimée par les scripts)
# Services arrêtés de préférence (sinon : pg_dump reste cohérent, VIR copie à chaud
# par sa propre commande, les médias peuvent manquer un envoi en cours).
set -euo pipefail
umask 077
for name in PREFIX DATABASE_URL VIR_DATABASE_PATH VIR_DATA_ENCRYPTION_KEY PI05_MEDIA_STORAGE_DIR; do
  if [ -z "${!name:-}" ]; then echo "Variable manquante : $name" >&2; exit 2; fi
done
read -r created stamp < <("$PREFIX/venv/bin/python" -c 'import datetime as d; n = d.datetime.now(d.timezone.utc)
print(n.strftime("%Y-%m-%dT%H:%M:%SZ"), n.strftime("%Y%m%dT%H%M%SZ"))')
if [ -z "${DEST:-}" ]; then
  if [ -z "${SAUVEGARDES_DIR:-}" ]; then echo "Variable manquante : SAUVEGARDES_DIR (ou DEST)" >&2; exit 2; fi
  mkdir -p "$SAUVEGARDES_DIR"
  DEST="$SAUVEGARDES_DIR/pi-sauvegarde-$stamp"
fi
[ ! -e "$DEST" ] || { echo "DEST existe déjà" >&2; exit 2; }
mkdir -p "$DEST"
chmod 700 "$DEST"
pg_url="${DATABASE_URL/+psycopg2/}"
pg_dump --format=custom --no-owner --file "$DEST/postgresql.dump" "$pg_url"
"$PREFIX/venv/bin/vir" backup "$DEST/vir.db" >/dev/null
tar -C "$PI05_MEDIA_STORAGE_DIR" -cf "$DEST/medias.tar" .
(cd "$DEST" && shasum -a 256 postgresql.dump vir.db medias.tar > SHA256SUMS)
files="postgresql.dump vir.db medias.tar SHA256SUMS"
if [ -f "$PREFIX/COMPOSITION.installee" ]; then
  cp "$PREFIX/COMPOSITION.installee" "$DEST/"
  files="$files COMPOSITION.installee"
fi
printf 'format=pi-sauvegarde-1\ncreee_le=%s\ncreee_par=deploy/sauvegarder.sh\nfichiers=%s\n' "$created" "$files" \
  > "$DEST/MANIFESTE"
chmod 400 "$DEST"/*
echo "Sauvegarde : $DEST"
