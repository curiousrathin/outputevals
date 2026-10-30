"""Find numbers an answer states without citing evidence.

The resolver only checks the {{ev:…}} references that are present, so a number
typed straight into the answer would render unchecked. This scans the draft for
numbers outside references and reports each one, unless it also appears in the
question (a year or an invoice number the user typed).

Ignored: references, code (`inline` or fenced), and list markers like "1." at
the start of a line. Dates split into parts (7/13/2026 → 7, 13, 2026), which is
intended: a date from the data should be cited too.
"""

import re

REF = re.compile(r"\{\{ev:[0-9a-f]+\}\}")
CODE = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)
LIST_MARKER = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)
NUMBER = re.compile(r"(?<![\w.])[$€£]?\d[\d,]*(?:\.\d+)?%?(?!\w)")


def canonical(token: str) -> str | None:
    """'$149,410.09' → '149410.09'; '12.50%' → '12.5'; '2026' → '2026'."""
    raw = token.strip("$€£%").replace(",", "")
    try:
        n = float(raw)
    except ValueError:
        return None
    return str(int(n)) if n.is_integer() else repr(n)


def numbers_in(text: str) -> list[str]:
    return [m.group(0).rstrip(",") for m in NUMBER.finditer(text)]


def unsourced_numbers(draft: str, question: str, query_values: list[str]) -> list[dict]:
    """[{number, matches_query}] for each number typed outside a reference.

    `matches_query` is True when the number equals a value some query returned:
    typed instead of cited, which bypasses the check but isn't invented.
    """
    text = LIST_MARKER.sub("", CODE.sub(" ", REF.sub(" ", draft)))
    allowed = {canonical(t) for t in numbers_in(question)}
    known = {canonical(v) for v in query_values}
    out = []
    for token in numbers_in(text):
        c = canonical(token)
        if c is None or c in allowed:
            continue
        out.append({"number": token, "matches_query": c in known})
    return out
