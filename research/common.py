"""CSV validation, atomic persistence and process locking for the study scripts."""

import csv
import hashlib
import io
import json
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCENARIO_FIELDS = ["scenario_id", "domain", "ground_truth", "loaded_prompt", "neutral_prompt"]
RESPONSE_FIELDS = ["response_id", "scenario_id", "domain", "framing", "model",
                   "response_text", "timestamp", "generation_params"]
BLIND_FIELDS = ["blind_id", "user_prompt", "ai_response", "verdict", "confidence_1_to_5", "reasoning"]
csv.field_size_limit(10_000_000)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def read_csv(path, required, *, exact=False):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)) or not set(required) <= set(fields):
            raise ValueError(f"{path}: missing or duplicate column names; need {required}")
        if exact and fields != required:
            raise ValueError(f"{path}: unexpected columns or order")
        rows = list(reader)
    for index, row in enumerate(rows, 2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"{path}: malformed CSV record {index}")
    return rows


def read_scenarios(path, domains=None):
    rows = read_csv(path, SCENARIO_FIELDS)
    seen = set()
    if not rows:
        raise ValueError("Scenarios CSV is empty. Fill the template with your own scenarios.")
    for row in rows:
        if any(not row[field].strip() for field in SCENARIO_FIELDS):
            raise ValueError("Every scenario needs an ID, domain, ground truth and both prompts.")
        sid = row["scenario_id"]
        if sid != sid.strip() or sid in seen:
            raise ValueError(f"Duplicate or whitespace-padded scenario_id: {sid!r}")
        if domains is not None and row["domain"] not in domains:
            raise ValueError(f"{sid}: domain is not in the configured domains list.")
        if row["loaded_prompt"] == row["neutral_prompt"]:
            raise ValueError(f"{sid}: the two prompts are identical; review the input.")
        seen.add(sid)
    return rows


def csv_bytes(fields, rows):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def atomic_write(path, data):
    """Replace on the same filesystem; a crash leaves either complete version."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                break
            except PermissionError as exc:
                # Windows sync/antivirus readers can briefly block atomic replacement.
                if getattr(exc, "winerror", None) not in {5, 32, 33} or attempt == 4:
                    raise
                time.sleep(0.1 * 2**attempt)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_csv(path, fields, rows):
    atomic_write(path, csv_bytes(fields, rows))


@contextmanager
def study_lock(directory):
    """OS-owned lock releases on process death; keep the file to avoid inode races."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".study.lock").open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError("Another process is using this study directory.") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
