"""Append-only, content-addressed evidence: the only place a number may come from.

Ported from OutputTracker's store. An evidence id is a hash of what produced the
value (source data, query, cell), so the same inputs always give the same id and
a different source always gives a different one. Rows are never edited; a
correction appends a new row and marks the old one superseded, so history stays.

Minting (`cite_result`) is pure and needs no database, so arena threads can show
ids to the model mid-run; `store_cited` persists them afterwards.
"""

import hashlib
import json

from sqlmodel import Session, select

from app.models import Evidence, utcnow

# Larger results aren't cited: the model is told to aggregate further instead.
MAX_CITED_CELLS = 60


def evidence_id(source: str, query: str, params: dict) -> str:
    """Same inputs -> same id; param key order is irrelevant."""
    payload = json.dumps(params, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{source}|{query}|{payload}".encode()).hexdigest()
    return f"ev:{digest[:12]}"


def normalize_sql(sql: str) -> str:
    return " ".join(sql.strip().rstrip(";").split())


def cite_result(source: str, sql: str, columns: list[str], rows: list[list]) -> list[dict]:
    """One citable evidence record per non-null cell, or [] if the result is too big."""
    if len(rows) * len(columns) > MAX_CITED_CELLS:
        return []
    query = normalize_sql(sql)
    cited = []
    for i, row in enumerate(rows):
        for column, value in zip(columns, row):
            if value is None:
                continue
            cited.append(
                {
                    "ev_id": evidence_id(source, query, {"row": i, "column": column}),
                    "value": str(value),
                    "label": f'row {i} · "{column}"',
                }
            )
    return cited


def citation_block(cited: list[dict], truncated: bool) -> str:
    """Text appended to a query result so the model can cite values."""
    if not cited:
        reason = "the result was truncated" if truncated else "the result is too large to cite"
        return (
            f"No evidence ids: {reason}. Aggregate further (fewer rows and columns) "
            "to get values you can cite."
        )
    lines = [f"{c['label']} = {c['value']} → {{{{{c['ev_id']}}}}}" for c in cited]
    return (
        "Evidence ids. In your answer write the {{ev:…}} reference, never the value itself:\n"
        + "\n".join(lines)
    )


def append_evidence(
    session: Session,
    ev_id: str,
    value: str,
    *,
    source: str,
    query: str = "",
    label: str = "",
    dataset_id: str = "",
) -> Evidence:
    """Record a fact. Re-recording the current value is a no-op; a different value
    appends a new row and supersedes the old one. Nothing is overwritten."""
    current = current_row(session, ev_id)
    if current and current.value == value:
        return current
    row = Evidence(
        ev_id=ev_id,
        value=value,
        source=source,
        query=query,
        label=label,
        dataset_id=dataset_id,
        created_at=utcnow(),
    )
    session.add(row)
    session.flush()
    if current:
        current.superseded_by = row.row_id
        session.add(current)
    return row


# Same mechanics; named separately so call sites read as a fix, not a first observation.
correct_evidence = append_evidence


def store_cited(session: Session, tool_calls: list[dict], source: str, dataset_id: str) -> None:
    for call in tool_calls:
        for c in call.get("evidence", []):
            append_evidence(
                session,
                c["ev_id"],
                c["value"],
                source=source,
                query=normalize_sql(call["sql"]),
                label=c["label"],
                dataset_id=dataset_id,
            )


def current_row(session: Session, ev_id: str) -> Evidence | None:
    return session.exec(
        select(Evidence).where(Evidence.ev_id == ev_id, Evidence.superseded_by.is_(None))
    ).first()


def current_value(session: Session, ev_id: str) -> str:
    row = current_row(session, ev_id)
    if row is None:
        raise KeyError(ev_id)
    return row.value


def value_history(session: Session, ev_id: str) -> list[str]:
    rows = session.exec(
        select(Evidence).where(Evidence.ev_id == ev_id).order_by(Evidence.row_id)
    ).all()
    return [r.value for r in rows]
