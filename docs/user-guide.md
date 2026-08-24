# User Guide

This guide walks through a real GCode session end-to-end and answers common questions. It is the companion to the [README](../README.md#use).

## Annotated example session

The example below uses the default free model `nvidia/nemotron-3-super-120b-a12b:free` (tool-capable) and a project that already has `~/.gcode/.env` configured. See [Setup](../README.md#setup) if you haven't created that file yet.

### 1. Start GCode — banner and prompt

```text
$ gcode
 GCode v0.3.2  —  local AI coding CLI  (model: nvidia/nemotron-3-super-120b-a12b:free)
 Type /help for commands, /models to switch models, /quit to exit.

 gcode> _
```

- The banner shows the version and the resolved model (from `--model` / `GCODE_MODEL` / `.gcoderc` / default).
- The `gcode>` prompt is where you type natural-language requests or slash commands.

### 2. Ask a question — streamed answer

```text
 gcode> explain what gcode/ui.py does and suggest one improvement

 ⏺ Assistant (nvidia/nemotron-3-super-120b-a12b:free):
 The file `gcode/ui.py` owns the terminal rendering — banner, markdown streaming,
 slash-command menu, and the `⏺ Tool(...) y/n` gate.  One small win: truncate
 long tool-argument previews so a `grep` with 200 matches doesn't flood the
 viewport (see `_truncate` at ui.py:18) …

 Tokens stream in live; Markdown is rendered as it arrives.
```

- Replies stream token-by-token; Markdown headings, code fences, and lists render incrementally.
- No tools run for a pure Q&A — the answer is just text.

### 3. Trigger a gated bash call

```text
 gcode> list the Python files in this repo and count their total lines

 ⏺ Tool(execute_bash)  args={"command": "find gcode -name \"*.py\" | xargs wc -l | tail -1"}
   →  y/n ?  y

 ⏺ Tool result:  842 gcode/*.py total

 ⏺ Assistant:  There are 7 Python files under `gcode/` with ~842 lines total …
```

- Every `execute_bash` (and `git_commit`, `/skill import`) shows `⏺ Tool(...)` and waits for `y/n`.
- Answer `y` to run, `n` to skip. The model's next turn sees the tool result.
- Pass `--yes` (`gcode --yes`) to skip the gate — only do this if you trust the prompts and the model.

### 4. Switch models with `/models` and `#n`

```text
 gcode> /models
  #1  nvidia/nemotron-3-super-120b-a12b:free  [openrouter] (128k ctx) [tools]
  #2  meta-llama/llama-3.2-3b-instruct:free    [openrouter] (128k ctx)
  #3  qwen/qwen3-30b-a3b:free                   [openrouter] (128k ctx) [tools]
  #4  gemma-3-4b-it:free                        [ollama] (8k)

 gcode> /model #3
   → now using qwen/qwen3-30b-a3b:free

 gcode> /model nvidia/nemotron-3-super-120b-a12b:free
   → now using nvidia/nemotron-3-super-120b-a12b:free
```

- `/models` lists free OpenRouter models (with context window and `[tools]` badge) plus local Ollama models.
- `/model <id>` switches by full id; `/model #n` switches by the numbered index from the last `/models` listing.
- Models without `[tools]` (e.g., `llama-3.2-3b:free`) will fail with `No endpoints found that support tool use` if the model tries to call a tool — see FAQ below.

### 5. Save, resume, and inspect history

```text
 gcode> /history
  [1] you: explain what gcode/ui.py does …
  [2] assistant: The file `gcode/ui.py` owns …
  [3] you: list the Python files …

 gcode> /quit
 $ gcode --session work   # resume the named session "work"
 $ gcode --session work --model qwen/qwen3-30b-a3b:free   # resume with a different model
```

- History is persisted atomically under `~/.gcode/history/` (one file per `--session` name; default session is `default`).
- `/history` shows recent turns; `/clear` discards the current session's history.
- History files are JSON; a corrupt file is surfaced as a warning and treated as empty, and a failed save is warned but does not crash the session (`gcode/history.py`).

---

## FAQ

### 429 / rate-limited on a free model?

Free models on OpenRouter's shared tier are heavily rate-limited. A `429` means the shared quota is exhausted.

- Wait a moment and retry.
- Use your own `OPENROUTER_API_KEY` (higher limits than the anonymous shared key).
- Switch to a less-contended free model via `/models` → `/model #n`.
- If you have Ollama running locally, `/ollama` and `/pull <model>` give you local, un-rate-limited models.

The error formatter detects `429` and surfaces the provider's retry hint (`gcode/errors.py`).

### “No endpoints found that support tool use” (404)?

Not every free model supports tool calling. For example `meta-llama/llama-3.2-3b-instruct:free` returns 404 when the agent tries `execute_bash` or `read_file`.

- Stick to models with the `[tools]` badge in `/models` (e.g., `nvidia/nemotron-3-super-120b-a12b:free`, `qwen/qwen3-30b-a3b:free`).
- The `Models` section in the README lists the default and the failure mode; `/models` is the live source of truth.

### Is `--yes` safe?

`--yes` (and `--yes` / `auto_approve = true` in `.gcoderc`) skips the `y/n` gate for `execute_bash` and `/skill import`. The model can then run any shell command without confirmation.

Only use it if you trust the prompt, the model, and the directory you launched in. For normal use, keep the gate and answer `y/n` per call.

### Where is history stored?

- `~/.gcode/history/<session>.json` — one JSON file per `--session` name.
- Default session: `~/.gcode/history/default.json`.
- `gcode/history.py` writes atomically (`tmp + rename`) and surfaces a warning if the file is corrupt or can't be saved, rather than crashing.

To clear a session: `/clear` inside GCode, or delete the file (`rm ~/.gcode/history/<session>.json`). To uninstall fully, remove `~/.gcode/` after deleting those files.

### How do I uninstall?

```bash
pip uninstall gcode
rm -rf ~/.gcode   # removes .env, history, skills, and .gcoderc if you put it there
```

Project-local skills live in `.gcode/skills/` inside each project — delete that folder per-project if you used it.

### Ollama setup?

1. Install Ollama: https://ollama.ai
2. Pull a tool-capable local model: `ollama pull qwen3:8b` (or any model you want)
3. In GCode: `/ollama` to list locals, `/models` to see both OpenRouter and Ollama, `/model <id>` to switch
4. `gcode --model qwen3:8b` to start directly on a local model (no API key needed for Ollama-only use)

See `/model` handling in `gcode/cli.py` and `gcode/ollama.py` for the selection logic.

### Rate limits, tool 404s, and model switching in one flow?

A typical resilient loop:

1. Start on the default free model.
2. If you hit `429`, wait 20–30s or `/model #n` to a different `[tools]` free model.
3. If you hit `No endpoints found that support tool use`, the model doesn't support tools — `/models` → pick a `[tools]` model.
4. For sustained work, pull an Ollama model and run fully local.

---

## Next steps

- Configure defaults in `.gcoderc` (see [Configuration file](../README.md#configuration-file)).
- Install skills under `.gcode/skills/` or `~/.gcode/skills/` (see [Skills](../README.md#skills)).
- On Windows, read [Windows setup and troubleshooting](windows.md).
