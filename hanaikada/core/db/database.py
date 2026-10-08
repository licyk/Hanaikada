"""SQLite storage with numbered migrations."""

import json
import logging
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# The full-text table and its triggers. Kept apart from MIGRATIONS because it is created only when
# this SQLite has FTS5 with the trigram tokenizer (3.34+); without it search falls back to LIKE.
FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS images_fts USING fts5(
    prompt, negative_prompt, name, model_name, loras,
    content='images', content_rowid='id', tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS images_fts_insert AFTER INSERT ON images BEGIN
    INSERT INTO images_fts(rowid, prompt, negative_prompt, name, model_name, loras)
    VALUES (new.id, new.prompt, new.negative_prompt, new.name, new.model_name, new.loras);
END;
CREATE TRIGGER IF NOT EXISTS images_fts_delete AFTER DELETE ON images BEGIN
    INSERT INTO images_fts(images_fts, rowid, prompt, negative_prompt, name, model_name, loras)
    VALUES ('delete', old.id, old.prompt, old.negative_prompt, old.name, old.model_name, old.loras);
END;
CREATE TRIGGER IF NOT EXISTS images_fts_update AFTER UPDATE OF prompt, negative_prompt, name, model_name, loras ON images BEGIN
    INSERT INTO images_fts(images_fts, rowid, prompt, negative_prompt, name, model_name, loras)
    VALUES ('delete', old.id, old.prompt, old.negative_prompt, old.name, old.model_name, old.loras);
    INSERT INTO images_fts(rowid, prompt, negative_prompt, name, model_name, loras)
    VALUES (new.id, new.prompt, new.negative_prompt, new.name, new.model_name, new.loras);
END;
"""

# Each entry is one migration. Append only; never edit a released entry.
MIGRATIONS: list[str] = [
    # 1
    """
    CREATE TABLE images (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        root_id          TEXT NOT NULL,
        rel_path         TEXT NOT NULL,
        dir              TEXT NOT NULL,
        name             TEXT NOT NULL,
        ext              TEXT NOT NULL,
        size             INTEGER NOT NULL,
        mtime_ns         INTEGER NOT NULL,
        ctime_ns         INTEGER,
        width            INTEGER,
        height           INTEGER,
        format           TEXT,
        platform         TEXT,
        platform_version TEXT,
        family           TEXT,
        prompt           TEXT,
        negative_prompt  TEXT,
        seed             INTEGER,
        steps            INTEGER,
        cfg_scale        REAL,
        distilled_cfg    REAL,
        sampler          TEXT,
        sampler_norm     TEXT,
        scheduler        TEXT,
        denoise          REAL,
        clip_skip        INTEGER,
        model_name       TEXT,
        model_hash       TEXT,
        vae_name         TEXT,
        loras            TEXT,
        gen_width        INTEGER,
        gen_height       INTEGER,
        mode             TEXT,
        info             TEXT NOT NULL,
        parse_error      TEXT,
        indexed_at       TEXT NOT NULL,
        missing_since    TEXT,
        UNIQUE(root_id, rel_path)
    );
    CREATE INDEX images_dir ON images(root_id, dir, mtime_ns DESC);
    CREATE INDEX images_mtime ON images(mtime_ns DESC, id DESC);
    CREATE INDEX images_model ON images(model_name);
    CREATE INDEX images_seed ON images(seed);
    CREATE INDEX images_platform ON images(platform);
    CREATE INDEX images_sampler ON images(sampler_norm);

    CREATE TABLE image_text (
        image_id  INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
        key       TEXT NOT NULL,
        value     TEXT NOT NULL,
        source    TEXT,
        truncated INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (image_id, key)
    );

    CREATE TABLE tags (
        id     INTEGER PRIMARY KEY AUTOINCREMENT,
        name   TEXT NOT NULL,
        type   TEXT NOT NULL,
        color  TEXT,
        count  INTEGER NOT NULL DEFAULT 0,
        UNIQUE(name, type)
    );
    CREATE INDEX tags_type ON tags(type, count DESC);

    CREATE TABLE image_tags (
        image_id   INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
        tag_id     INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        PRIMARY KEY (image_id, tag_id)
    );
    CREATE INDEX image_tags_tag ON image_tags(tag_id, image_id);
    CREATE TRIGGER image_tags_count_insert AFTER INSERT ON image_tags BEGIN
        UPDATE tags SET count = count + 1 WHERE id = new.tag_id;
    END;
    CREATE TRIGGER image_tags_count_delete AFTER DELETE ON image_tags BEGIN
        UPDATE tags SET count = count - 1 WHERE id = old.tag_id;
    END;

    CREATE TABLE folders (
        root_id    TEXT NOT NULL,
        rel_path   TEXT NOT NULL,
        parent     TEXT,
        mtime_ns   INTEGER NOT NULL,
        scanned_at TEXT NOT NULL,
        PRIMARY KEY (root_id, rel_path)
    );
    CREATE INDEX folders_parent ON folders(root_id, parent);

    CREATE TABLE client_state (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    INSERT INTO tags(name, type, color) VALUES ('favorite', 'custom', NULL);
    """,
]


def fts_available() -> bool:
    """Whether this SQLite has FTS5 with the trigram tokenizer (SQLite 3.34 or newer)."""
    try:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return True


class Database:
    """One shared connection guarded by a lock. Fine for a single local process."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path) if path != ":memory:" else path
        if isinstance(self.path, Path):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        self.created = self.schema_version == 0
        self.migrate()
        self.fts = self._ensure_fts()

    @property
    def schema_version(self) -> int:
        return int(self._conn.execute("PRAGMA user_version").fetchone()[0])

    def migrate(self) -> None:
        with self._lock:
            current = self.schema_version
            for number, script in enumerate(MIGRATIONS, start=1):
                if number <= current:
                    continue
                self._conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {number};\nCOMMIT;")

    def _ensure_fts(self) -> bool:
        if not fts_available():
            logger.warning("This SQLite has no FTS5 trigram tokenizer; text search uses LIKE instead")
            return False
        with self._lock:
            exists = self._conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'images_fts'").fetchone() is not None
            self._conn.executescript(f"BEGIN;\n{FTS_SCHEMA}\nCOMMIT;")
            if not exists and self._conn.execute("SELECT 1 FROM images LIMIT 1").fetchone() is not None:
                self._conn.execute("INSERT INTO images_fts(images_fts) VALUES ('rebuild')")
        return True

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] | dict[str, Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def fetchone(self, sql: str, params: tuple[Any, ...] | list[Any] | dict[str, Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple[Any, ...] | list[Any] | dict[str, Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- client state --------------------------------------------------------

    def get_client_state(self, key: str) -> Any:
        row = self.fetchone("SELECT value FROM client_state WHERE key = ?", (key,))
        return None if row is None else json.loads(row["value"])

    def set_client_state(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO client_state(key, value, updated_at) VALUES (?, ?, datetime('now')) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, json.dumps(value)),
        )
