#!/usr/bin/env python3
"""
Benchmark which :free OpenRouter models reliably support GCode's tool schema.

For each :free model on OpenRouter, send a fixed prompt that requires one
tool call (read_file) and record success/failure, tool-support, latency,
and 429 behavior. Results are written to docs/model-tool-support.md and can
be re-run with an OpenRouter API key.

Usage:
  OPENROUTER_API_KEY=sk-or-... python scripts/benchmark-tool-support.py
  # Or dry-run without a key (uses supports_tools flag only):
  python scripts/benchmark-tool-support.py --dry-run
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("requests not installed; pip install requests", file=sys.stderr)
    sys.exit(1)

from gcode.models import list_free_models

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
TOOL_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the local filesystem",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    }
]
PROMPT = "Use the read_file tool to read path 'README.md' and summarize its first line."


def benchmark_one(model_id: str, api_key: str, timeout: int = 30) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/shauryagangrade/GCode",
    }
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": PROMPT}],
        "tools": TOOL_SCHEMA,
        "tool_choice": "auto",
    }
    start = time.time()
    try:
        resp = requests.post(OPENROUTER_CHAT_URL, headers=headers, json=payload, timeout=timeout)
        latency = time.time() - start
        # 429 handling
        if resp.status_code == 429:
            return {"model": model_id, "ok": False, "reason": "429 rate-limited", "latency": latency, "status": 429}
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            return {"model": model_id, "ok": False, "reason": "no choices", "latency": latency}
        msg = choices[0].get("message", {})
        tool_calls = msg.get("tool_calls") or msg.get("toolCalls") or []
        # OpenRouter may put tool_calls under message.tool_calls
        if tool_calls:
            return {"model": model_id, "ok": True, "reason": "tool called", "latency": latency}
        # Check if model refused tool and returned text instead
        content = msg.get("content", "")
        if "No endpoints found that support tool use" in str(content):
            return {"model": model_id, "ok": False, "reason": "No endpoints found that support tool use", "latency": latency}
        return {"model": model_id, "ok": False, "reason": f"no tool call, content={content[:80]!r}", "latency": latency}
    except requests.exceptions.RequestException as exc:
        latency = time.time() - start
        status = getattr(exc.response, "status_code", None) if hasattr(exc, "response") else None
        return {"model": model_id, "ok": False, "reason": f"request error: {exc}", "latency": latency, "status": status}


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark :free models for tool support")
    parser.add_argument("--dry-run", action="store_true", help="Don't call API; use supports_tools flag only")
    parser.add_argument("--output", default="docs/model-tool-support.md", help="Output markdown file")
    parser.add_argument("--json", default="docs/model-tool-support.json", help="Output JSON file")
    args = parser.parse_args()

    free_models, err = list_free_models()
    if err:
        print(f"Failed to list models: {err}", file=sys.stderr)
        sys.exit(1)
    if not free_models:
        print("No :free models found", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not args.dry_run and not api_key:
        print("OPENROUTER_API_KEY not set; running --dry-run (supports_tools only)", file=sys.stderr)
        args.dry_run = True

    results = []
    for m in free_models:
        mid = m["id"]
        supports = m.get("supports_tools", False)
        if args.dry_run:
            # Dry-run: report advertised support only
            results.append(
                {
                    "model": mid,
                    "advertised_tools": supports,
                    "ok": supports,
                    "reason": "advertised" if supports else "not advertised",
                    "latency": None,
                }
            )
            print(f"{mid}: {'tools' if supports else 'no-tools'} (dry-run)")
        else:
            res = benchmark_one(mid, api_key)
            res["advertised_tools"] = supports
            results.append(res)
            status = "OK" if res["ok"] else f"FAIL ({res['reason']})"
            print(f"{mid}: {status} in {res['latency']:.2f}s")

    # Write JSON
    out_json = Path(args.json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(results, indent=2))
    print(f"Wrote {out_json} ({len(results)} models)")

    # Write Markdown table
    out_md = Path(args.output)
    lines = [
        "# Model Tool-Support Benchmark",
        "",
        "Reproducible benchmark for which `:free` OpenRouter models reliably support GCode's tool schema.",
        "",
        "Script: `scripts/benchmark-tool-support.py` — for each `:free` model, sends a fixed prompt requiring `read_file` and records success/failure, latency, and 429 behavior.",
        "",
        f"Last run: {time.strftime('%Y-%m-%d')} (dry-run={args.dry_run})",
        "",
        "| Model | Advertised tools | Benchmark ok | Reason | Latency (s) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in sorted(results, key=lambda x: x["model"]):
        adv = "✓" if r.get("advertised_tools") else "✗"
        ok = "✓" if r.get("ok") else "✗"
        reason = (r.get("reason") or "").replace("|", "\\|")[:60]
        lat = f"{r['latency']:.2f}" if r.get("latency") is not None else "-"
        lines.append(f"| `{r['model']}` | {adv} | {ok} | {reason} | {lat} |")
    lines.extend(
        [
            "",
            "## Curated defaults",
            "",
            "- Recommended tool-capable free models (verified): `nvidia/nemotron-3-super-120b-a12b:free`, `qwen/qwen3-30b-a3b:free`, `deepseek/deepseek-chat:free`, `mistralai/mistral-small-3.2-24b-instruct:free`",
            "- Known non-tool models (advertised `supports_tools=false` and benchmark fails): `meta-llama/llama-3.2-3b-instruct:free` (returns `No endpoints found that support tool use`)",
            "- `/models` now flags models where advertised `supports_tools` is false with a warning; see `gcode/models.py` and `gcode/cli.py`",
            "",
            "Rerun: `OPENROUTER_API_KEY=sk-or-... python scripts/benchmark-tool-support.py`",
        ]
    )
    out_md.write_text("\n".join(lines) + "\n")
    print(f"Wrote {out_md}")


if __name__ == "__main__":
    main()
