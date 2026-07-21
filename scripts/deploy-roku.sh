#!/usr/bin/env bash
# Zip the app (manifest MUST be at zip root) and sideload via Roku dev installer.
set -euo pipefail
: "${ROKU_IP:?set ROKU_IP}" "${ROKU_DEV_PASS:?set ROKU_DEV_PASS}"

cd "$(dirname "$0")/../roku-app"
mkdir -p ../out
rm -f ../out/lunaria-roku.zip
zip -r ../out/lunaria-roku.zip . -x '.*'

curl -sS -u "rokudev:${ROKU_DEV_PASS}" --digest \
  -F "mysubmit=Install" \
  -F "archive=@../out/lunaria-roku.zip" \
  "http://${ROKU_IP}/plugin_install" | grep -oE 'Install (Success|Failure[^<]*)' || true
