"""Durable SQLite jobs for a single-worker GPU server; no simulated progress."""
import json
import sqlite3
import threading
import time
from pathlib import Path

class JobStore:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(directory / "jobs.sqlite3", check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.db.commit()

    def save(self, job):
        with self.lock:
            job["updated_at"] = time.time()
            self.db.execute("INSERT OR REPLACE INTO jobs VALUES (?, ?)", (job["job_id"], json.dumps(job)))
            self.db.commit()
        return job

    def get(self, job_id):
        with self.lock:
            row = self.db.execute("SELECT payload FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def all(self):
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM jobs")]

    def update(self, job_id, **fields):
        with self.lock:
            job = self.get(job_id)
            if not job:
                raise KeyError(job_id)
            if job["status"] == "CANCELLED":
                return job
            return self.save({**job, **fields})
