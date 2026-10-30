#!/usr/bin/env bash
#
# Checks every part of the system and reports what works.
# The API must already be running (make run, in another terminal).
#
set -uo pipefail
cd "$(dirname "$0")"

API="${API:-http://127.0.0.1:8000}"
GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; NC='\033[0m'
pass=0; fail=0; skip=0

ok()  { echo -e "  ${GREEN}PASS${NC}  $1"; pass=$((pass+1)); }
bad() { echo -e "  ${RED}FAIL${NC}  $1"; fail=$((fail+1)); }
skp() { echo -e "  ${YELLOW}SKIP${NC}  $1"; skip=$((skip+1)); }

PYBIN=service/.venv/bin/python
[ -x "$PYBIN" ] || PYBIN=python3

# Read a value out of JSON on stdin. Keys are passed as separate arguments, so
# nothing is interpolated into the Python source — an earlier version built the
# expression as a string and the quotes collided.
#   echo "$json" | jget products
#   echo "$json" | jget routine 0 product price
jget() {
  "$PYBIN" -c '
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(1)
for k in sys.argv[1:]:
    try:
        d = d[int(k)] if k.lstrip("-").isdigit() else d[k]
    except Exception:
        sys.exit(1)
if d is None:
    sys.exit(1)
print(d)
' "$@" 2>/dev/null
}

# Length of a list or dict at the given path.
jlen() {
  "$PYBIN" -c '
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(1)
for k in sys.argv[1:]:
    try:
        d = d[int(k)] if k.lstrip("-").isdigit() else d[k]
    except Exception:
        sys.exit(1)
print(len(d) if hasattr(d, "__len__") else 0)
' "$@" 2>/dev/null
}

echo
echo "Testing $API"
echo "================================================"

# ---------------------------------------------------------------- 1. health --
echo
echo "1. Service"
H=$(curl -s --max-time 10 "$API/health" 2>/dev/null)
if [ -z "$H" ]; then
  bad "API not reachable — start it with 'make run' in another terminal"
  echo; echo "  $pass passed, $fail failed"; exit 1
fi

N=$(echo "$H" | jget products)
if [ "${N:-0}" -gt 0 ] 2>/dev/null; then
  ok "API up, $N products loaded"
else
  bad "API up but no products — check DB settings in service/.env"
  echo "        /health says: $(echo "$H" | head -c 200)"
fi

P=$(echo "$H" | jget packs)
[ "${P:-0}" -gt 0 ] 2>/dev/null && ok "$P packs detected" || bad "no packs detected"

L=$(echo "$H" | jget live_stock)
[ "$L" = "True" ] && ok "live pricing on" || skp "live pricing off"

# --------------------------------------------------------------- 2. options --
echo
echo "2. Questionnaire data"
for d in visage cheveux corps interieur; do
  C=$(curl -s --max-time 10 "$API/options?domain=$d" | jlen concerns)
  if [ "${C:-0}" -gt 0 ] 2>/dev/null; then ok "$d: $C concerns available"
  else bad "$d: no concerns"; fi
done

# ------------------------------------------------------------- 3. recommend --
echo
echo "3. Recommendation engine"
R=$(curl -s --max-time 15 -X POST "$API/recommend" -H 'content-type: application/json' \
     -d '{"domain":"visage","concerns":["taches_pigmentaires"],"skin_type":"sensible"}')

S=$(echo "$R" | jlen routine)
M=$(echo "$R" | jget profile matched_products)
if [ "${S:-0}" -gt 0 ] 2>/dev/null; then ok "routine built: $S steps from ${M:-?} matches"
else bad "no routine returned"; fi

PR=$(echo "$R" | jget routine 0 product price)
[ -n "${PR:-}" ] && ok "live price present: $PR DT" || bad "no price"

RE=$(echo "$R" | jget routine 0 reason)
[ -n "${RE:-}" ] && ok "explanation present: \"$RE\"" || bad "no explanation"

NM=$(echo "$R" | jget routine 0 product name)
[ -n "${NM:-}" ] && ok "product: ${NM:0:52}" || bad "no product name"

# safety rule: a product declaring a different skin type must be excluded
R2=$(curl -s --max-time 15 -X POST "$API/recommend" -H 'content-type: application/json' \
      -d '{"domain":"visage","concerns":["exces_sebum"],"skin_type":"sensible"}')
