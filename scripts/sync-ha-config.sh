#!/usr/bin/env bash
# Copy this repo's Home Assistant config to a Home Assistant OS device (e.g. Home Assistant Green).
#
# Copies only deploy/homeassistant/{custom_sentences,packages,custom_templates}; other files
# in /config are left alone, and secrets.yaml (your per-home settings) is never overwritten.
#
# Usage:
#   scripts/sync-ha-config.sh root@homeassistant.local     # via the "Terminal & SSH" add-on
#   scripts/sync-ha-config.sh /Volumes/config              # via the Samba add-on share (mounted)
# Options:
#   --dry-run      list what would be copied, change nothing
#   --add-secrets  append missing music_* settings to secrets.yaml (placeholders: edit them after)
#   --restart      (SSH only) check the config, then restart Home Assistant
#   -p PORT        SSH port (default 22, or $SSH_PORT)
set -euo pipefail

usage() { sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

TARGET="" DRY=0 ADD_SECRETS=0 RESTART=0 PORT="${SSH_PORT:-22}"
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --add-secrets) ADD_SECRETS=1 ;;
    --restart) RESTART=1 ;;
    -p) PORT="$2"; shift ;;
    -h|--help) usage 0 ;;
    -*) echo "unknown option: $1" >&2; usage 2 ;;
    *) [ -z "$TARGET" ] && TARGET="$1" || { echo "only one target allowed" >&2; usage 2; } ;;
  esac
  shift
done
[ -n "$TARGET" ] || usage 2

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO/deploy/homeassistant"
DIRS=(custom_sentences packages custom_templates)
SECRET_KEYS=(music_default_player music_allow_streaming music_speakers)
SECRETS_BLOCK='
# --- music-stream (docs/setup-green.md) - edit these to match your speakers ---
music_default_player: media_player.kitchen_speaker   # speaker used when no room is named
music_allow_streaming: true                          # false = never fall back to Spotify etc.
music_speakers:                                      # speakers the blocklist automation watches
  - media_player.kitchen_speaker
  - media_player.living_room_speaker
'

# (bash 3.2-compatible: macOS ships an old bash without mapfile)
FILES=()
while IFS= read -r f; do FILES+=("$f"); done < <(cd "$SRC" && find "${DIRS[@]}" -type f ! -name '.*' | sort)

if [[ "$TARGET" == *@* ]]; then
  MODE=ssh
  remote() { ssh -p "$PORT" "$TARGET" "$@"; }
  read_remote() { remote "cat /config/$1 2>/dev/null" || true; }
else
  MODE=local
  [ -d "$TARGET" ] || { echo "target directory not found: $TARGET (mount the Samba 'config' share first)" >&2; exit 1; }
  read_remote() { cat "$TARGET/$1" 2>/dev/null || true; }
fi

echo "Copying ${#FILES[@]} files to $TARGET ($MODE):"
printf '  %s\n' "${FILES[@]}"
if [ "$DRY" -eq 1 ]; then
  echo "(dry run: nothing copied)"
else
  export COPYFILE_DISABLE=1   # macOS: don't create ._ files on the share
  if [ "$MODE" = ssh ]; then
    tar -C "$SRC" -cf - "${FILES[@]}" | remote "tar -C /config -xf -"
  else
    tar -C "$SRC" -cf - "${FILES[@]}" | tar -C "$TARGET" -xf -
  fi
  echo "Copied."
fi

STATUS=0

# configuration.yaml must load the packages folder.
if ! read_remote configuration.yaml | grep -Eq '^[[:space:]]*packages:[[:space:]]*!include_dir_named[[:space:]]+packages'; then
  STATUS=1
  cat <<'EOF'

!! configuration.yaml doesn't load the packages folder yet. Add (merge into an existing
   "homeassistant:" section if there is one):

homeassistant:
  packages: !include_dir_named packages
EOF
fi

# secrets.yaml must define the per-home settings.
SECRETS="$(read_remote secrets.yaml)"
MISSING="" N_MISSING=0
for key in "${SECRET_KEYS[@]}"; do
  if ! grep -Eq "^${key}:" <<<"$SECRETS"; then MISSING="$MISSING $key"; N_MISSING=$((N_MISSING + 1)); fi
done
if [ "$N_MISSING" -gt 0 ]; then
  if [ "$ADD_SECRETS" -eq 1 ] && [ "$DRY" -eq 0 ] && [ "$N_MISSING" -eq "${#SECRET_KEYS[@]}" ]; then
    if [ "$MODE" = ssh ]; then
      printf '%s' "$SECRETS_BLOCK" | remote "cat >> /config/secrets.yaml"
    else
      printf '%s' "$SECRETS_BLOCK" >> "$TARGET/secrets.yaml"
    fi
    echo
    echo "Added placeholder music_* settings to secrets.yaml - edit them to your speakers' entity ids."
  else
    STATUS=1
    echo
    echo "!! secrets.yaml is missing:$MISSING"
    echo "   Add these lines (or re-run with --add-secrets when none are present), then edit them:"
    printf '%s\n' "$SECRETS_BLOCK"
  fi
fi

if [ "$RESTART" -eq 1 ] && [ "$DRY" -eq 0 ]; then
  if [ "$MODE" != ssh ]; then
    echo "--restart needs an SSH target; restart from Settings -> System -> Restart instead."
  elif [ "$STATUS" -ne 0 ]; then
    echo "Not restarting: fix the items above first."
  else
    echo "Checking configuration and restarting Home Assistant..."
    remote "ha core check && ha core restart"
  fi
elif [ "$DRY" -eq 0 ]; then
  echo
  echo "Next: restart Home Assistant (Settings -> System -> Restart), or re-run with --restart over SSH."
fi
exit "$STATUS"
