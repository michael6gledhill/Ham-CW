#!/usr/bin/env bash
# Test all ham-cw Rust API endpoints via curl
# Usage: ./test-api.sh [host]
#   e.g. ./test-api.sh 192.168.3.140
#        ./test-api.sh localhost

HOST="${1:-192.168.3.140}"
BASE="http://${HOST}"

pass=0; fail=0
check() {
  local code=$?
  if [ $code -eq 0 ]; then ((pass++)); echo " -> OK"
  else ((fail++)); echo " -> FAIL (exit $code)"; fi
}

echo "=== ham-cw API test — ${BASE} ==="
echo ""

echo "--- GET / (index page) ---"
curl -s -o /dev/null -w "%{http_code}" "${BASE}/" | grep -q 200; check

echo "--- GET /settings ---"
curl -s "${BASE}/settings" | head -c 200; echo; check

echo "--- POST /settings (set freq=750, wpm=25) ---"
curl -s -X POST "${BASE}/settings" \
  -H "Content-Type: application/json" \
  -d '{"frequency":750,"wpm":25}'; echo; check

echo "--- GET /settings (verify update) ---"
curl -s "${BASE}/settings" | head -c 200; echo; check

echo "--- POST /save-settings ---"
curl -s -X POST "${BASE}/save-settings"; echo; check

echo "--- GET /gpio-status ---"
curl -s "${BASE}/gpio-status"; echo; check

echo "--- POST /api/adjust (freq +10) ---"
curl -s -X POST "${BASE}/api/adjust" \
  -H "Content-Type: application/json" \
  -d '{"param":"frequency","step":10}'; echo; check

echo "--- POST /api/adjust (wpm -1) ---"
curl -s -X POST "${BASE}/api/adjust" \
  -H "Content-Type: application/json" \
  -d '{"param":"wpm","step":-1}'; echo; check

echo "--- POST /api/test (500ms tone) ---"
curl -s -X POST "${BASE}/api/test"; echo; check

sleep 1

echo "--- POST /api/send (send CQ) ---"
curl -s -X POST "${BASE}/api/send" \
  -H "Content-Type: application/json" \
  -d '{"text":"CQ CQ CQ"}'; echo; check

sleep 3

echo "--- POST /api/stop ---"
curl -s -X POST "${BASE}/api/stop"; echo; check

echo "--- POST /api/start-detection (pin_dot) ---"
curl -s -X POST "${BASE}/api/start-detection" \
  -H "Content-Type: application/json" \
  -d '{"role":"pin_dot"}'; echo; check

sleep 1

echo "--- GET /api/detection-status ---"
curl -s "${BASE}/api/detection-status"; echo; check

echo "--- POST /api/stop-detection ---"
curl -s -X POST "${BASE}/api/stop-detection"; echo; check

echo "--- POST /settings (restore defaults) ---"
curl -s -X POST "${BASE}/settings" \
  -H "Content-Type: application/json" \
  -d '{"frequency":800,"wpm":20}'; echo; check

echo "--- GET /static/css/style.css ---"
curl -s -o /dev/null -w "%{http_code}" "${BASE}/static/css/style.css" | grep -q 200; check

echo "--- GET /static/js/main.js ---"
curl -s -o /dev/null -w "%{http_code}" "${BASE}/static/js/main.js" | grep -q 200; check

echo ""
echo "=== Results: ${pass} passed, ${fail} failed ==="
