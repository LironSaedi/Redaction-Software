#!/bin/bash
# Build Obscura for macOS (Apple Silicon): Obscura.app, "Uninstall Obscura.app" and a .pkg installer wizard.
#
#   packaging/macos/build_macos.sh                 program only: the setup assistant imports or downloads the models
#   packaging/macos/build_macos.sh --with-models   complete offline installer (adds ~4.6 GB of AI models)
#   options: --skip-pkg (just the .app)   --reuse-runtime (keep the Python runtime from the last build)
#
# Optional signing / notarisation (otherwise the build is ad-hoc signed; Gatekeeper then asks once, right-click → Open):
#   SIGN_APP="Developer ID Application: Firm (TEAMID)" SIGN_PKG="Developer ID Installer: Firm (TEAMID)" \
#   NOTARY_PROFILE=obscura-notary packaging/macos/build_macos.sh --with-models
#
# Needs: Xcode command line tools (clang, pkgbuild), uv, Homebrew tesseract. Run from anywhere.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
# build output can live on another drive: OBSCURA_BUILD_DIR / OBSCURA_DIST_DIR, or build/ and dist/ as links to it
for d in build dist; do
  if [ -L "$ROOT/$d" ] && [ ! -e "$ROOT/$d" ]; then
    echo "$d/ points to $(readlink "$ROOT/$d"), which is not available — connect that drive or set OBSCURA_BUILD_DIR / OBSCURA_DIST_DIR" >&2
    exit 1
  fi
done
BUILD="${OBSCURA_BUILD_DIR:-$ROOT/build}/macos"
DIST="${OBSCURA_DIST_DIR:-$ROOT/dist}"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/backend/obscura/__init__.py")"
BUNDLE_ID="com.obscura.redaction"
WITH_MODELS=0; SKIP_PKG=0; REUSE=0
for a in "$@"; do
  case "$a" in
    --with-models) WITH_MODELS=1 ;;
    --skip-pkg) SKIP_PKG=1 ;;
    --reuse-runtime) REUSE=1 ;;
    *) echo "unknown option $a" >&2; exit 2 ;;
  esac
done
[ "$(uname -m)" = "arm64" ] || { echo "build on an Apple Silicon Mac" >&2; exit 1; }
step() { printf '\n==> %s\n' "$*"; }

STAGE="$BUILD/root/Obscura"
APP="$STAGE/Obscura.app"
RES="$APP/Contents/Resources"
step "Obscura $VERSION for macOS (models included: $([ $WITH_MODELS = 1 ] && echo yes || echo no))"
if [ "$REUSE" = 1 ] && [ -x "$RES/runtime/bin/python3" ]; then
  find "$STAGE" -mindepth 1 -maxdepth 1 ! -name Obscura.app -exec rm -rf {} +
  find "$RES" -mindepth 1 -maxdepth 1 ! -name runtime -exec rm -rf {} +
  rm -rf "$APP/Contents/MacOS" "$APP/Contents/Info.plist" "$APP/Contents/_CodeSignature"
else
  rm -rf "$BUILD/root"
fi
mkdir -p "$RES" "$APP/Contents/MacOS" "$DIST"

# ---- 1. Python runtime (relocatable CPython from python-build-standalone, via uv) -------------------------------
if [ ! -x "$RES/runtime/bin/python3" ]; then
  step "Python runtime"
  uv python install 3.12 >/dev/null
  PYBIN="$(uv python find --managed-python 3.12)"
  PYHOME="$(cd "$(dirname "$(python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))' "$PYBIN")")/.." && pwd)"
  [ -f "$PYHOME/lib/libpython3.12.dylib" ] || { echo "need a python-build-standalone 3.12 (uv python install 3.12)" >&2; exit 1; }
  rsync -a "$PYHOME/" "$RES/runtime/"
  rm -f "$RES/runtime/lib/python3.12/EXTERNALLY-MANAGED"
  grep -v -E '^(pytest|faker)==' "$ROOT/backend/requirements.txt" > "$BUILD/requirements-runtime.txt"
  step "Python packages (from the uv cache when possible)"
  # (uv splits an --excludes path at spaces, so it is passed relative to the build folder)
  cp "$ROOT/backend/requirements-exclude.txt" "$BUILD/requirements-exclude.txt"
  (cd "$BUILD" && uv pip install --python "$RES/runtime/bin/python3" --compile-bytecode -q \
    -r requirements-runtime.txt --excludes requirements-exclude.txt)
  step "spaCy transformer model"
  VENV_SITE="$ROOT/backend/.venv/lib/python3.12/site-packages"
  if [ -d "$VENV_SITE/en_core_web_trf" ]; then
    cp -R "$VENV_SITE/en_core_web_trf" "$VENV_SITE"/en_core_web_trf-*.dist-info "$RES/runtime/lib/python3.12/site-packages/"
  else
    uv pip install --python "$RES/runtime/bin/python3" -q \
      "https://github.com/explosion/spacy-models/releases/download/en_core_web_trf-3.8.0/en_core_web_trf-3.8.0-py3-none-any.whl"
  fi
  rm -rf "$RES/runtime/share/man" "$RES/runtime/lib/python3.12/test" "$RES/runtime/lib/python3.12/idlelib"
