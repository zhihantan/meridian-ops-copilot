"""The copilot's tool loop (T17, BUILD): Anthropic Messages through Unity Gateway's native Anthropic path.

The system prompt and tool definitions carry cache_control, so repeated calls read them from the prompt
cache. The model call uses the caller's token, so gateway usage is attributed to the caller. Each step
is emitted as an event (tool call, tool result, answer) for streaming and background clients.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

import anthropic

from copilot.tools import DEFINITIONS, Tools
from meridian.agent.answer import ABSTAIN, CONFIG
from meridian.common.workspace import bearer_token

MAX_TURNS = 8
SYSTEM = f"""You are Meridian Commerce's operations copilot for payment incidents.
- Use search_kb for policies, runbooks, fees and SLAs, and ask_genie for numbers from payments data.
- Answer only from tool results. Cite every fact with its label in square brackets: knowledge base passages like
  [DOC-RB-021 p.1], data from Genie like [GENIE-1a2b3c4d].
- If the tools return nothing relevant, reply exactly: {ABSTAIN}
- If sources disagree, follow the most recently modified one and name the older one.
- Do not comment on access tiers or restrictions; access is checked before you see any result.
- Be brief and concrete."""


def gateway(tools: Tools) -> anthropic.AsyncAnthropic:
    host = tools.caller.client.config.host
    return anthropic.AsyncAnthropic(base_url=f"{host}/ai-gateway/anthropic", auth_token=bearer_token(tools.caller.client))


async def run(tools: Tools, messages: list[dict], emit: Callable[[dict], Awaitable[int]]) -> str:
    client = gateway(tools)
    system = [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]
    definitions = [*DEFINITIONS[:-1], {**DEFINITIONS[-1], "cache_control": {"type": "ephemeral"}}]
    history = [{"role": m["role"], "content": m["content"]} for m in messages if m.get("role") in ("user", "assistant")]
    for _ in range(MAX_TURNS):
        resp = await client.messages.create(model=CONFIG["answer_model"], max_tokens=800, system=system,
                                            tools=definitions, messages=history)
        history.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in resp.content]})
        calls = [b for b in resp.content if b.type == "tool_use"]
        if not calls:
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            await emit({"type": "message", "message": {"role": "assistant", "content": text}})
            return text
        results = []
        for call in calls:
            await emit({"type": "message", "message": {"role": "assistant", "content": "",
                                                       "tool_calls": [{"name": call.name, "args": call.input}]}})
            output = await asyncio.to_thread(tools.call, call.name, call.input)
            summary = {"sources": [r["source"] for r in output.get("results", []) + output.get("queries", [])],
                       "note": output.get("note") or output.get("error")}
            await emit({"type": "message", "message": {"role": "tool", "name": call.name,  # labels, not text
                                                       "content": json.dumps(summary)}})
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": json.dumps(output)})
        history.append({"role": "user", "content": results})
    text = "I stopped after too many steps; please narrow the question."
    await emit({"type": "message", "message": {"role": "assistant", "content": text}})
    return text
