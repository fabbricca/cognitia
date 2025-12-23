#!/usr/bin/env bash
set -euo pipefail

LB_IP="${1:-10.0.0.150}"

echo "Testing Cognitia via ingress LB at https://${LB_IP} (override Host header)"

echo "\n== UI (/) =="
curl -sk -H 'Host: cognitia.iberu.me' "https://${LB_IP}/" -o /dev/null -w "UI / -> HTTP %{http_code}\n"

echo "\n== API (/health) =="
curl -sk -H 'Host: cognitia.iberu.me' "https://${LB_IP}/health" -o /dev/null -w "API /health -> HTTP %{http_code}\n"

echo "\n== API (/api/health) =="
curl -sk -H 'Host: cognitia.iberu.me' "https://${LB_IP}/api/health" -o /dev/null -w "API /api/health -> HTTP %{http_code}\n"

echo "\n== Auth (/health) =="
curl -sk -H 'Host: auth.cognitia.iberu.me' "https://${LB_IP}/health" -o /dev/null -w "AUTH /health -> HTTP %{http_code}\n"

echo "\n== Auth JWKS (/.well-known/jwks.json) =="
curl -sk -H 'Host: auth.cognitia.iberu.me' "https://${LB_IP}/.well-known/jwks.json" | head -c 400

echo "\n\nDone."