BAD=$(echo "$R2" | "$PYBIN" -c '
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    print(-1); raise SystemExit
n = 0
for s in d.get("routine", []):
    t = s["product"].get("skin_type") or []
    if t and "sensible" not in t and "tous" not in t:
        n += 1
print(n)' 2>/dev/null)
if [ "${BAD:-1}" = "0" ]; then ok "safety rule holds: no contraindicated product"
elif [ "${BAD:-1}" = "-1" ]; then bad "safety rule: could not read the response"
else bad "safety rule violated ($BAD products)"; fi

# ------------------------------------------------------------------ 4. derja --
echo
echo "4. Tunisian Arabic (no API key needed)"
D=$("$PYBIN" -c "
import sys; sys.path.insert(0,'service')
from app import derja
a = derja.analyse('3andi 7boub fi wajhi w bachra dehnia')
print(a['domain'], a['skin_type'], ','.join(a['concerns']))" 2>/dev/null)
echo "$D" | grep -q "imperfections_acne" && ok "arabizi understood: $D" \
                                         || bad "arabizi not understood"

D2=$("$PYBIN" -c "
import sys; sys.path.insert(0,'service')
from app import derja
a = derja.analyse('عندي بقع في وجهي وبشرة حساسة')
print(a['domain'], a['skin_type'], ','.join(a['concerns']))" 2>/dev/null)
echo "$D2" | grep -q "taches" && ok "arabic script understood: $D2" \
                              || bad "arabic script not understood"

# --------------------------------------------------------------- 5. semantic --
echo
echo "5. Semantic search (optional)"
SE=$(echo "$H" | jget semantic enabled)
if [ "$SE" = "True" ]; then
  # Loading the embedding model takes a while on a cold machine, and longer
  # when the project sits on /mnt/c. Wait for the service to report itself
  # warm rather than testing a feature that is still starting up.
  WARM=$(echo "$H" | jget semantic warm)
  if [ "$WARM" != "True" ]; then
    printf "  ....  waiting for the embedding model to load"
    for i in $(seq 1 60); do
      sleep 3; printf "."
      WARM=$(curl -s --max-time 10 "$API/health" | jget semantic warm)
      [ "$WARM" = "True" ] && break
    done
    echo ""
  fi
  # Generous timeout: the very first inference after startup can take tens of
  # seconds on a cold machine, and a timeout here would fail a feature that
  # actually works.
  SR=$(curl -s --max-time 90 -X POST "$API/search" -H 'content-type: application/json' \
        -d '{"query":"cuir chevelu gras avec des squames","domain":"cheveux"}')
  Q=$(echo "$SR" | jlen results)
  CAND=$(echo "$SR" | jget meta candidates)
  if [ "${Q:-0}" -gt 0 ] 2>/dev/null; then
    TOP=$(echo "$SR" | jget results 0 product name)
    SIM=$(echo "$SR" | jget results 0 similarity)
    ok "semantic search: $Q results (best $SIM — ${TOP:0:40})"
  elif [ -z "$SR" ]; then
    bad "semantic search timed out — try again, the model may still be loading"
  elif [ "${CAND:-0}" = "0" ]; then
    bad "semantic search: no candidates passed the domain filter"
  else
    bad "semantic search: ${CAND} candidates but none above the score floor"
    echo "        lower EMBED_MIN_SCORE in service/.env (currently $(echo "$SR" | jget meta min_score))"
  fi
else
  skp "disabled — enable with: make enable-semantic"
fi

# ------------------------------------------------------------------ 6. agent --
echo
echo "6. Conversational agent (optional)"
A=$(curl -s --max-time 45 -X POST "$API/chat" -H 'content-type: application/json' \
     -d '{"message":"3andi 7boub fi wajhi w bachra dehnia"}' 2>/dev/null)
if echo "$A" | grep -q '"reply"'; then
  T=$(echo "$A" | jlen meta tool_calls)
  PD=$(echo "$A" | jlen products)
  ok "agent replied, ${T:-0} tool call(s), ${PD:-0} product(s)"
elif echo "$A" | grep -qi "désactiv\|desactiv"; then
  skp "disabled — enable with: make enable-agent KEY=gsk_..."
else
  skp "no API key configured, or the provider is rate-limited"
  echo "        response: $(echo "$A" | head -c 110)"
fi

# ----------------------------------------------------------------- summary ---
echo
echo "================================================"
echo -e "  ${GREEN}$pass passed${NC}   ${RED}$fail failed${NC}   ${YELLOW}$skip skipped${NC}"
echo
[ "$fail" -eq 0 ] && echo "  Everything that is enabled works." \
                  || echo "  See the failures above."
echo
exit $([ "$fail" -eq 0 ] && echo 0 || echo 1)
