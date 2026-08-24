"""GCode agent: model construction, the streaming tool-call loop, history trim."""

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from gcode.errors import format_model_error
from gcode.ollama import OLLAMA_V1_URL
from gcode.tools import TOOL_MAP, is_auto_approve


def _print_usage(response, ui) -> None:
    """Print a compact footer with token usage when provider supplies it."""
    try:
        usage = None
        # LangChain 0.3+ stores usage in usage_metadata
        usage_meta = getattr(response, "usage_metadata", None)
        if usage_meta:
            # usage_metadata may be dict or object with input_tokens/output_tokens
            if isinstance(usage_meta, dict):
                usage = usage_meta
            else:
                usage = {
                    "input_tokens": getattr(usage_meta, "input_tokens", None),
                    "output_tokens": getattr(usage_meta, "output_tokens", None),
                    "total_tokens": getattr(usage_meta, "total_tokens", None),
                }
        # Fallback: response_metadata may contain token_usage
        if not usage or not any(usage.values()):
            meta = getattr(response, "response_metadata", {}) or {}
            # OpenRouter may put usage under response_metadata['usage'] or ['token_usage']
            if isinstance(meta, dict):
                cand = meta.get("token_usage") or meta.get("usage") or {}
                if isinstance(cand, dict) and cand:
                    usage = cand
                # Also check for X-RateLimit headers
                headers = meta.get("headers") or meta.get("response_headers") or {}
                if headers and isinstance(headers, dict):
                    # headers may be case-insensitive
                    rl_remaining = None
                    for k in ("x-ratelimit-remaining", "X-RateLimit-Remaining", "ratelimit-remaining"):
                        if k in headers:
                            rl_remaining = headers[k]
                            break
                    if rl_remaining is not None:
                        usage = usage or {}
                        usage["rate_limit_remaining"] = rl_remaining
        if not usage or not any(v is not None for v in usage.values()):
            return
        # Build compact footer
        parts = []
        inp = usage.get("input_tokens") or usage.get("prompt_tokens") or usage.get("promptTokens")
        out = usage.get("output_tokens") or usage.get("completion_tokens") or usage.get("completionTokens")
        total = usage.get("total_tokens") or usage.get("totalTokens")
        if inp is not None or out is not None:
            if inp is not None and out is not None:
                parts.append(f"{inp} in / {out} out")
            elif inp is not None:
                parts.append(f"{inp} in")
            else:
                parts.append(f"{out} out")
            if total is not None:
                parts.append(f"total {total}")
        # Cost approx (if available)
        cost = usage.get("cost") or usage.get("total_cost")
        if cost is not None:
            try:
                parts.append(f"~${float(cost):.4f}")
            except Exception:
                parts.append(f"cost {cost}")
        # Rate limit remaining
        rl = usage.get("rate_limit_remaining") or usage.get("x-ratelimit-remaining")
        if rl is not None:
            parts.append(f"rate-limit remaining: {rl}")
        if parts:
            ui.info(f"[dim]Usage: {'  ·  '.join(parts)}[/dim]")
    except Exception:
        # Never let usage printing break the turn
        return

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MAX_HISTORY = 30


def build_model(model_id: str, api_key: str):
    """Build a ChatOpenAI model bound to all GCode tools.

    Supports both OpenRouter (requires api_key) and local Ollama (api_key can
    be empty).  Ollama model ids are prefixed with ``ollama/`` (e.g.
    ``ollama/llama3.2``); the prefix is stripped when talking to the local
    server.
    """
    from gcode.tools import ALL_TOOLS

    # Ollama local models — no API key required
    # Ollama's OpenAI-compatible endpoint ignores the API key field, so we
    # pass a non-empty placeholder to satisfy ChatOpenAI's validation.
    if model_id.startswith("ollama/"):
        ollama_model = model_id[len("ollama/") :]  # strip prefix
        return ChatOpenAI(
            model=ollama_model,
            api_key=SecretStr("ollama"),
            base_url=OLLAMA_V1_URL,
        ).bind_tools(ALL_TOOLS)

    # Default: OpenRouter
    return ChatOpenAI(
        model=model_id,
        api_key=SecretStr(api_key),
        base_url=OPENROUTER_BASE_URL,
    ).bind_tools(ALL_TOOLS)


