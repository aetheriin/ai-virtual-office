"""Runtime configuration loaded from environment / .env (secrets never hard-coded)."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "backend" / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    model_pm: str = os.getenv("MODEL_PM", "google/gemma-3-27b-it:free")
    model_risk: str = os.getenv("MODEL_RISK", "google/gemma-3-27b-it:free")
    model_coder: str = os.getenv("MODEL_CODER", "qwen/qwen-2.5-coder-32b-instruct:free")
    model_debate: str = os.getenv("MODEL_DEBATE", "meta-llama/llama-3.1-8b-instruct:free")

    twelve_data_api_key: str = os.getenv("TWELVE_DATA_API_KEY", "")
    allow_synthetic_data: bool = _bool("ALLOW_SYNTHETIC_DATA", True)

    default_capital: float = _float("DEFAULT_CAPITAL", 10_000_000)
    default_risk_pct: float = _float("DEFAULT_RISK_PCT", 1.0)
    min_rr: float = _float("MIN_RR", 1.5)
    max_daily_loss_pct: float = _float("MAX_DAILY_LOSS_PCT", 3.0)

    cors_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
    )
    sqlite_path: str = os.getenv("SQLITE_PATH", str(ROOT / "backend" / "office.db"))

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openrouter_api_key or self.gemini_api_key)


settings = Settings()
