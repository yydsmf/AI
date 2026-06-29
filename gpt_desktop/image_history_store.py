import json
import os
import sqlite3
import time

from .core import HISTORY_DIR, IMAGE_HISTORY_FILE, load_json_file


IMAGE_HISTORY_DB_FILE = os.path.join(HISTORY_DIR, "image_history.db")


def _connect():
    os.makedirs(HISTORY_DIR, exist_ok=True)
    conn = sqlite3.connect(IMAGE_HISTORY_DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS image_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at REAL NOT NULL,
            image_path TEXT NOT NULL UNIQUE,
            prompt TEXT NOT NULL DEFAULT '',
            refs_json TEXT NOT NULL DEFAULT '[]',
            result_json TEXT NOT NULL DEFAULT '{}'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_image_history_created_at ON image_history(created_at DESC)")
    return conn


def _valid_image(path):
    try:
        return isinstance(path, str) and os.path.exists(path) and os.path.getsize(path) > 0
    except Exception:
        return False


def init_image_history_store():
    conn = _connect()
    try:
        conn.commit()
    finally:
        conn.close()


def migrate_json_history_once():
    conn = _connect()
    try:
        current = conn.execute("SELECT COUNT(*) FROM image_history").fetchone()[0]
        if current:
            return

        data = load_json_file(IMAGE_HISTORY_FILE, [])
        if not isinstance(data, list):
            return

        base_time = time.time() - len(data)
        for result_index, result in enumerate(data):
            if not isinstance(result, dict):
                continue
            prompt = str(result.get("prompt", "") or "")
            refs = result.get("refs", [])
            if not isinstance(refs, list):
                refs = []
            refs = [p for p in refs if _valid_image(p)]
            images = result.get("images", [])
            if not isinstance(images, list):
                continue
            created_at = base_time + result_index
            for image_path in images:
                if not _valid_image(image_path):
                    continue
                item_result = dict(result)
                item_result["images"] = [image_path]
                item_result["refs"] = refs
                conn.execute(
                    """
                    INSERT OR IGNORE INTO image_history
                    (created_at, image_path, prompt, refs_json, result_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        created_at,
                        image_path,
                        prompt,
                        json.dumps(refs, ensure_ascii=False),
                        json.dumps(item_result, ensure_ascii=False),
                    ),
                )
        conn.commit()
    finally:
        conn.close()


def append_image_result(result):
    if not isinstance(result, dict):
        return 0
    images = result.get("images", [])
    if not isinstance(images, list):
        return 0
    prompt = str(result.get("prompt", "") or "")
    refs = result.get("refs", [])
    if not isinstance(refs, list):
        refs = []
    refs = [p for p in refs if _valid_image(p)]
    created_at = time.time()

    conn = _connect()
    inserted = 0
    try:
        for image_path in images:
            if not _valid_image(image_path):
                continue
            item_result = dict(result)
            item_result["images"] = [image_path]
            item_result["refs"] = refs
            cur = conn.execute(
                """
                INSERT OR REPLACE INTO image_history
                (created_at, image_path, prompt, refs_json, result_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    image_path,
                    prompt,
                    json.dumps(refs, ensure_ascii=False),
                    json.dumps(item_result, ensure_ascii=False),
                ),
            )
            inserted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 1
        conn.commit()
        return inserted
    finally:
        conn.close()


def iter_image_items(limit=30, offset=0, skip_paths=None):
    skip = set()
    for path in skip_paths or []:
        try:
            skip.add(os.path.abspath(path))
        except Exception:
            skip.add(path)

    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT image_path, prompt, refs_json
            FROM image_history
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (int(limit), int(offset)),
        ).fetchall()
    finally:
        conn.close()

    emitted = 0
    for image_path, prompt, refs_json in rows:
        if not _valid_image(image_path):
            continue
        try:
            key = os.path.abspath(image_path)
        except Exception:
            key = image_path
        if key in skip:
            continue
        try:
            refs = json.loads(refs_json or "[]")
        except Exception:
            refs = []
        if not isinstance(refs, list):
            refs = []
        yield image_path, prompt or "", [p for p in refs if _valid_image(p)]
        emitted += 1


def count_images():
    conn = _connect()
    try:
        return int(conn.execute("SELECT COUNT(*) FROM image_history").fetchone()[0])
    finally:
        conn.close()


def remove_image(image_path):
    conn = _connect()
    try:
        conn.execute("DELETE FROM image_history WHERE image_path = ?", (image_path,))
        conn.commit()
    finally:
        conn.close()


def clear_history():
    conn = _connect()
    try:
        conn.execute("DELETE FROM image_history")
        conn.commit()
    finally:
        conn.close()