fi
"$RES/runtime/bin/python3" -c "import fastapi, torch, spacy, gliner, fitz, presidio_analyzer, en_core_web_trf, tkinter" \
  || { echo "runtime is incomplete" >&2; exit 1; }

# ---- 2. Obscura itself -------------------------------------------------------------------------------------------
step "application files"
mkdir -p "$RES/app/scripts"
rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' "$ROOT/backend/obscura/" "$RES/app/obscura/"
cp "$ROOT/backend/scripts/download_models.py" "$ROOT/backend/scripts/make_cert.sh" "$RES/app/scripts/"
cp "$ROOT/backend/obscura_launch.pyw" "$RES/app/"
[ -f "$ROOT/frontend/dist/index.html" ] || (cd "$ROOT/frontend" && npm run build)
rsync -a --delete "$ROOT/frontend/dist/" "$RES/app/frontend/"
"$RES/runtime/bin/python3" -m compileall -q "$RES/app/obscura"
cp "$HERE/uninstall.sh" "$RES/uninstall.sh"
chmod +x "$RES/uninstall.sh"

step "OCR engine (Tesseract)"
"$HERE/bundle_tesseract.sh" "$RES/tesseract"

if [ "$WITH_MODELS" = 1 ]; then
  step "AI models"
  mkdir -p "$RES/models"
  for part in gliner/nvidia-gliner-pii vision whisper/medium.en whisper/small.en whisper/small translate/m2m100_418m speaker; do
    [ -d "$ROOT/backend/models/$part" ] || { echo "missing model $part — run backend/scripts/download_models.py" >&2; exit 1; }
    mkdir -p "$RES/models/$(dirname "$part")"
    rsync -a "$ROOT/backend/models/$part" "$RES/models/$(dirname "$part")/"
  done
fi

step "licences"
mkdir -p "$RES/licenses"
find "$RES/runtime/lib/python3.12/site-packages" -maxdepth 3 -type f -path '*.dist-info/*' \
  \( -iname 'LICEN[CS]E*' -o -iname 'COPYING*' -o -iname 'NOTICE*' -o -path '*.dist-info/licenses/*' \) \
  | while read -r f; do
      pkg="$(echo "$f" | sed -E 's|.*/site-packages/([^/]+)\.dist-info/.*|\1|')"
      cp "$f" "$RES/licenses/$pkg-$(basename "$f")"
    done
cp "$RES/runtime/lib/python3.12/LICENSE.txt" "$RES/licenses/Python-LICENSE.txt" 2>/dev/null || true

# ---- 3. bundle: icon, launcher, Info.plist ------------------------------------------------------------------------
step "app bundle"
"$RES/runtime/bin/python3" "$ROOT/packaging/common/make_icons.py" "$BUILD/icons" >/dev/null
cp "$BUILD/icons/Obscura.icns" "$RES/Obscura.icns"
LIBPY_ID="$(otool -D "$RES/runtime/lib/libpython3.12.dylib" | tail -1)"
clang -O2 -arch arm64 -mmacosx-version-min=12.0 -Wno-unused-command-line-argument \
  -I "$RES/runtime/include/python3.12" "$HERE/launcher.c" -L "$RES/runtime/lib" -lpython3.12 \
  -o "$APP/Contents/MacOS/Obscura"
install_name_tool -change "$LIBPY_ID" "@executable_path/../Resources/runtime/lib/libpython3.12.dylib" "$APP/Contents/MacOS/Obscura"
plist() {  # plist EXEC ID NAME DISPLAY OUT
  sed -e "s|@EXEC@|$1|" -e "s|@BUNDLE_ID@|$2|" -e "s|@NAME@|$3|" -e "s|@DISPLAY@|$4|" -e "s|@VERSION@|$VERSION|g" \
    "$HERE/Info.plist.in" > "$5"
}
plist Obscura "$BUNDLE_ID" Obscura "Obscura Redaction Studio" "$APP/Contents/Info.plist"

