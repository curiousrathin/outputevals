"""Prompt construction for the two arena arms.

Both arms share an identical prefix (instructions + data), so the only
difference the model sees is the configuration block appended for the
configured arm. The shared prefix also carries the cache breakpoint, so both
arms reuse the same cached data.

Every dataset is queried, never pasted in: the CSV is loaded into a SQL table,
the prompt carries the schema and the first rows of the original file, and the
model reads the data through the query_data tool. Query results come back with
evidence ids, and the answer must cite values as {{ev:…}} references so the
fail-closed resolver can check every one before anything is shown.
"""

import hashlib

from app.models import Configuration, Dataset

INSTRUCTIONS = """You are a data analyst answering questions about a CSV dataset.
Answer using only the data. If the data does not contain the answer, say so plainly instead of guessing."""

QUERY_INSTRUCTIONS = """The dataset is loaded as a DuckDB table named `data` with every row of the original file. \
The first rows below are only a preview. Use the query_data tool to read the data: aggregate in SQL instead of \
fetching raw rows.

Every query result lists evidence ids for its values. In your answer, write each value that comes from the data \
as its reference, for example "The top customer was {{ev:7f3a91c2d0e4}} with {{ev:c91e04b7aa21}}." Never type a \
number or data value yourself, and never invent an id: an answer with any unknown reference is rejected entirely. \
If a result has no evidence ids, aggregate further until it does."""

CONFIG_PREAMBLE = "The dataset owner provided the following to help you interpret the data:"
SAMPLE_LINES = 20


def configuration_text(
    config: Configuration, dataset: Dataset, files: list[dict] | None = None
) -> str:
    """Render a configuration as prompt text. Empty string if it adds nothing.

    `files` are the resolved library attachments ({path, text}); their content is
    part of the text, so editing an attached file changes the config version."""
    dtypes = {c["name"]: c["dtype"] for c in dataset.columns}
    parts = []

    described = [n for n in config.nodes if n.get("description", "").strip()]
    if described or config.edges:
        lines = ["<data_dictionary>"]
        if described:
            lines.append("Fields:")
            lines += [
                f"- {n['id']} ({dtypes.get(n['id'], 'unknown')}): {n['description'].strip()}"
                for n in described
            ]
        if config.edges:
            lines.append("Relationships:")
            lines += [
                f"- {e['source']} → {e['target']}: {e['description'].strip()}" for e in config.edges
            ]
        lines.append("</data_dictionary>")
        parts.append("\n".join(lines))

    if files:
        docs = "\n".join(f'<file path="{f["path"]}">\n{f["text"].strip()}\n</file>' for f in files)
        parts.append(f"<library>\n{docs}\n</library>")

    if config.context_markdown.strip():
        parts.append(
            f"<additional_context>\n{config.context_markdown.strip()}\n</additional_context>"
        )
    return "\n\n".join(parts)


def config_version(config_text: str) -> str:
    return hashlib.sha256(config_text.encode()).hexdigest()[:16]


def query_data_text(dataset: Dataset, csv_text: str, schema: list[tuple[str, str]]) -> str:
    sample = "\n".join(csv_text.splitlines()[: SAMPLE_LINES + 1])
    columns = "\n".join(f'- "{name}" {dtype}' for name, dtype in schema)
    return (
        f"{INSTRUCTIONS}\n\n{QUERY_INSTRUCTIONS}\n\n"
        f'<dataset filename="{dataset.filename}" rows="{dataset.row_count}" table="data">\n'
        f"<columns>\n{columns}\n</columns>\n"
        f"<first_rows>\n{sample}\n</first_rows>\n"
        f"</dataset>"
    )


def build_system(data_text: str, config_text: str | None) -> list[dict]:
    """System blocks for one arm. config_text=None -> baseline."""
    blocks = [{"type": "text", "text": data_text, "cache_control": {"type": "ephemeral"}}]
    if config_text:
        blocks.append({"type": "text", "text": f"{CONFIG_PREAMBLE}\n\n{config_text}"})
    return blocks


def system_as_text(blocks: list[dict]) -> str:
    return "\n\n".join(b["text"] for b in blocks)
