#!/bin/bash
# Removes Obscura from this Mac. Lives in Obscura.app/Contents/Resources/; started by the app's "Uninstall…" button,
# by "Uninstall Obscura.app", or by hand:
#
#   uninstall.sh                     asks before doing anything
#   uninstall.sh --yes               no questions (the app already asked)
#   uninstall.sh --yes --remove-data also delete case files, exports, audit log, keys and settings
#
# Case data is only ever deleted with --remove-data, and only from a folder that really is an Obscura data folder.
set -u
YES=0; REMOVE=0; DATA=""; CONFIG=""; WAIT_PID=""; RES=""
ORIG_ARGS=("$@")
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) YES=1 ;;
    --remove-data) REMOVE=1 ;;
    --data-dir) DATA="$2"; shift ;;
    --config) CONFIG="$2"; shift ;;
    --wait-pid) WAIT_PID="$2"; shift ;;
    --resources) RES="$2"; shift ;;
  esac
  shift
done

if [ -z "$RES" ]; then
  # run from a temporary copy: this file is inside the app we are about to stop and delete
  RES="$(cd "$(dirname "$0")" && pwd)"
  TMP_COPY="$(mktemp -t obscura-uninstall).sh"
  cp "$0" "$TMP_COPY" && chmod +x "$TMP_COPY"
  exec /bin/bash "$TMP_COPY" ${ORIG_ARGS[@]+"${ORIG_ARGS[@]}"} --resources "$RES"
fi
trap 'rm -f "$0"' EXIT
APP="$(cd "$RES/../.." && pwd)"                     # …/Obscura.app
PARENT="$(dirname "$APP")"                          # …/Obscura (folder made by the installer) or /Applications
SUPPORT="$HOME/Library/Application Support/Obscura"
CONFIG="${CONFIG:-$SUPPORT/config.json}"
LOG="${TMPDIR:-/tmp}/obscura-uninstall.log"
exec >>"$LOG" 2>&1
echo "== $(date) uninstall app=$APP remove_data=$REMOVE"

ask() {  # ask "question" "button" -> 0 when the button was pressed
  /usr/bin/osascript -e "button returned of (display dialog \"$1\" buttons {\"Cancel\", \"$2\"} default button \"Cancel\" with title \"Uninstall Obscura\" with icon caution)" 2>/dev/null | grep -q "$2"
}

if [ "$YES" -eq 0 ]; then
  ask "Remove Obscura from this Mac? The program and its AI models will be deleted." "Uninstall" || exit 0
  if ask "Also permanently delete all case files, exports, the audit log and settings? Choose Keep to leave them (a reinstall will find them again)." "Delete everything"; then
    REMOVE=1
  fi
fi

# 1. stop Obscura (the app asked us to start; wait for it to quit, then make sure nothing from the bundle runs)
if [ -n "$WAIT_PID" ]; then
  for _ in $(seq 1 60); do kill -0 "$WAIT_PID" 2>/dev/null || break; sleep 0.5; done
fi
/usr/bin/pkill -TERM -f "$APP/Contents/" 2>/dev/null
sleep 1
/usr/bin/pkill -KILL -f "$APP/Contents/" 2>/dev/null

# 2. start-at-login item
[ -n "${OBSCURA_UNINSTALL_TEST:-}" ] || /bin/launchctl bootout "gui/$(id -u)/com.obscura.redaction" 2>/dev/null
rm -f "$HOME/Library/LaunchAgents/com.obscura.redaction.plist"

# 3. case data (only on request, only a real Obscura data folder)
if [ -z "$DATA" ] && [ -f "$CONFIG" ]; then
  DATA="$(/usr/bin/plutil -extract data_dir raw -o - "$CONFIG" 2>/dev/null)"
fi
DATA="${DATA:-$SUPPORT/data}"
if [ "$REMOVE" -eq 1 ]; then
  case "$DATA" in
    ""|"/"|"$HOME"|"$HOME/"|"/Users"|"/Applications") echo "refusing to delete '$DATA'";;
    *)
      if [ -f "$DATA/obscura.db" ] || [ -d "$DATA/keys" ] || [ -d "$DATA/blobs" ]; then
        rm -rf "$DATA/keys"        # keys first: whatever is left can no longer be decrypted
        rm -rf "$DATA"
        echo "deleted data $DATA"
      else
        echo "'$DATA' does not look like an Obscura data folder; left alone"
      fi;;
  esac
  rm -rf "$SUPPORT"
else
  rm -rf "$SUPPORT/models" "$SUPPORT/model-download.log"   # downloaded models go with the program
fi

# 4. the program (an installer-made "Obscura" folder goes as a whole)
TARGETS=("$APP")
if [ "$(basename "$PARENT")" = "Obscura" ]; then TARGETS=("$PARENT"); fi
if [ -d "$PARENT/Uninstall Obscura.app" ] && [ "${TARGETS[0]}" = "$APP" ]; then TARGETS+=("$PARENT/Uninstall Obscura.app"); fi
removed=1
for t in "${TARGETS[@]}"; do
  rm -rf "$t" 2>/dev/null || removed=0
  [ -e "$t" ] && removed=0
done
if [ "$removed" -eq 0 ]; then
  # installed for all users (/Applications): macOS asks for an administrator password
  quoted=""
  for t in "${TARGETS[@]}"; do quoted="$quoted '$(printf "%s" "$t" | sed "s/'/'\\\\''/g")'"; done
  /usr/bin/osascript -e "do shell script \"rm -rf $quoted; /usr/sbin/pkgutil --forget com.obscura.redaction >/dev/null 2>&1; true\" with administrator privileges" \
    || { /usr/bin/osascript -e 'display dialog "Obscura could not be removed (no administrator permission)." buttons {"OK"} with title "Uninstall Obscura"'; exit 1; }
fi
if [ -z "${OBSCURA_UNINSTALL_TEST:-}" ]; then
  /usr/sbin/pkgutil --forget com.obscura.redaction >/dev/null 2>&1
  /usr/sbin/pkgutil --volume "$HOME" --forget com.obscura.redaction >/dev/null 2>&1   # "install for me only"
fi

msg="Obscura has been removed."
[ "$REMOVE" -eq 0 ] && msg="$msg Your case files were kept in $DATA."
[ -n "${OBSCURA_UNINSTALL_TEST:-}" ] || /usr/bin/osascript -e "display notification \"$msg\" with title \"Obscura\"" 2>/dev/null
echo "done: $msg"
exit 0
