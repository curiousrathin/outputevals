from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_prefix="OT_", extra="ignore")

    data_dir: Path = ROOT / "data"
    database_url: str = f"sqlite:///{ROOT / 'data' / 'outputtracker.db'}"

    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "medium"  # low | medium | high | xhigh | max
    judge_model: str = "claude-opus-5-5"
    embedding_model: str = "BAAI/bge-small-en-v1.5"

    cors_origins: list[str] = ["http://localhost:5173"]


settings = Settings()
