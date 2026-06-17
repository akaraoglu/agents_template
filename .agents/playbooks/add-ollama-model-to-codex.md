# Add an Ollama Model to Codex (local model profile)

## Goal
Register a local Ollama model as a Codex `--profile` that loads reliably, keeps its
declared context window in sync with what Ollama actually loads, and survives long
multi-turn sessions without the "session hangs at low %" failure.

All Codex-side artifacts live under `~/.codex/` (NOT in this repo, and NOT in any
`agent_template_new` folder). Three directories matter:
- `~/.codex/modelfiles/<name>.Modelfile`        — tuned Ollama build recipe
- `~/.codex/model_catalogs/local-models.json`   — shared Codex catalog (one entry per model)
- `~/.codex/<profile>.config.toml`              — the Codex profile invoked with `--profile`

## Preconditions
- The base model is pulled in Ollama (`ollama pull <base>`; confirm with `ollama list`).
- The `ollama_local` provider exists in `~/.codex/config.toml`:
  ```toml
  [model_providers.ollama_local]
  name = "Ollama"
  base_url = "http://localhost:11434/v1"
  wire_api = "responses"
  ```
- You know the model's architecture facts (layers, KV heads, head dim, native context)
  for the GPU-memory budget. Get them with:
  ```bash
  curl -s http://localhost:11434/api/show -d '{"model":"<base>","verbose":true}' \
    | python3 -c "import json,sys;mi=json.load(sys.stdin)['model_info'];[print(k,'=',v) for k,v in mi.items() if any(s in k for s in ['block_count','head_count','key_length','value_length','context_length'])]"
  ```

## Budget the context BEFORE choosing num_ctx
The "stops responding after a while" hang is almost always the KV cache (plus weights)
exceeding GPU VRAM and silently spilling to CPU/RAM. Size it first.

- Per-token KV bytes (f16) = `kv_layers * kv_heads * head_dim * 2 (K+V) * 2 (bytes)`.
- Watch for **hybrid attention**: some archs (e.g. `qwen35`) keep a real KV cache on only
  a fraction of layers (the others use fixed-size linear attention). Count only the layers
  whose `head_count_kv` is non-zero. This dramatically shrinks the KV cache.
- Total resident ≈ `weights blob (Q4_K_M ≈ params*0.6 GB) + KV cache + ~1–2 GB compute`.
- KV-cache quantization (`q8_0` ≈ half, `q4_0` ≈ quarter of f16) is what makes very large
  contexts fit. It requires flash-attention on the server (see Step 5).

Pick the largest `num_ctx` whose total comfortably fits VRAM. Leave headroom; if you want
two models co-resident, both must fit at once or Ollama will swap between them per request.

## Steps

### 1. Write the tuned Modelfile — `~/.codex/modelfiles/<name>.Modelfile`
Base GGUFs commonly ship a bare `TEMPLATE {{ .Prompt }}` with no turn markers or stop
token, which degrades multi-turn behavior. Always supply: sampling, a pinned `num_ctx`,
a `stop` token, a canonical chat template, and a minimal `SYSTEM`.

```
FROM <base>:<tag>

# Model-specific sampling (use the model authors' recommended values).
PARAMETER temperature <t>
PARAMETER top_p <p>
PARAMETER top_k <k>
# ...any other recommended params (min_p, presence_penalty, repeat_penalty, ...)

# Pin the loaded context so Codex (catalog context_window) and Ollama agree.
# This is the fix for "low % shown but the session hangs": without it Ollama loads
# its own default num_ctx while the catalog claims something larger.
PARAMETER num_ctx <N>

# Stop cleanly at the model's end-of-turn marker.
PARAMETER stop "<end-of-turn-token>"

# Canonical chat template restoring this model's turn markers (replace bare {{ .Prompt }}).
TEMPLATE """<model-specific turn template>"""

# Keep the model-level prompt minimal; Codex injects the real runtime instructions.
SYSTEM """You are Codex. Follow the runtime instructions you are given."""
```

Reference templates already in this setup:
- Gemma (`<start_of_turn>` / `<end_of_turn>`): `~/.codex/modelfiles/gemma4-26b.Modelfile`
- Qwen3 ChatML (`<|im_start|>` / `<|im_end|>`): `~/.codex/modelfiles/qwen3.6-27b.Modelfile`

### 2. Build the model
```bash
cd ~/.codex/modelfiles
ollama create <name> -f <name>.Modelfile
ollama show <name> | grep -iE "num_ctx|context length"   # confirm num_ctx baked in
```

### 3. Add a catalog entry — `~/.codex/model_catalogs/local-models.json`
Copy an existing entry in the `models` array and edit it. The single most important rule:

> **`context_window` and `max_context_window` MUST equal the Modelfile `num_ctx`.**

