#!/bin/bash
# Build Jarvis (the Mac app, installed as "Lucy"), sign it for this Mac and install it to ~/Applications.
# The app icon is the Telegram bot's profile picture (or jarvis/AppIcon.png if you put one there).
# Needs only the Xcode Command Line Tools (xcode-select --install), not the full Xcode.
#
#   JARVIS_SERVER=wss://<your-domain>/ws/jarvis JARVIS_TOKEN=<token> scripts/build_jarvis.sh
#
# The server URL and token are written once to ~/Library/Application Support/Jarvis/config.json
# (if not given, the token is read from .env). They are never baked into the app.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$HOME/Library/Caches/Jarvis-build"   # outside iCloud/git
NAME="Lucy"                                 # the app's name in Finder, the Dock and Settings
APP="$BUILD/$NAME.app"
DEST="$HOME/Applications/$NAME.app"
CONFIG_DIR="$HOME/Library/Application Support/Jarvis"

echo "→ Building"
swift build -c release --package-path "$ROOT/jarvis" --scratch-path "$BUILD"

echo "→ Packaging $NAME.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BUILD/release/Jarvis" "$APP/Contents/MacOS/$NAME"
cp "$ROOT/jarvis/Info.plist" "$APP/Contents/Info.plist"

echo "→ Making the icon"
PICTURE="$ROOT/jarvis/AppIcon.png"
if [ ! -f "$PICTURE" ]; then
  # Same face as in Telegram: download the bot's profile picture (token from the environment or .env).
  BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ROOT/.env" 2>/dev/null | cut -d= -f2- || true)}"
  PICTURE="$BUILD/avatar.jpg"
  rm -f "$PICTURE"
  if [ -n "$BOT_TOKEN" ]; then
    python3 - "$BOT_TOKEN" "$PICTURE" <<'PY' || true
import json, sys, urllib.request
token, out = sys.argv[1], sys.argv[2]
api = lambda method, query="": json.load(urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}{query}"))
bot = api("getMe")["result"]
photos = api("getUserProfilePhotos", f"?user_id={bot['id']}&limit=1")["result"]["photos"]
if photos:
    path = api("getFile", f"?file_id={photos[0][-1]['file_id']}")["result"]["file_path"]
    urllib.request.urlretrieve(f"https://api.telegram.org/file/bot{token}/{path}", out)
PY
  fi
fi
if [ -f "$PICTURE" ]; then
  rm -rf "$BUILD/$NAME.iconset"
  swift "$ROOT/jarvis/make_icon.swift" "$PICTURE" "$BUILD/$NAME.iconset"
  iconutil -c icns "$BUILD/$NAME.iconset" -o "$APP/Contents/Resources/$NAME.icns"
else
  echo "  (no picture: set a profile photo for the bot in @BotFather or add jarvis/AppIcon.png)"
fi

# Signed with a self-made certificate kept in its own keychain file (not your login keychain).
# The same certificate every time means macOS keeps Jarvis's permissions across rebuilds
# (an ad-hoc signature changes with every build and macOS asks again).
# To give the app to someone else, sign it with an Apple Developer ID and notarize it instead.
SIGN_DIR="$CONFIG_DIR/signing"
KEYCHAIN="$SIGN_DIR/jarvis-signing.keychain-db"
IDENTITY="Jarvis Local Signing"
mkdir -p "$SIGN_DIR" && chmod 700 "$SIGN_DIR"
if [ ! -f "$KEYCHAIN" ]; then
  echo "→ Creating a local signing certificate (one time)"
  openssl rand -hex 24 > "$SIGN_DIR/password" && chmod 600 "$SIGN_DIR/password"
  PASS="$(cat "$SIGN_DIR/password")"
  TMP="$(mktemp -d)"
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=$IDENTITY" \
    -keyout "$TMP/key.pem" -out "$TMP/cert.pem" \
    -addext "keyUsage=critical,digitalSignature" -addext "extendedKeyUsage=critical,codeSigning" 2>/dev/null
  openssl pkcs12 -export -legacy -inkey "$TMP/key.pem" -in "$TMP/cert.pem" -out "$TMP/id.p12" -passout "pass:$PASS" 2>/dev/null \
    || openssl pkcs12 -export -inkey "$TMP/key.pem" -in "$TMP/cert.pem" -out "$TMP/id.p12" -passout "pass:$PASS"
  OLD_KEYCHAINS=$(security list-keychains -d user | xargs)
  security create-keychain -p "$PASS" "$KEYCHAIN"
  security list-keychains -d user -s $OLD_KEYCHAINS   # keep it out of the normal keychain list
  security unlock-keychain -p "$PASS" "$KEYCHAIN"
  security import "$TMP/id.p12" -k "$KEYCHAIN" -P "$PASS" -T /usr/bin/codesign >/dev/null
  security set-key-partition-list -S apple-tool:,apple: -s -k "$PASS" "$KEYCHAIN" >/dev/null
  rm -rf "$TMP"
fi
security unlock-keychain -p "$(cat "$SIGN_DIR/password")" "$KEYCHAIN"
echo "→ Signing"
codesign --force --keychain "$KEYCHAIN" --sign "$IDENTITY" --identifier com.andrewrayne.jarvis "$APP"

echo "→ Writing config"
mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/config.json" ] || [ -n "${JARVIS_TOKEN:-}" ]; then
  TOKEN="${JARVIS_TOKEN:-$(grep -E '^JARVIS_TOKEN=' "$ROOT/.env" 2>/dev/null | cut -d= -f2- || true)}"
  SERVER="${JARVIS_SERVER:-}"
  if [ -z "$TOKEN" ] || [ -z "$SERVER" ]; then
    echo "Set JARVIS_SERVER (wss://<domain>/ws/jarvis) and JARVIS_TOKEN (or put it in .env)" >&2
    exit 1
  fi
  python3 -c 'import json,sys; print(json.dumps({"server": sys.argv[1], "token": sys.argv[2]}, indent=2))' \
    "$SERVER" "$TOKEN" > "$CONFIG_DIR/config.json"
  chmod 600 "$CONFIG_DIR/config.json"
fi

echo "→ Installing to $DEST"
pkill -x Jarvis 2>/dev/null || true   # older builds were called Jarvis
pkill -x "$NAME" 2>/dev/null || true
mkdir -p "$HOME/Applications"
rm -rf "$DEST" "$HOME/Applications/Jarvis.app"
cp -R "$APP" "$DEST"
open "$DEST"
touch "$DEST"   # so Finder and the Dock pick up the new icon
echo "✓ $NAME is running (look for the waveform icon in the menu bar)"