# "Uninstall Obscura.app" next to the app
UN="$STAGE/Uninstall Obscura.app"
mkdir -p "$UN/Contents/MacOS" "$UN/Contents/Resources"
cat > "$UN/Contents/MacOS/Uninstall" <<'SH'
#!/bin/bash
here="$(cd "$(dirname "$0")" && pwd)"
exec /bin/bash "$here/../../../Obscura.app/Contents/Resources/uninstall.sh"
SH
chmod +x "$UN/Contents/MacOS/Uninstall"
cp "$BUILD/icons/Obscura.icns" "$UN/Contents/Resources/Obscura.icns"
plist Uninstall "$BUNDLE_ID.uninstall" "Uninstall Obscura" "Uninstall Obscura" "$UN/Contents/Info.plist"

# ---- 4. signing -----------------------------------------------------------------------------------------------------
step "code signing ($([ -n "${SIGN_APP:-}" ] && echo "$SIGN_APP" || echo ad-hoc))"
if [ -n "${SIGN_APP:-}" ]; then
  # every Mach-O file inside the bundle, innermost first, with the hardened runtime
  find "$RES" -type f \( -name '*.so' -o -name '*.dylib' -o -perm -u+x \) -print0 | while IFS= read -r -d '' f; do
    if file -b "$f" | grep -q 'Mach-O'; then
      codesign --force --timestamp --options runtime --entitlements "$HERE/entitlements.plist" --sign "$SIGN_APP" "$f"
    fi
  done
  codesign --force --timestamp --options runtime --entitlements "$HERE/entitlements.plist" --sign "$SIGN_APP" "$APP"
  codesign --force --timestamp --options runtime --sign "$SIGN_APP" "$UN"
else
  codesign --force --sign - "$APP/Contents/MacOS/Obscura"
  codesign --force --sign - "$APP" 2>/dev/null || codesign --force --deep --sign - "$APP"
  codesign --force --sign - "$UN"
fi
codesign --verify --strict "$APP" && echo "signature ok"

APP_SIZE="$(du -sh "$APP" | cut -f1)"
echo "Obscura.app: $APP_SIZE"
[ "$SKIP_PKG" = 1 ] && exit 0

# ---- 5. installer package (the macOS Installer wizard) ------------------------------------------------------------
step "installer package"
SUFFIX="$([ $WITH_MODELS = 1 ] && echo "-full" || echo "")"
OUT="$DIST/Obscura-$VERSION-macOS$SUFFIX.pkg"
pkgbuild --analyze --root "$BUILD/root" "$BUILD/component.plist" >/dev/null
n=$(/usr/libexec/PlistBuddy -c "Print" "$BUILD/component.plist" | grep -c "BundleIsRelocatable" || true)
for ((i = 0; i < n; i++)); do
  /usr/libexec/PlistBuddy -c "Set :$i:BundleIsRelocatable false" "$BUILD/component.plist"
done
pkgbuild --root "$BUILD/root" --component-plist "$BUILD/component.plist" --install-location /Applications \
  --identifier "$BUNDLE_ID" --version "$VERSION" --scripts "$HERE/pkg/scripts" "$BUILD/obscura-app.pkg"
rm -rf "$BUILD/resources" && cp -R "$HERE/pkg/resources" "$BUILD/resources"
"$RES/runtime/bin/python3" - "$BUILD/icons/obscura.png" "$BUILD/resources/background.png" <<'PY'
import sys
from PIL import Image
icon = Image.open(sys.argv[1]).resize((150, 150), Image.LANCZOS)
bg = Image.new("RGBA", (620, 418), (0, 0, 0, 0))
icon.putalpha(icon.getchannel("A").point(lambda a: int(a * 0.85)))
bg.paste(icon, (22, 418 - 150 - 22), icon)
bg.save(sys.argv[2])
PY
sed "s|@VERSION@|$VERSION|" "$HERE/pkg/distribution.xml" > "$BUILD/distribution.xml"
productbuild --distribution "$BUILD/distribution.xml" --resources "$BUILD/resources" --package-path "$BUILD" \
  ${SIGN_PKG:+--sign "$SIGN_PKG"} "$OUT"
if [ -n "${NOTARY_PROFILE:-}" ]; then
  step "notarisation"
  xcrun notarytool submit "$OUT" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$OUT"
fi
step "done"
ls -lh "$OUT"
shasum -a 256 "$OUT"
