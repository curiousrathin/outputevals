"""Read-only SQL access to a dataset, for CSVs too large to paste into a prompt.

The CSV is loaded into an in-memory DuckDB table named `data`; external file
access and configuration changes are then locked, so the model can only read
that table.
"""

import csv
import io
import re
from pathlib import Path

import duckdb

MAX_RESULT_ROWS = 200
MAX_RESULT_CHARS = 20_000
_ALLOWED = re.compile(r"^\s*(select|with|describe|summarize)\b", re.IGNORECASE)

TOOL = {
    "name": "query_data",
    "description": (
        "Run a read-only DuckDB SQL query against the dataset table `data` and get the result as CSV. "
        f"Returns at most {MAX_RESULT_ROWS} rows, so aggregate in SQL (GROUP BY, SUM, COUNT) rather than "
        'fetching raw rows. Quote column names that contain spaces or capitals with double quotes, e.g. "Due Date".'
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "A single SELECT/WITH/DESCRIBE/SUMMARIZE statement.",
            }
        },
        "required": ["sql"],
        "additionalProperties": False,
    },
}


class QueryError(ValueError):
    pass


class DataQuery:
    def __init__(self, csv_path: Path):
        self.con = duckdb.connect()
        path = str(csv_path).replace("'", "''")
        self.con.execute(
            f"CREATE TABLE data AS SELECT * FROM read_csv_auto('{path}', sample_size=-1)"
        )
        self.con.execute("SET enable_external_access = false")
        self.con.execute("SET lock_configuration = true")

    def schema(self) -> list[tuple[str, str]]:
        return [(r[0], r[1]) for r in self.con.execute("DESCRIBE data").fetchall()]

    def run(self, sql: str) -> dict:
        """Execute one query. Returns {csv, row_count, truncated}; raises QueryError."""
        sql = sql.strip().rstrip(";").strip()
        if ";" in sql:
            raise QueryError("Only one statement per query.")
        if not _ALLOWED.match(sql):
            raise QueryError(
                "Only read-only SELECT, WITH, DESCRIBE or SUMMARIZE queries are allowed."
            )
        try:
            cursor = self.con.execute(sql)
            rows = cursor.fetchmany(MAX_RESULT_ROWS + 1)
            columns = [d[0] for d in cursor.description]
        except duckdb.Error as e:
            raise QueryError(str(e).splitlines()[0]) from e

        truncated = len(rows) > MAX_RESULT_ROWS
        rows = rows[:MAX_RESULT_ROWS]
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(columns)
        writer.writerows(rows)
        text = out.getvalue()
        if len(text) > MAX_RESULT_CHARS:
            text, truncated = text[:MAX_RESULT_CHARS], True
        if truncated:
            text += f"\n[Result truncated. Showing up to {MAX_RESULT_ROWS} rows; aggregate to see everything.]"
        return {"csv": text, "row_count": len(rows), "truncated": truncated}

    def close(self) -> None:
        self.con.close()
