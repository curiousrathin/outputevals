from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_prefix="OT_", extra="ignore")

    data_dir: Path = ROOT / "data"
    database_url: str = f"sqlite:///{ROOT / 'data' / 'outputtracker.db'}"
    # Skill library (Markdown on disk). Defaults to data/library, which is gitignored so
    # client knowledge stays out of this repo; point it at its own git repo to version it.
    library_dir: Path | None = None

    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "medium"  # low | medium | high | xhigh | max
    # Extra or overriding prices for the cost eval (USD per million tokens); see evals/pricing.py.
    model_prices: dict[str, dict[str, float]] = {}
    judge_model: str = "claude-opus-5-5"
    embedding_model: str = "BAAI/bge-small-en-v1.5"

    cors_origins: list[str] = ["http://localhost:5173"]


settings = Settings()