def trim_history(messages: list) -> None:
    """Keep the system message plus the most recent MAX_HISTORY messages.

    Trims only at a settled boundary (between turns) and drops any leading
    ToolMessages whose owning assistant message was trimmed, so the API never
    sees an orphaned tool result.
    """
    if len(messages) <= MAX_HISTORY + 1:
        return
    tail = messages[-MAX_HISTORY:]
    while tail and isinstance(tail[0], ToolMessage):
        tail.pop(0)
    messages[:] = [messages[0]] + tail


def _stream(messages: list, model, ui) -> AIMessage:
    """Stream one model response, forwarding text to the UI, and return the
    accumulated message (with ``tool_calls`` populated).

    A Ctrl+C during streaming stops the stream but keeps the session alive:
    whatever was accumulated so far is returned as the turn's assistant
    message so it gets persisted with the rest of the history.
    """
    ui.assistant_start()
    accumulated = None
    interrupted = False
    try:
        for chunk in model.stream(messages):
            if not isinstance(chunk, AIMessageChunk):
                continue
            if chunk.content:
                ui.token(chunk.content)
            accumulated = chunk if accumulated is None else accumulated + chunk
    except KeyboardInterrupt:
        interrupted = True
    if accumulated is None:
        accumulated = AIMessageChunk(content="")
    ui.assistant_end()
    if interrupted:
        ui.info("(streaming stopped by user)")
    # Store the canonical AIMessage (not the chunk) for clean history + reloads.
    return AIMessage(
        content=accumulated.content,
        tool_calls=[] if interrupted else accumulated.tool_calls,
        additional_kwargs=accumulated.additional_kwargs,
        id=accumulated.id,
    )


def _run_tool(tool_name: str, tool_args: dict, ui) -> str:
    ui.tool_start(tool_name, tool_args)
    if tool_name == "execute_bash" and not is_auto_approve():
        if not ui.ask_permission("Run this command?"):
            result = "Command execution cancelled by user."
            ui.tool_result(tool_name, result)
            return result
    fn = TOOL_MAP.get(tool_name)
    if fn is None:
        result = f"Unknown tool: {tool_name}"
    else:
        try:
            result = fn.invoke(tool_args)
        except KeyboardInterrupt:
            # Ctrl+C during a tool call cancels that call and keeps the
            # session alive; the model sees a cancelled result instead of the
            # whole REPL dying.
            result = "Command execution cancelled by user."
        except Exception as exc:
            result = f"Tool {tool_name} raised: {exc}"
    ui.tool_result(tool_name, result)
    return result


def run_turn(user_input: str, messages: list, model, ui) -> None:
    """Run one user turn: append the human message, stream the response, loop
    over any tool calls (with UI display + a permission gate for bash), and
    append everything to ``messages``.
    """
    messages.append(HumanMessage(content=user_input))

    try:
        response = _stream(messages, model, ui)
    except Exception as exc:
        ui.error("model request failed: " + format_model_error(exc))
        return

    messages.append(response)
    _print_usage(response, ui)

    errored = False
    while getattr(response, "tool_calls", None):
        for tool_call in response.tool_calls:
            result = _run_tool(tool_call["name"], tool_call["args"], ui)
            messages.append(
                ToolMessage(
                    content=result,
                    name=tool_call["name"],
                    tool_call_id=tool_call["id"],
                )
            )

        try:
            response = _stream(messages, model, ui)
        except Exception as exc:
            ui.error("model request failed: " + format_model_error(exc))
            errored = True
            break

        messages.append(response)
        _print_usage(response, ui)

    if errored:
        return
