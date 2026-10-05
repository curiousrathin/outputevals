"""Prompt construction for the two arena arms.

Both arms share an identical prefix (instructions + data), so the only
difference the model sees is the configuration block appended for the
configured arm. The shared prefix also carries the cache breakpoint, so both
arms reuse the same cached data.

Data modes:
- inline: the original CSV, verbatim, when it fits in the context window.
- query:  larger CSVs are loaded into a SQL table; the prompt carries the
          schema and the first rows of the original file, and the model reads
          the rest through the query_data tool.
"""

import hashlib

from app.models import Configuration, Dataset

INSTRUCTIONS = """You are a data analyst answering questions about a CSV dataset.
Answer using only the data provided. Cite the specific rows or values that support your answer.
If the data does not contain the answer, say so plainly instead of guessing."""

QUERY_INSTRUCTIONS = """The dataset is too large to include in full. It is loaded as a DuckDB table named `data` \
with every row of the original file. Use the query_data tool to read it: aggregate in SQL instead of fetching raw \
rows, and base every number in your answer on query results."""

CONFIG_PREAMBLE = "The dataset owner provided the following to help you interpret the data:"
SAMPLE_LINES = 20


def configuration_text(config: Configuration, dataset: Dataset) -> str:
    """Render a configuration as prompt text. Empty string if it adds nothing."""
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

    if config.context_markdown.strip():
        parts.append(
            f"<additional_context>\n{config.context_markdown.strip()}\n</additional_context>"
        )
    return "\n\n".join(parts)


def config_version(config_text: str) -> str:
    return hashlib.sha256(config_text.encode()).hexdigest()[:16]


def inline_data_text(dataset: Dataset, csv_text: str) -> str:
    return f'{INSTRUCTIONS}\n\n<dataset filename="{dataset.filename}">\n{csv_text}\n</dataset>'


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