A mismatch is the root cause of the "hangs at low %" symptom: Codex reports usage against
a context size larger than what Ollama actually loaded, so real overflow happens while the
UI still shows single-digit percentages. Edit by slug, programmatically, to avoid touching
sibling entries:
```bash
python3 - <<'PY'
import json
p="/home/alik/.codex/model_catalogs/local-models.json"
d=json.load(open(p))
for m in d["models"]:
    if m["slug"]=="<name>":
        m["context_window"]=<N>
        m["max_context_window"]=<N>
json.dump(d,open(p,"w"),indent=2,ensure_ascii=False); open(p,"a").write("\n")
print({m["slug"]:(m["context_window"],m["max_context_window"]) for m in d["models"]})
PY
```
Set `provider` to `ollama_local`, `enabled` true, and `input_modalities` to match the
model (e.g. include `image` only for vision models).

### 4. Create the Codex profile — `~/.codex/<profile>.config.toml`
```toml
model = "<name>"
model_provider = "ollama_local"
model_catalog_json = "/home/alik/.codex/model_catalogs/local-models.json"
approval_policy = "on-request"
approvals_reviewer = "user"
model_reasoning_effort = "medium"   # see Notes: "high" can over-think and stall
model_verbosity = "medium"
```
> **Profile names cannot contain dots.** `codex exec --profile qwen3.6-27b` is rejected
> ("pass a plain name"). Name the profile file/flag without dots (e.g. `qwen36-27b`); the
> underlying Ollama model name may still contain dots.

To grant write access to extra paths for this profile, add:
```toml
[sandbox_workspace_write]
writable_roots = ["/abs/path/one", "/abs/path/two"]
```

### 5. (Large context only) Enable q8_0 KV cache globally on the Ollama server
Needed when f16 KV would exceed VRAM but q8_0 fits. This is a **global, root-owned**
change affecting every model the server loads, and it requires a restart (drops any
currently loaded model).
```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf >/dev/null <<'EOF'
[Service]
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama
```
Confirm it took: `systemctl show ollama -p Environment` should list both vars.

### 6. Verify (do not skip)
```bash
# (a) Load the model and force KV allocation
curl -s http://localhost:11434/api/generate \
  -d '{"model":"<name>","prompt":"hi","stream":false,"options":{"num_predict":8}}' >/dev/null

# (b) MUST show CONTEXT=<N> and PROCESSOR=100% GPU (any % CPU = spill = future hang)
ollama ps

# (c) Confirm the actual server flags
ps aux | grep "[l]lama-server" | grep -oE "\-c [0-9]+|--cache-type-[kv] [a-z0-9_]+|--flash-attn [a-z]+"

# (d) Coherence under the (possibly quantized) KV cache
curl -s http://localhost:11434/api/chat -d '{"model":"<name>","stream":false,"think":false,
  "messages":[{"role":"user","content":"Reply with exactly: OK 12+30=42"}],
  "options":{"num_predict":40,"temperature":0}}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['message']['content'])"

# (e) End-to-end Codex smoke
codex exec --profile <profile> "print the word READY and nothing else"
```

## Verification checklist
- `ollama show <name>` reports the intended `num_ctx`.
- Catalog `context_window` == `max_context_window` == Modelfile `num_ctx`.
- `ollama ps` shows the target CONTEXT at **100% GPU** with VRAM headroom remaining.
- `llama-server` flags show the expected `-c <N>`, `--flash-attn on`, and (if used) `--cache-type-k/v q8_0`.
- Coherence test returns the exact expected string with a clean stop.
- `codex exec --profile <profile>` returns a normal completion.

## Recovery / rollback
- "Hangs at low %": re-check catalog↔num_ctx equality and `ollama ps` for any CPU spill;
  lower `num_ctx` (and the catalog to match) until it is 100% GPU.
- Large context won't fit at f16: enable q8_0 KV (Step 5) or drop `num_ctx`.
- q8_0 KV unsupported / poor quality: fall back to `q4_0` (smaller) or remove the override
  and use a smaller f16 context — no model rebuild needed, just the env value + restart.
- Profile rejected: ensure the `--profile` name has no dots.
- Revert a model: lower `num_ctx`/catalog and `ollama create` again, or delete the profile
  `.config.toml`, the catalog entry, and `ollama rm <name>`.

## Notes / gotchas
- Keep the Modelfile `num_ctx` and the catalog window in lockstep forever; changing one
  without the other reintroduces the hang.
- `OLLAMA_KV_CACHE_TYPE` is global — once set, it applies to every model (e.g. it also
  affects gemma). The quality impact of `q8_0` is negligible for coding use.
- Thinking models emit a `reasoning` block before `content`. With `model_reasoning_effort
  = "high"` they can spend the whole turn reasoning and finish with little or no actionable
  output (empty `agent_message`, no tool call) — which looks like "answers my reply but
  won't continue the task." Prefer `medium` for local thinking models and raise only when
  needed.
- Two large-context models usually cannot be co-resident on one GPU; Ollama swaps between
  them per request (a startup latency cost, not a correctness problem).
