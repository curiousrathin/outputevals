import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic

from app.config import settings
from app.core.ledger import build_snapshot
from app.core.prompts import system_as_text
from app.core.sqltool import TOOL, DataQuery, QueryError

MAX_TOKENS = 16000
MAX_TOOL_TURNS = 25


def _run_tool(query: DataQuery, block) -> tuple[dict, dict]:
    """Execute one query_data call -> (tool_result block, trace record)."""
    sql = block.input.get("sql", "") if isinstance(block.input, dict) else ""
    try:
        result = query.run(sql)
    except QueryError as e:
        return (
            {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": f"Error: {e}",
                "is_error": True,
            },
            {"sql": sql, "error": str(e), "row_count": 0, "result": ""},
        )
    return (
        {"type": "tool_result", "tool_use_id": block.id, "content": result["csv"]},
        {"sql": sql, "error": None, "row_count": result["row_count"], "result": result["csv"]},
    )


def run_arm(
    client: anthropic.Anthropic,
    arm: str,
    system: list[dict],
    question: str,
    tags: dict[str, str],
    csv_path: Path | None = None,
) -> dict:
    """Ask one arm the question. Never raises: failures are recorded on the response.

    csv_path set -> query mode: the model reads the data through the query_data tool.
    """
    model = settings.llm_model
    mode = "query" if csv_path else "inline"
    params = {"effort": settings.llm_effort, "max_tokens": MAX_TOKENS, "mode": mode}
    result = {
        "arm": arm,
        "model": model,
        "mode": mode,
        "system_prompt": system_as_text(system),
        "tool_calls": [],
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
    }
    messages: list[dict] = [{"role": "user", "content": question}]
    query = DataQuery(csv_path) if csv_path else None
    start = time.perf_counter()
    try:
        for _ in range(MAX_TOOL_TURNS + 1):
            response = client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                thinking={"type": "adaptive"},
                output_config={"effort": settings.llm_effort},
                system=system,
                messages=messages,
                **({"tools": [TOOL]} if query else {}),
            )
            usage = response.usage
            result["input_tokens"] += usage.input_tokens
            result["output_tokens"] += usage.output_tokens
            result["cache_creation_tokens"] += usage.cache_creation_input_tokens or 0
            result["cache_read_tokens"] += usage.cache_read_input_tokens or 0

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_uses or not query:
                break
            # Append the assistant turn unchanged (thinking blocks included), then all results at once.
            messages.append({"role": "assistant", "content": response.content})
            results = [_run_tool(query, b) for b in tool_uses]
            messages.append({"role": "user", "content": [r for r, _ in results]})
            result["tool_calls"] += [t for _, t in results]
        else:
            result["error"] = (
                f"Stopped after {MAX_TOOL_TURNS} rounds of queries without a final answer."
            )

        result["output"] = "".join(b.text for b in response.content if b.type == "text")
        result["stop_reason"] = response.stop_reason
        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None) or "unspecified"
            result["error"] = f"Model declined to answer ({category})."
        elif response.stop_reason == "max_tokens":
            result["error"] = "Answer was cut off at the token limit."
    except anthropic.APIStatusError as e:
        result["error"] = f"Anthropic API error ({e.status_code}): {e.message}"
    except anthropic.APIConnectionError:
        result["error"] = "Couldn't reach the Anthropic API."
    finally:
        if query:
            query.close()
    result["latency_ms"] = int((time.perf_counter() - start) * 1000)

    snapshot = build_snapshot(
        function_name=f"arena.{arm}",
        inputs={"system": result["system_prompt"], "question": question},
        outputs={
            "response": result.get("output", ""),
            "tool_calls": result["tool_calls"],
            "error": result.get("error") or "",
        },
        model=model,
        params=params,
        execution_time_ms=result["latency_ms"],
        tags={**tags, "arm": arm},
    )
    result["fingerprint"] = snapshot.fingerprint()
    result["content_hash"] = snapshot.content_hash()
    return result


def run_both(
    client: anthropic.Anthropic,
    systems: dict[str, list[dict]],
    question: str,
    tags: dict[str, str],
    csv_path: Path | None = None,
) -> list[dict]:
    with ThreadPoolExecutor(max_workers=len(systems)) as pool:
        futures = [
            pool.submit(run_arm, client, arm, system, question, tags, csv_path)
            for arm, system in systems.items()
        ]
        return [f.result() for f in futures]
