#!/usr/bin/env bash
# Installation reproductible du montage PI + VIR + PGDR + CPL dans $PREFIX,
# hors des dépôts sources (aucun build/ ni egg-info créé dans un dépôt d'origine).
#
#   PREFIX=/opt/cpl-produit VIR_SRC=<dépôt VIR> PGDR_SRC=<dépôt PGDR> CPL_SRC=<dépôt CPL> \
#   GGM_WHEEL=<chemin de ggm-1.0.0-py3-none-any.whl> deploy/installer.sh
#
# Sources : chemins ou URL git ; chaque composant est cloné puis fixé au commit
# de deploy/COMPOSITION.env (refus de toute autre révision). PI est cloné depuis
# le dépôt qui contient ce script, à sa révision courante (HEAD).
# Résultat : $PREFIX/venv (dépendances verrouillées), $PREFIX/src/<composant>,
# $PREFIX/frontend-dist (frontend construit), $PREFIX/COMPOSITION.installee.
# Réseau nécessaire : index PyPI et registre npm (dépendances), rien d'autre.
set -euo pipefail
umask 077

here="$(cd "$(dirname "$0")" && pwd)"
pi_repo="$(git -C "$here" rev-parse --show-toplevel)"
# shellcheck source=/dev/null
source "$here/COMPOSITION.env"
for name in PREFIX VIR_SRC PGDR_SRC CPL_SRC GGM_WHEEL; do
  if [ -z "${!name:-}" ]; then echo "Variable manquante : $name" >&2; exit 2; fi
done
PYTHON="${PYTHON:-python3.14}"
"$PYTHON" -c "import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)" \
  || { echo "Python >= $PYTHON_MIN requis ($PYTHON)" >&2; exit 2; }
echo "$GGM_WHEEL_SHA256  $GGM_WHEEL" | shasum -a 256 -c - >/dev/null \
  || { echo "Empreinte de la roue GGM incorrecte" >&2; exit 2; }
if [ -e "$PREFIX/src" ]; then echo "$PREFIX/src existe déjà : installer dans un PREFIX neuf" >&2; exit 2; fi

mkdir -p "$PREFIX/src"
fetch() {  # nom source commit
  git clone -q --no-hardlinks "$2" "$PREFIX/src/$1"
  git -C "$PREFIX/src/$1" checkout -q --detach "$3"
  local got; got="$(git -C "$PREFIX/src/$1" rev-parse HEAD)"
  [ "$got" = "$3" ] || { echo "$1 : révision $got, attendu $3" >&2; exit 1; }
}
fetch vir "$VIR_SRC" "$VIR_COMMIT"
fetch pgdr "$PGDR_SRC" "$PGDR_COMMIT"
fetch cpl "$CPL_SRC" "$CPL_COMMIT"
PI_COMMIT="$(git -C "$pi_repo" rev-parse HEAD)"
if [ -n "$(git -C "$pi_repo" status --porcelain -- src deploy frontend/src frontend/package-lock.json)" ]; then
  echo "Le dépôt PI a des changements non commités : seule une révision commitée s'installe" >&2; exit 2
fi
fetch pi "$pi_repo" "$PI_COMMIT"

"$PYTHON" -m venv "$PREFIX/venv"
pip="$PREFIX/venv/bin/pip"
"$pip" -q install --upgrade pip
"$pip" -q install --no-deps -r "$PREFIX/src/pi/deploy/requirements.lock"
# Les composants depuis des copies de build dans $PREFIX (jamais depuis les dépôts d'origine)
for c in vir pgdr cpl pi; do
  rsync -a --exclude .git "$PREFIX/src/$c/" "$PREFIX/build/$c/"
done
"$pip" -q install --no-deps "$GGM_WHEEL" "$PREFIX/build/vir" "$PREFIX/build/pgdr" "$PREFIX/build/cpl" "$PREFIX/build/pi"
"$pip" check

# Frontend construit pour la production (aucun serveur Vite à l'exécution)
rsync -a --exclude node_modules --exclude dist "$PREFIX/src/pi/frontend/" "$PREFIX/build/frontend/"
(cd "$PREFIX/build/frontend" && npm ci --no-audit --no-fund >/dev/null && npm run build >/dev/null)
rm -rf "$PREFIX/frontend-dist" && cp -R "$PREFIX/build/frontend/dist" "$PREFIX/frontend-dist"
chmod -R go-w "$PREFIX/frontend-dist"

cat > "$PREFIX/COMPOSITION.installee" <<COMPO
PI_COMMIT=$PI_COMMIT
VIR_COMMIT=$VIR_COMMIT
PGDR_COMMIT=$PGDR_COMMIT
CPL_COMMIT=$CPL_COMMIT
GGM_WHEEL_SHA256=$GGM_WHEEL_SHA256
PYTHON=$("$PREFIX/venv/bin/python" --version)
INSTALLED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
COMPO
echo "Installé dans $PREFIX :"
cat "$PREFIX/COMPOSITION.installee"
