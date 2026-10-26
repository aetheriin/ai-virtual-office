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
    alpha_vantage_api_key: str = os.getenv("ALPHA_VANTAGE_API_KEY", "")
    finnhub_api_key: str = os.getenv("FINNHUB_API_KEY", "")
    news_rss_feeds: list[str] = field(
        default_factory=lambda: [u.strip() for u in os.getenv(
            "NEWS_RSS_FEEDS", "https://www.fxstreet.com/rss/news,https://www.investing.com/rss/news_1.rss"
        ).split(",") if u.strip()]
    )
    news_lookback_hours: float = _float("NEWS_LOOKBACK_HOURS", 24)
    news_use_llm: bool = _bool("NEWS_USE_LLM", True)
    enable_news: bool = _bool("ENABLE_NEWS", True)
    # Demo only: invent candles when no live source answers. Off by default so a typo in a ticker
    # gives a clear "not found" error instead of a convincing-looking fake chart.
    allow_synthetic_data: bool = _bool("ALLOW_SYNTHETIC_DATA", False)
    # MetaTrader5: brokers rename symbols (XAUUSDm, XAUUSD.r ...). JSON map and/or suffix; auto-detect otherwise.
    mt5_symbol_map: str = os.getenv("MT5_SYMBOL_MAP", "")
    mt5_symbol_suffix: str = os.getenv("MT5_SYMBOL_SUFFIX", "")

    default_capital: float = _float("DEFAULT_CAPITAL", 10_000_000)
    default_risk_pct: float = _float("DEFAULT_RISK_PCT", 1.0)
    min_rr: float = _float("MIN_RR", 1.5)
    # TP1 (nearest resistance) must be at least this many R away; lower it to accept trades closer to resistance
    min_rr_tp1: float = _float("MIN_RR_TP1", 1.0)
    max_daily_loss_pct: float = _float("MAX_DAILY_LOSS_PCT", 3.0)

    cors_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
    )
    sqlite_path: str = os.getenv("SQLITE_PATH", str(ROOT / "backend" / "office.db"))
    # PostgreSQL for IT project data, e.g. postgresql://office:office@localhost:5432/office
    # Empty -> local SQLite file (backend/projects.db) so the app still runs without a DB server.
    database_url: str = os.getenv("DATABASE_URL", "")
    db_auto_migrate: bool = _bool("DB_AUTO_MIGRATE", True)

    # GitHub pull requests from the IT department (fine-grained token: Contents + Pull requests read/write)
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    github_api_url: str = os.getenv("GITHUB_API_URL", "https://api.github.com")
    auto_pr: bool = _bool("AUTO_PR", True)
    # Without an LLM the coders emit generic templates; don't push those to real repos unless asked
    allow_template_pr: bool = _bool("ALLOW_TEMPLATE_PR", False)
    pr_branch_prefix: str = os.getenv("PR_BRANCH_PREFIX", "ai/")
    pr_max_files: int = int(_float("PR_MAX_FILES", 40))
    pr_max_file_kb: float = _float("PR_MAX_FILE_KB", 200)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openrouter_api_key or self.gemini_api_key)


settings = Settings()
