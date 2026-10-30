#!/usr/bin/env python3
"""List the models a provider currently offers, marking tool support.

The agent requires tool calling. Providers expose tool-capable and text-only
models through the same endpoint, so the distinction has to be read from the
model metadata rather than guessed from the name.
"""
import json
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    print("  Could not read the provider response.")
    sys.exit(1)

models = data.get("data") or []
if not models:
    print("  No models returned. Check LLM_BASE_URL and LLM_API_KEY.")
    sys.exit(1)

# speech and embedding models are irrelevant here
SKIP = ("whisper", "tts", "embed", "guard", "orpheus")

rows = []
for m in models:
    mid = str(m.get("id", ""))
    if any(w in mid.lower() for w in SKIP):
        continue
    feats = m.get("supported_features") or []
    tools = "tools" in feats
    # some providers omit the field entirely; do not claim knowledge we lack
    mark = "[tools]" if tools else ("[no tools]" if feats else "[unknown]")
    rows.append((not tools, mid, mark, m.get("context_window") or ""))

rows.sort()
if not rows:
    print("  No chat models found.")
    sys.exit(1)

for _, mid, mark, ctx in rows:
    ctx_s = f"  ctx {ctx}" if ctx else ""
    print(f"  {mark:<11} {mid}{ctx_s}")
