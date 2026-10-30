#!/usr/bin/env bash
# Prueba de humo de la integración Nebius / NVIDIA Nemotron.
#
# Comprueba las tres capas por separado, para que un fallo diga cuál está rota:
#   1. la clave contra Token Factory (sin proxy),
#   2. el catálogo que el proxy publica en /v1/models,
#   3. una completion real a través del proxy.
#
# Uso:  NEBIUS_API_KEY=... ./scripts/verify-nebius.sh
#       PROXY_URL=http://localhost:5100 ./scripts/verify-nebius.sh   # reusa uno vivo
#
# Sale con 0 solo si las tres capas responden.
set -uo pipefail

: "${NEBIUS_API_KEY:?falta NEBIUS_API_KEY}"
BASE="${NEBIUS_PROXY_URL:-https://api.tokenfactory.nebius.com/v1}"
MODEL="${NEMOTRON_MODEL:-nvidia/nemotron-3-super-120b-a12b}"
PROXY_URL="${PROXY_URL:-http://localhost:5100}"
fail=0

say() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

say "1. Token Factory directo ($BASE)"
if ids=$(curl -sf -m 25 -H "Authorization: Bearer $NEBIUS_API_KEY" \
           "$BASE/models" | python3 -c \
           'import json,sys; [print(m["id"]) for m in json.load(sys.stdin)["data"]]'); then
  echo "   modelos servidos: $(printf '%s\n' "$ids" | wc -l)"
  printf '%s\n' "$ids" | grep -i nemotron | sed 's/^/   nemotron: /' || echo "   sin Nemotron en el catálogo"
else
  echo "   FALLO: la clave no autentica contra Token Factory"; fail=1
fi

say "2. Catálogo del proxy ($PROXY_URL/v1/models)"
if models=$(curl -sf -m 30 "$PROXY_URL/v1/models"); then
  printf '%s' "$models" | python3 -c '
import json, sys
m = [x for x in json.load(sys.stdin).get("models", []) if x.get("provider") == "nebius"]
print("   modelos nebius publicados:", len(m))
for x in m:
    print("  ", x["id"], "[", x.get("tier"), "]")
raise SystemExit(0 if m else 1)
' || { echo "   FALLO: el proxy no publica modelos nebius"; fail=1; }
else
  echo "   FALLO: el proxy no responde (¿está arriba?)"; fail=1
fi

say "3. Completion real vía proxy ($MODEL)"
resp=$(curl -s -m 120 -X POST "$PROXY_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"$MODEL\",\"role\":\"architect\",\"max_tokens\":700,\"messages\":[{\"role\":\"user\",\"content\":\"Answer in one short sentence: what does evidence-based verification mean?\"}]}")
printf '%s' "$resp" | python3 -c '
import json,sys
d=json.load(sys.stdin)
if "error" in d:
    print("   FALLO:", json.dumps(d["error"])[:300]); raise SystemExit(1)
c=d["choices"][0]
txt=(c["message"].get("content") or "").strip()
print("   provider:", d.get("provider"), "| modelo:", d.get("model"))
print("   finish:", c.get("finish_reason"), "| tokens:", d.get("usage",{}).get("completion_tokens"))
print("   respuesta:", (txt[:220] or "(vacía)")
      + "\n   (los modelos de razonamiento gastan tokens en `reasoning`; sube max_tokens si sale vacía)")
raise SystemExit(0 if txt else 1)
' || fail=1

say "resultado"
[ "$fail" -eq 0 ] && echo "   OK: las tres capas responden" || echo "   hay fallos, ver arriba"
exit "$fail"
