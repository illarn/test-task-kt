import sqlite3
from contextlib import closing
from pathlib import Path

from app.database import DATABASE_PATH


def main() -> None:
    migration = Path(__file__).resolve().parents[1] / "migrations/001_initial.sql"
    with closing(sqlite3.connect(DATABASE_PATH)) as db:
        db.executescript(migration.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
