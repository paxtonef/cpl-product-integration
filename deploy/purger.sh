#!/usr/bin/env bash
# Purge de conservation. SIMULATION PAR DÉFAUT : nombres par catégorie, rien n'est modifié.
#   deploy/purger.sh               simulation de toutes les catégories (fonctionne sans politique :
#                                  « rien ne serait supprimé »), sauvegardes et copies mises de côté comprises
#   deploy/purger.sh --executer    exécution, dans l'ordre (guide §9.2) : artefacts vir_resolution échus
#                                  expurgés et dossiers échus supprimés (opérations CPL), plaque et VIN échus,
#                                  médias, journaux tournés (PI_CONSERVATION_*_JOURS) ; puis sessions web
#                                  expirées (PI) et enregistrements VIR échus (VIR_RETENTION_DAYS, propre à VIR).
# Aucune durée n'est supposée : l'exécution est refusée tant qu'une politique manque.
# Sauvegardes et copies de restauration : deploy/nettoyer_sauvegardes.sh (séparé).
set -euo pipefail
umask 077
for name in PREFIX DATABASE_URL; do
  if [ -z "${!name:-}" ]; then echo "Variable manquante : $name" >&2; exit 2; fi
done
py="$PREFIX/venv/bin/python"
if [ "${1:-}" != "--executer" ]; then
  "$py" -m product_integration.conservation.cli purge
  if [ -n "${VIR_RETENTION_DAYS:-}" ]; then
    echo "- VIR (VIR_RETENTION_DAYS) : purge propre à VIR, non simulée ici (VIR purge aussi à chaque écriture)"
  else
    echo "- VIR (VIR_RETENTION_DAYS) : non défini — aucune politique, rien ne serait supprimé"
  fi
  exit 0
fi
for name in VIR_DATABASE_PATH VIR_DATA_ENCRYPTION_KEY VIR_RETENTION_DAYS; do
  if [ -z "${!name:-}" ]; then echo "Variable manquante : $name — exécution refusée, rien n'est supprimé" >&2; exit 2; fi
done
"$py" -m product_integration.conservation.cli purge --executer
"$py" -m product_integration.auth.cli purge-sessions
"$PREFIX/venv/bin/vir" purge
