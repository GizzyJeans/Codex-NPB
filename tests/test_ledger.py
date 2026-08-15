import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_npb.ledger import LedgerError, append, verify  # noqa: E402


class LedgerTests(unittest.TestCase):
    def test_rejects_reserved_chain_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            with self.assertRaisesRegex(LedgerError, "reserved keys"):
                append(path, {"event_type": "bad", "sequence": 99})

    def test_append_verify_and_detect_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            append(path, {"event_type": "historical_import", "value": 1})
            append(path, {"event_type": "settlement", "value": 2})
            self.assertEqual(len(verify(path)), 2)

            rows = path.read_text(encoding="utf-8").splitlines()
            first = json.loads(rows[0])
            first["value"] = 9
            rows[0] = json.dumps(first)
            path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(LedgerError, "hash mismatch"):
                verify(path)


if __name__ == "__main__":
    unittest.main()
