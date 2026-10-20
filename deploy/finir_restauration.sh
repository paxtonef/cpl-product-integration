#!/usr/bin/env bash
# Fin de restauration (appelé par deploy/restaurer.sh ; relançable seul après correction). SERVICES ARRÊTÉS.
# Tant qu'il n'a pas abouti, MONTAGE_DIR/RESTAURATION_A_PURGER reste posé et scripts/lancer_montage.sh refuse
# de démarrer : aucun accès n'est rouvert. Dans l'ordre, chaque étape devant réussir :
#   1. migrations applicables (deploy/migrer.sh upgrade : CPL jusqu'à 031, puis schéma pi_auth) ;
#   2. révocation de toutes les sessions web restaurées, puis purge de conservation dans son ordre documenté :
#      expurgation des artefacts vir_resolution échus, suppression des dossiers échus, plaque et VIN échus,
#      médias, journaux (refusée sans politique explicite : le verrou reste) ;
#   3. sessions expirées et compteurs (purge-sessions), puis enregistrements VIR échus (vir purge).
# Le verrou n'est retiré qu'en cas de succès complet. Le service n'est jamais relancé par ce script.
set -euo pipefail
umask 077
for name in PREFIX DATABASE_URL VIR_DATABASE_PATH VIR_DATA_ENCRYPTION_KEY MONTAGE_DIR VIR_RETENTION_DAYS; do
  if [ -z "${!name:-}" ]; then echo "Variable manquante : $name" >&2; exit 2; fi
done
py="$PREFIX/venv/bin/python"
lock="$MONTAGE_DIR/RESTAURATION_A_PURGER"
[ -e "$lock" ] || { echo "Aucune restauration en attente ($lock absent) : rien à faire." >&2; exit 2; }
fail() {
  echo "Restauration faite, mais $1 : service fermé ($lock conservé). Corriger, puis relancer deploy/finir_restauration.sh." >&2
  exit 1
}
bash "$(dirname "$0")/migrer.sh" upgrade >/dev/null || fail "migrations NON appliquées"
"$py" -m product_integration.conservation.cli apres-restauration || fail "politique de conservation NON appliquée"
"$py" -m product_integration.auth.cli purge-sessions >/dev/null || fail "purge des sessions NON appliquée"
"$PREFIX/venv/bin/vir" purge >/dev/null || fail "purge VIR NON appliquée"
rm -f "$lock"
echo "Restauration terminée ; migrations et conservation appliquées, sessions révoquées."
echo "Le service n'est pas relancé : vérifier, puis le démarrer explicitement (systemctl start cpl-produit)."
