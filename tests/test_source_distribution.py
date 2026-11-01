import base64
import hashlib
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("source_setup", ROOT / "scripts/prepare_sources.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class SourceDistributionTests(unittest.TestCase):
    def test_unicode_insertion_and_deletion_reconstruct_exact_target(self):
        before = "first\n原文\nlast\n".encode()
        after = "first\n新增\nlast\n".encode()
        change = {"base_sha256": module.sha256(before), "target_sha256": module.sha256(after),
                  "edits": [{"start": 6, "end": 13, "insert_base64": base64.b64encode("新增\n".encode()).decode()}]}
        self.assertEqual(module.apply_changes(before, change), after)
        with self.assertRaises(ValueError): module.apply_changes(b"wrong base", change)

    def test_escape_paths_and_overlapping_edits_fail_closed(self):
        for relative in ("../private.json", "/absolute", "C:/private", "a\\..\\private"):
            with self.assertRaises(ValueError): module.safe_path(ROOT, relative)
        change = {"base_sha256": module.sha256(b"abc"), "target_sha256": module.sha256(b"abc"),
                  "edits": [{"start": 2, "end": 3, "insert_base64": ""}, {"start": 0, "end": 1, "insert_base64": ""}]}
        with self.assertRaises(ValueError): module.apply_changes(b"abc", change)

if __name__ == "__main__": unittest.main()
