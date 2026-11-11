"""Offline private-server backup and retention. Stop the API before running.

python -m backend.maintenance --backup release-backups/studio.zip
python -m backend.maintenance --prune-days 30           # dry run
python -m backend.maintenance --prune-days 30 --apply   # explicit deletion
"""
import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import time
import uuid
import zipfile
from dotenv import load_dotenv


def job_directory(root: Path, job_id: str) -> Path:
    if str(uuid.UUID(job_id)) != job_id:
        raise ValueError("Invalid job directory")
    target = root / job_id
    if target.is_symlink() or target.resolve().parent != root.resolve():
        raise ValueError("Job directory must stay inside the data volume")
    return target


def backup(root: Path, destination: Path):
    root = root.resolve(); destination = destination.resolve()
    if destination.is_relative_to(root):
        raise ValueError("Save backups outside the data volume")
    if not (root / "jobs.sqlite3").is_file():
        raise ValueError("No existing studio database found")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental replacement of a previous backup.
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in root.rglob("*"):
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError("Data volume contains an external link")
            if path.is_file():
                archive.write(path, path.relative_to(root).as_posix())
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ValueError("Backup verification failed")


def prune(root: Path, days: int, apply: bool = False) -> list[str]:
    if days < 1:
        raise ValueError("Retention must be at least one day")
    database = root / "jobs.sqlite3"
    if not database.is_file():
        raise ValueError("No existing studio database found")
    removed = []
    with sqlite3.connect(database) as connection:
        for job_id, payload in connection.execute("SELECT id, payload FROM jobs").fetchall():
            job = json.loads(payload)
            if job["status"] not in ("COMPLETED", "FAILED", "CANCELLED"):
                continue
            if job.get("updated_at", time.time()) >= time.time() - days * 86400:
                continue
            target = job_directory(root, job_id)
            if apply:
                if target.exists():
                    shutil.rmtree(target)
                connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            removed.append(job_id)
    return removed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--backup", type=Path)
    action.add_argument("--prune-days", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    load_dotenv()
    from backend.config import settings
    if args.backup:
        backup(settings.DATA_DIR, args.backup)
        print("Backup created and archive integrity verified. Keep it private: it contains source images and models.")
    else:
        jobs = prune(settings.DATA_DIR, args.prune_days, args.apply)
        print(json.dumps({"mode": "deleted" if args.apply else "dry-run", "jobIds": jobs}))


if __name__ == "__main__":
    main()
