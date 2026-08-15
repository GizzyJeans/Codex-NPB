from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


ZERO_HASH = "0" * 64


class LedgerError(ValueError):
    pass


def canonical_json(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def record_hash(record: dict) -> str:
    payload = {key: value for key, value in record.items() if key != "record_hash"}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def verify(path: Path) -> list[dict]:
    previous_hash = ZERO_HASH
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise LedgerError(f"{path}:{line_number}: invalid JSON") from exc
            if record.get("sequence") != len(records) + 1:
                raise LedgerError(f"{path}:{line_number}: broken sequence")
            if record.get("previous_hash") != previous_hash:
                raise LedgerError(f"{path}:{line_number}: broken previous hash")
            expected = record_hash(record)
            if record.get("record_hash") != expected:
                raise LedgerError(f"{path}:{line_number}: hash mismatch")
            records.append(record)
            previous_hash = expected
    return records


def append(path: Path, payload: dict) -> dict:
    reserved = {"sequence", "previous_hash", "record_hash"}
    conflicts = reserved.intersection(payload)
    if conflicts:
        raise LedgerError(f"payload uses reserved keys: {', '.join(sorted(conflicts))}")
    existing = verify(path) if path.exists() else []
    previous_hash = existing[-1]["record_hash"] if existing else ZERO_HASH
    record = {
        "sequence": len(existing) + 1,
        **payload,
        "previous_hash": previous_hash,
    }
    record["record_hash"] = record_hash(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(record) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Codex-NPB hash-chain ledger")
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        records = verify(args.path)
    except (OSError, LedgerError) as exc:
        print(f"Integrity failed: {exc}")
        return 2
    print(f"Integrity OK: {len(records)} records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
