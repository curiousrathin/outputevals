import hashlib
import io
from pathlib import Path

import pandas as pd

from app.config import settings

# CSVs up to this (estimated) size are pasted into the prompt verbatim; larger
# ones are queried through SQL. Claude's context window is 1M tokens and the
# estimate below runs high, so this leaves room for instructions and answers.
MAX_INLINE_TOKENS = 600_000


class CSVError(ValueError):
    pass


def dataset_path(dataset_id: str) -> Path:
    return settings.data_dir / "datasets" / f"{dataset_id}.csv"


def decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def estimate_tokens(text: str) -> int:
    return len(text) // 3  # CSVs are digit/punctuation heavy; err on the high side


def _dtype(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"
    return "text"


def profile(raw: bytes) -> tuple[pd.DataFrame, list[dict]]:
    try:
        df = pd.read_csv(io.StringIO(decode(raw)))
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as e:
        raise CSVError(f"Couldn't parse CSV: {e}") from e
    if df.empty or len(df.columns) == 0:
        raise CSVError("CSV has no rows.")

    columns = []
    for name in df.columns:
        series = df[name]
        samples = series.dropna().astype(str).unique()[:3].tolist()
        columns.append(
            {
                "name": str(name),
                "dtype": _dtype(series),
                "non_null": int(series.notna().sum()),
                "unique": int(series.nunique()),
                "samples": samples,
            }
        )
    return df, columns


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_text(dataset_id: str) -> str:
    """The original file, byte-for-byte decoded: exactly what the baseline arm sees."""
    return decode(dataset_path(dataset_id).read_bytes())


def preview(dataset_id: str, limit: int = 50) -> dict:
    df = pd.read_csv(io.StringIO(read_text(dataset_id)), nrows=limit)
    df = df.astype(object).where(df.notna(), None)
    return {"columns": [str(c) for c in df.columns], "rows": df.values.tolist()}
