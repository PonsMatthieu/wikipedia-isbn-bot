"""État persistant et historique. Pas de WAL : compatible avec le NFS Toolforge."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


@contextmanager
def run_lock(data_dir: Path):
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = data_dir / "run.lock"
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise RuntimeError("Une opération est déjà verrouillée. Voir docs/OPERATIONS.md") from exc
    try:
        (lock / "owner.json").write_text(dumps({"pid": os.getpid(), "created_at": now()}), encoding="utf-8")
        yield
    finally:
        (lock / "owner.json").unlink(missing_ok=True)
        lock.rmdir()


class State:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY, page_id INTEGER NOT NULL, title TEXT NOT NULL,
          category_timestamp TEXT NOT NULL, created_at TEXT NOT NULL,
          status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
          last_error TEXT, next_retry TEXT
        );
        CREATE TABLE IF NOT EXISTS memberships (
          page_id INTEGER PRIMARY KEY, title TEXT NOT NULL, category_timestamp TEXT NOT NULL,
          event_id INTEGER NOT NULL REFERENCES events(id), active INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS findings (
          id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES events(id),
          locator TEXT NOT NULL, page_json TEXT NOT NULL, finding_json TEXT NOT NULL,
          diff TEXT NOT NULL, status TEXT NOT NULL, selected_isbn TEXT,
          approved_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(event_id, locator)
        );
        CREATE TABLE IF NOT EXISTS edits (
          id INTEGER PRIMARY KEY, finding_id INTEGER NOT NULL UNIQUE REFERENCES findings(id),
          old_revid INTEGER NOT NULL, new_revid INTEGER, new_hash TEXT NOT NULL,
          summary TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL,
          error_code TEXT
        );
        CREATE TABLE IF NOT EXISTS cache (
          key TEXT PRIMARY KEY, value TEXT NOT NULL, created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS alerts (
          id INTEGER PRIMARY KEY, code TEXT NOT NULL, message TEXT NOT NULL,
          created_at TEXT NOT NULL, sent_at TEXT
        );
        """)
        self.db.commit()

    def close(self):
        self.db.close()

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))

    def sync_memberships(self, members: list[dict], process_existing: bool = False) -> dict:
        """Un snapshot complet est obligatoire : ne jamais marquer les absents sur une page API partielle."""
        first = self.get_meta("baseline_done") is None
        added, removed = 0, 0
        with self.db:
            current = {row["pageid"] for row in members}
            for row in members:
                pid, title, ts = row["pageid"], row["title"], row["timestamp"]
                previous = self.db.execute("SELECT * FROM memberships WHERE page_id=?", (pid,)).fetchone()
                changed = previous is None or not previous["active"] or previous["category_timestamp"] != ts
                if changed:
                    if previous is not None:
                        self.db.execute("UPDATE events SET status='SUPERSEDED' WHERE id=? AND status!='EDITED'", (previous["event_id"],))
                        self.db.execute("UPDATE findings SET status='STALE',updated_at=? WHERE event_id=? AND status IN ('NEEDS_REVIEW','APPROVED','NO_CANDIDATE')", (now(), previous["event_id"]))
                    status = "BASELINE" if first and not process_existing else "NEW"
                    cursor = self.db.execute(
                        "INSERT INTO events(page_id,title,category_timestamp,created_at,status) VALUES (?,?,?,?,?)",
                        (pid, title, ts, now(), status),
                    )
                    self.db.execute("INSERT OR REPLACE INTO memberships VALUES (?,?,?,?,1)", (pid, title, ts, cursor.lastrowid))
                    added += 1
                else:
                    self.db.execute("UPDATE memberships SET title=? WHERE page_id=?", (title, pid))
            for previous in self.db.execute("SELECT * FROM memberships WHERE active=1").fetchall():
                if previous["page_id"] in current:
                    continue
                self.db.execute("UPDATE memberships SET active=0 WHERE page_id=?", (previous["page_id"],))
                self.db.execute("UPDATE events SET status='RESOLVED_EXTERNALLY' WHERE id=? AND status!='EDITED'", (previous["event_id"],))
                self.db.execute("UPDATE findings SET status='STALE',updated_at=? WHERE event_id=? AND status IN ('NEEDS_REVIEW','APPROVED','NO_CANDIDATE')", (now(), previous["event_id"]))
                removed += 1
            if first:
                self.db.execute("INSERT INTO meta VALUES ('baseline_done',?)", (now(),))
        return {"baseline": first, "seen": len(members), "added": added, "removed": removed}

    def queue_existing(self, limit: int) -> int:
        with self.db:
            ids = [r[0] for r in self.db.execute(
                "SELECT e.id FROM events e JOIN memberships m ON m.event_id=e.id WHERE e.status='BASELINE' AND m.active=1 ORDER BY e.id LIMIT ?", (limit,)
            )]
            self.db.executemany("UPDATE events SET status='NEW' WHERE id=?", [(i,) for i in ids])
        return len(ids)

    def add_manual_event(self, page_id: int, title: str) -> int:
        with self.db:
            c = self.db.execute("INSERT INTO events(page_id,title,category_timestamp,created_at,status) VALUES (?,?,?,?,?)", (page_id, title, "manual:" + uuid4().hex, now(), "NEW"))
        return c.lastrowid

    def pending_events(self, limit: int):
        # Un crash pendant l'analyse est rejouable. Les soumissions ne le sont pas.
        return self.db.execute("SELECT * FROM events WHERE status IN ('NEW','ANALYSING') OR (status='FAILED' AND attempts<4 AND next_retry<=?) ORDER BY id LIMIT ?", (now(), limit)).fetchall()

    def event_status(self, event_id: int, status: str, error: str | None = None, next_retry: str | None = None):
        with self.db:
            self.db.execute("UPDATE events SET status=?,last_error=?,next_retry=?,attempts=attempts+? WHERE id=?", (status, error, next_retry, int(status == "ANALYSING"), event_id))

    def save_finding(self, event_id: int, page: dict, finding: dict, diff: str) -> int:
        locator = f"t{finding['field']['template_index']}:p{finding['field']['parameter_index']}"
        with self.db:
            # Analyse interrompue : seules les propositions non approuvées peuvent être remplacées.
            old = self.db.execute("SELECT id,status FROM findings WHERE event_id=? AND locator=?", (event_id, locator)).fetchone()
            if old and old["status"] in {"APPROVED", "EDITED", "SUBMITTING", "UNKNOWN_SUBMISSION"}:
                return old["id"]
            self.db.execute("""INSERT INTO findings(event_id,locator,page_json,finding_json,diff,status,created_at,updated_at)
              VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(event_id,locator) DO UPDATE SET
              page_json=excluded.page_json,finding_json=excluded.finding_json,diff=excluded.diff,
              status=excluded.status,updated_at=excluded.updated_at""", (event_id, locator, dumps(page), dumps(finding), diff, finding["status"], now(), now()))
        return self.db.execute("SELECT id FROM findings WHERE event_id=? AND locator=?", (event_id, locator)).fetchone()[0]

    def finding(self, finding_id: int):
        row = self.db.execute("SELECT * FROM findings WHERE id=?", (finding_id,)).fetchone()
        if row is None:
            raise ValueError(f"Proposition {finding_id} introuvable")
        return dict(row)

    def findings(self, statuses: tuple[str, ...] = ()) -> list[dict]:
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            rows = self.db.execute(f"SELECT * FROM findings WHERE status IN ({placeholders}) ORDER BY id", statuses)
        else:
            rows = self.db.execute("SELECT * FROM findings ORDER BY id")
        return [dict(r) for r in rows]

    def approve(self, finding_id: int, isbn: str, operator: str, finding: dict, diff: str):
        row = self.finding(finding_id)
        if row["status"] != "NEEDS_REVIEW":
            raise ValueError("Seule une proposition NEEDS_REVIEW peut être approuvée")
        with self.db:
            self.db.execute("UPDATE findings SET status='APPROVED',selected_isbn=?,approved_by=?,finding_json=?,diff=?,updated_at=? WHERE id=?", (isbn, operator, dumps(finding), diff, now(), finding_id))

    def set_finding_status(self, finding_id: int, status: str):
        with self.db:
            self.db.execute("UPDATE findings SET status=?,updated_at=? WHERE id=?", (status, now(), finding_id))

    def begin_edit(self, finding_id: int, old_revid: int, new_hash: str, summary: str):
        with self.db:
            self.db.execute("INSERT INTO edits(finding_id,old_revid,new_hash,summary,state,created_at) VALUES (?,?,?,?,?,?)", (finding_id, old_revid, new_hash, summary, "SUBMITTING", now()))
            self.db.execute("UPDATE findings SET status='SUBMITTING',updated_at=? WHERE id=?", (now(), finding_id))

    def finish_edit(self, finding_id: int, state: str, new_revid: int | None = None, error_code: str | None = None):
        with self.db:
            self.db.execute("UPDATE edits SET state=?,new_revid=?,error_code=? WHERE finding_id=?", (state, new_revid, error_code, finding_id))
            self.db.execute("UPDATE findings SET status=?,updated_at=? WHERE id=?", (state, now(), finding_id))

    def alert(self, code: str, message: str):
        with self.db:
            self.db.execute("INSERT INTO alerts(code,message,created_at) VALUES (?,?,?)", (code, message, now()))

    def edit_errors(self) -> int:
        rows = self.db.execute("SELECT state FROM edits ORDER BY id DESC LIMIT 10").fetchall()
        return sum(r[0] in {"EDIT_FAILED", "UNKNOWN_SUBMISSION", "SUBMITTING"} for r in rows)

    def stats(self) -> dict:
        return {
            "events": {r[0]: r[1] for r in self.db.execute("SELECT status,count(*) FROM events GROUP BY status")},
            "findings": {r[0]: r[1] for r in self.db.execute("SELECT status,count(*) FROM findings GROUP BY status")},
            "last_success": self.get_meta("last_success"),
            "write_halted": self.get_meta("write_halted"),
        }
