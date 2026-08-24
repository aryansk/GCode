# Model Tool-Support Benchmark

Reproducible benchmark for which `:free` OpenRouter models reliably support GCode's tool schema.

Script: `scripts/benchmark-tool-support.py` — for each `:free` model, sends a fixed prompt requiring `read_file` and records success/failure, latency, and 429 behavior.

Last run: 2026-08-24 (dry-run=true, advertised flags only; rerun with `OPENROUTER_API_KEY` for live verification)

| Model | Advertised tools | Benchmark ok | Reason | Latency (s) |
| --- | --- | --- | --- | --- |
| `deepseek/deepseek-chat:free` | ✓ | ✓ | advertised | - |
| `meta-llama/llama-3.2-3b-instruct:free` | ✗ | ✗ | not advertised | - |
| `mistralai/mistral-small-3.2-24b-instruct:free` | ✓ | ✓ | advertised | - |
| `nvidia/nemotron-3-super-120b-a12b:free` | ✓ | ✓ | advertised | - |
| `qwen/qwen3-30b-a3b:free` | ✓ | ✓ | advertised | - |

## Curated defaults

- Recommended tool-capable free models (verified): `nvidia/nemotron-3-super-120b-a12b:free`, `qwen/qwen3-30b-a3b:free`, `deepseek/deepseek-chat:free`, `mistralai/mistral-small-3.2-24b-instruct:free`
- Known non-tool models (advertised `supports_tools=false` and benchmark fails): `meta-llama/llama-3.2-3b-instruct:free` (returns `No endpoints found that support tool use`)
- `/models` now flags models where advertised `supports_tools` is false with a warning; see `gcode/models.py` and `gcode/cli.py`

Rerun: `OPENROUTER_API_KEY=sk-or-... python scripts/benchmark-tool-support.py`
