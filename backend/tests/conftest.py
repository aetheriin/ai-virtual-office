import os
import sys
import tempfile
from pathlib import Path

# Tests must never hit paid/free APIs or the user's DB
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["SQLITE_PATH"] = ":memory:"
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/projects.db"
os.environ["ENABLE_NEWS"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


import dataclasses  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture
def patch_settings(monkeypatch):
    """Settings is a frozen dataclass imported by name: swap the object in every app module."""
    def apply(**kw):
        from app import config
        old = config.settings
        new = dataclasses.replace(old, **kw)
        for name, mod in list(sys.modules.items()):
            if (name == "app" or name.startswith("app.")) and getattr(mod, "settings", None) is old:
                monkeypatch.setattr(mod, "settings", new)
        return new
    return apply
