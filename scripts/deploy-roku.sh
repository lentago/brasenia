#!/usr/bin/env bash
# Zip the app (manifest MUST be at zip root) and sideload via Roku dev installer
# to every screen in ROKU_IP (one address, or several separated by spaces; the
# screens share one dev password). Exits non-zero if any screen did not install.
set -euo pipefail
: "${ROKU_IP:?set ROKU_IP}" "${ROKU_DEV_PASS:?set ROKU_DEV_PASS}"
read -ra screens <<< "$ROKU_IP"

cd "$(dirname "$0")/../roku-app"
mkdir -p ../out
rm -f ../out/brasenia-roku.zip
zip -r ../out/brasenia-roku.zip . -x '.*'

failed=0
for ip in "${screens[@]}"; do
  # The installer answers "Identical to previous version" when the build is
  # already there; that is a success too.
  result=$(curl -sS -u "rokudev:${ROKU_DEV_PASS}" --digest \
    -F "mysubmit=Install" \
    -F "archive=@../out/brasenia-roku.zip" \
    "http://${ip}/plugin_install" \
    | grep -oE 'Install (Success|Failure[^<]*)|Identical to previous version' | head -1) || true
  echo "${ip}: ${result:-no install result}"
  case "$result" in
    "Install Success"|"Identical to previous version") ;;
    *) failed=1 ;;
  esac
done
exit "$failed"
