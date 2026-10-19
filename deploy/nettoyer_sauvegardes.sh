#!/usr/bin/env bash
# Sauvegardes échues. SIMULATION PAR DÉFAUT.
#   SAUVEGARDES_DIR=<dossier> deploy/nettoyer_sauvegardes.sh [--executer]
# Ne supprime que les dossiers créés et identifiés par les scripts de livraison :
# SAUVEGARDES_DIR/pi-sauvegarde-<horodatage>/ (deploy/sauvegarder.sh) et
# <PI05_MEDIA_STORAGE_DIR>.avant-restauration-<horodatage>/ (deploy/restaurer.sh), chacun avec son
# MANIFESTE et exactement les fichiers qu'il annonce ; tout autre contenu est conservé et signalé.
# Âge : date de création du manifeste ; durée : PI_CONSERVATION_SAUVEGARDES_JOURS (aucune supposée).
set -euo pipefail
umask 077
for name in PREFIX DATABASE_URL; do
  if [ -z "${!name:-}" ]; then echo "Variable manquante : $name" >&2; exit 2; fi
done
exec "$PREFIX/venv/bin/python" -m product_integration.conservation.cli sauvegardes ${1:+"$1"}
