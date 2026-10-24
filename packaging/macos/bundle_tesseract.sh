#!/bin/bash
# Copy Homebrew's Tesseract (and every non-system library it needs) into DEST so the app runs on Macs without
# Homebrew. Library paths are rewritten to @loader_path and everything is re-signed (ad hoc unless SIGN_ID is set).
#
#   bundle_tesseract.sh DEST            e.g. …/Obscura.app/Contents/Resources/tesseract
set -euo pipefail
DEST="$1"
BREW_TESS="$(brew --prefix tesseract)"
mkdir -p "$DEST/bin" "$DEST/lib" "$DEST/share/tessdata"
cp -L "$BREW_TESS/bin/tesseract" "$DEST/bin/tesseract"
chmod u+w "$DEST/bin/tesseract"
for f in eng.traineddata osd.traineddata; do cp -L "$BREW_TESS/share/tessdata/$f" "$DEST/share/tessdata/"; done
cp -R "$BREW_TESS/share/tessdata/configs" "$DEST/share/tessdata/" 2>/dev/null || true

is_system() { case "$1" in /usr/lib/*|/System/*) return 0;; *) return 1;; esac; }

# where an "@rpath/NAME" / "@loader_path/NAME" dependency of SRC really lives
resolve() {  # resolve DEP SRC
  local dep="$1" src="$2" name dir r
  name="$(basename "$dep")"; dir="$(dirname "$(cd "$(dirname "$src")" && pwd -P)/$(basename "$src")")"
  case "$dep" in
    @loader_path/*|@executable_path/*) [ -e "$dir/${dep#*/}" ] && { echo "$dir/${dep#*/}"; return; } ;;
    @rpath/*)
      [ -e "$dir/$name" ] && { echo "$dir/$name"; return; }
      while read -r r; do
        r="${r/@loader_path/$dir}"
        [ -e "$r/$name" ] && { echo "$r/$name"; return; }
      done < <(otool -l "$src" | awk '/LC_RPATH/{getline; getline; print $2}') ;;
    *) [ -e "$dep" ] && { echo "$dep"; return; } ;;
  esac
  echo ""
}

# breadth-first over the dependency graph; queue items are "copy|original"
queue=("$DEST/bin/tesseract|$(cd "$BREW_TESS/bin" && pwd -P)/$(basename "$(readlink "$BREW_TESS/bin/tesseract" || echo tesseract)")")
[ -e "${queue[0]#*|}" ] || queue=("$DEST/bin/tesseract|$(python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))' "$BREW_TESS/bin/tesseract")")
seen=" "
while [ ${#queue[@]} -gt 0 ]; do
  item="${queue[0]}"; queue=("${queue[@]:1}")
  bin="${item%%|*}"; src="${item#*|}"
  while read -r dep; do
    is_system "$dep" && continue
    name="$(basename "$dep")"
    real="$(resolve "$dep" "$src")"
    if [ -z "$real" ]; then echo "bundle_tesseract: cannot find $dep (needed by $src)" >&2; exit 1; fi
    real="$(python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))' "$real")"
    if [ "$bin" = "$DEST/bin/tesseract" ]; then new="@loader_path/../lib/$name"; else new="@loader_path/$name"; fi
    install_name_tool -change "$dep" "$new" "$bin" 2>/dev/null
    if [[ "$seen" != *" $name "* ]]; then
      seen="$seen$name "
      cp -L "$real" "$DEST/lib/$name"
      chmod u+w "$DEST/lib/$name"
      install_name_tool -id "@loader_path/$name" "$DEST/lib/$name" 2>/dev/null
      queue+=("$DEST/lib/$name|$real")
    fi
  done < <(otool -L "$bin" | tail -n +2 | awk '{print $1}' | grep -v "^$(otool -D "$bin" | tail -n +2)$" )
done

for f in "$DEST/lib/"*.dylib "$DEST/bin/tesseract"; do
  codesign --force --sign "${SIGN_ID:--}" ${SIGN_ID:+--options runtime --timestamp} "$f" >/dev/null 2>&1
done

# prove it: no Homebrew paths left, and it runs with a clean environment
if otool -L "$DEST/bin/tesseract" "$DEST/lib/"*.dylib | grep -E "/opt/homebrew|/usr/local/(opt|Cellar)"; then
  echo "bundle_tesseract: Homebrew paths remain" >&2; exit 1
fi
env -i TESSDATA_PREFIX="$DEST/share/tessdata" "$DEST/bin/tesseract" --list-langs >/dev/null
echo "tesseract bundled: $(du -sh "$DEST" | cut -f1)"
