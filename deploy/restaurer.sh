#!/usr/bin/env bash
# Restauration d'une sauvegarde de deploy/sauvegarder.sh. SERVICES ARRÊTÉS.
#   SOURCE=<dossier de sauvegarde> deploy/restaurer.sh
# Remplace le contenu de la base PostgreSQL en place (objets sauvegardés ; aucune copie PostgreSQL n'est mise
# de côté : prendre une sauvegarde avant si l'état actuel doit être gardé), la base VIR (VIR copie l'actuelle
# à côté, 0600 ; ce script écrit près d'elle <copie>.MANIFESTE pour que deploy/nettoyer_sauvegardes.sh la
# reconnaisse) et les médias (dossier actuel mis de côté en 0700 avec un MANIFESTE, non supprimé).
# Avant toute réouverture : MONTAGE_DIR/RESTAURATION_A_PURGER est posé (scripts/lancer_montage.sh refuse
# de démarrer tant qu'il existe), puis deploy/finir_restauration.sh applique, dans l'ordre, migrations,
# révocation des sessions et conservation ; le verrou n'est retiré qu'en cas de succès complet.
# Le service n'est jamais relancé par ce script.
set -euo pipefail
umask 077
for name in PREFIX DATABASE_URL VIR_DATABASE_PATH VIR_DATA_ENCRYPTION_KEY PI05_MEDIA_STORAGE_DIR SOURCE \
            MONTAGE_DIR VIR_RETENTION_DAYS; do
  if [ -z "${!name:-}" ]; then echo "Variable manquante : $name" >&2; exit 2; fi
done
(cd "$SOURCE" && shasum -a 256 -c SHA256SUMS >/dev/null) || { echo "Empreintes de la sauvegarde incorrectes" >&2; exit 1; }
py="$PREFIX/venv/bin/python"
lock="$MONTAGE_DIR/RESTAURATION_A_PURGER"
mkdir -p "$MONTAGE_DIR"
printf 'restauration commencée le %s ; purge de conservation non encore appliquée\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$lock"
pg_url="${DATABASE_URL/+psycopg2/}"
pg_restore --clean --if-exists --no-owner --single-transaction --dbname "$pg_url" "$SOURCE/postgresql.dump"
vir_out="$("$PREFIX/venv/bin/vir" restore "$SOURCE/vir.db")"
vir_copy="$(printf '%s\n' "$vir_out" | sed -n 's/.*previous database copied to: //p' | head -1)"
if [ -n "$vir_copy" ] && [ "$vir_copy" != "none" ] && [ -f "$vir_copy" ]; then
  "$py" - "$vir_copy" <<'PY'
import datetime, hashlib, os, sys
path = sys.argv[1]
digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
created = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
with open(os.open(path + ".MANIFESTE", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400), "w") as fh:
    fh.write(f"format=pi-copie-vir-1\ncreee_le={created}\ncreee_par=deploy/restaurer.sh\n"
             f"fichier={os.path.basename(path)}\ntaille={os.path.getsize(path)}\nsha256={digest}\n")
PY
fi
"$PREFIX/venv/bin/vir" check-storage >/dev/null
if [ -d "$PI05_MEDIA_STORAGE_DIR" ]; then
  aside="$PI05_MEDIA_STORAGE_DIR.avant-restauration-$(date -u +%Y%m%dT%H%M%SZ)"
  mv "$PI05_MEDIA_STORAGE_DIR" "$aside"
  chmod 700 "$aside"
  printf 'format=pi-avant-restauration-1\ncreee_le=%s\ncreee_par=deploy/restaurer.sh\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$aside/MANIFESTE"
fi
mkdir -p "$PI05_MEDIA_STORAGE_DIR"
tar -C "$PI05_MEDIA_STORAGE_DIR" -xf "$SOURCE/medias.tar"
echo "Restauré depuis $SOURCE."
exec bash "$(dirname "$0")/finir_restauration.sh"
