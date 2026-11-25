from pathlib import Path

from sqlalchemy import create_engine

DATABASE_PATH = Path(__file__).resolve().parents[1] / "editor.sqlite3"
engine = create_engine(f"sqlite:///{DATABASE_PATH}", hide_parameters=True)
