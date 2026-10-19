#!/usr/bin/env bash
# Restauration d'une sauvegarde de deploy/sauvegarder.sh. SERVICES ARRÊTÉS.
#   SOURCE=<dossier de sauvegarde> deploy/restaurer.sh
# Remplace le contenu de la base PostgreSQL (objets sauvegardés), la base VIR
# (VIR met l'actuelle de côté) et les médias (dossier actuel mis de côté avec un MANIFESTE, non supprimé).
# Avant toute réouverture : MONTAGE_DIR/RESTAURATION_A_PURGER est posé (scripts/lancer_montage.sh refuse
# de démarrer tant qu'il existe) ; après la restauration, toutes les sessions web sont révoquées et la
# politique de conservation est appliquée (plaque et VIN échus vidés, médias échus supprimés, VIR purgé) ;
# le verrou n'est retiré qu'en cas de succès. Le service n'est jamais relancé par ce script.
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
"$PREFIX/venv/bin/vir" restore "$SOURCE/vir.db" >/dev/null
"$PREFIX/venv/bin/vir" check-storage >/dev/null
if [ -d "$PI05_MEDIA_STORAGE_DIR" ]; then
  aside="$PI05_MEDIA_STORAGE_DIR.avant-restauration-$(date -u +%Y%m%dT%H%M%SZ)"
  mv "$PI05_MEDIA_STORAGE_DIR" "$aside"
  printf 'format=pi-avant-restauration-1\ncreee_le=%s\ncreee_par=deploy/restaurer.sh\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$aside/MANIFESTE"
fi
mkdir -p "$PI05_MEDIA_STORAGE_DIR"
tar -C "$PI05_MEDIA_STORAGE_DIR" -xf "$SOURCE/medias.tar"
# Une sauvegarde antérieure à la conservation n'a pas les tables de traçage : schéma PI mis à jour.
"$py" -m product_integration.auth.cli migrate >/dev/null
if ! "$py" -m product_integration.conservation.cli apres-restauration \
   || ! "$py" -m product_integration.auth.cli purge-sessions \
   || ! "$PREFIX/venv/bin/vir" purge; then
  echo "Restauration faite, mais politique de conservation NON appliquée : service fermé ($lock conservé)." >&2
  exit 1
fi
rm -f "$lock"
echo "Restauration terminée depuis $SOURCE ; conservation appliquée, sessions révoquées."
echo "Le service n'est pas relancé : vérifier, puis le démarrer explicitement (systemctl start cpl-produit)."
