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
