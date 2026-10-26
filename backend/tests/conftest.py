import os
import sys
from pathlib import Path

# Tests must never hit paid/free APIs or the user's DB
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["SQLITE_PATH"] = ":memory:"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
