#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$PROJECT_DIR/.venv"
TEMP_ROOT="$(mktemp -d "${TMPDIR:-/private/tmp}/codex-pet-usage.XXXXXX")"
TEMP_DIST="$TEMP_ROOT/dist"
TEMP_BUILD="$TEMP_ROOT/build"
export PYINSTALLER_CONFIG_DIR="$TEMP_ROOT/pyinstaller-config"
trap 'rm -rf "$TEMP_ROOT"' EXIT

if [[ ! -x "$VENV/bin/pyinstaller" ]]; then
  python3 -m venv "$VENV"
  "$VENV/bin/python" -m pip install -r "$PROJECT_DIR/requirements.txt"
fi
"$VENV/bin/pyinstaller" \
  --noconfirm \
  --clean \
  --workpath "$TEMP_BUILD" \
  --distpath "$TEMP_DIST" \
  "$PROJECT_DIR/CodexPetUsage.spec"

APP="$TEMP_DIST/CodexPetUsage.app"
xattr -cr "$APP"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

mkdir -p "$PROJECT_DIR/dist"
rm -rf "$PROJECT_DIR/dist/CodexPetUsage.app"
rm -f "$PROJECT_DIR/dist/CodexPetUsage.app.zip"
ditto --norsrc --noextattr --noqtn --noacl "$APP" "$PROJECT_DIR/dist/CodexPetUsage.app"
ditto -c -k --norsrc --noextattr --noqtn --noacl --keepParent \
  "$APP" "$PROJECT_DIR/dist/CodexPetUsage.app.zip"

if ! codesign --verify --deep --strict "$PROJECT_DIR/dist/CodexPetUsage.app"; then
  echo "Documents metadata invalidated the copied app; use the verified ZIP." >&2
  rm -rf "$PROJECT_DIR/dist/CodexPetUsage.app"
fi

echo "$PROJECT_DIR/dist/CodexPetUsage.app.zip"
