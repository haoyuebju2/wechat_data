"""Export reviewed new source files + insertion-only changes, never runtime data."""
import base64
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_sources import apply_changes, blob_sha, canonical, safe_path, sha256

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "upstream_local"
COMMIT = "64664bef316897b0bca2d391be4a6d2c0c472062"
NEW_FILES = {
    "offline-requirements.lock", "offline_backend.py", "offline_context_mcp.py",
    "desktop/src/offline-main.cjs", "desktop/src/offline-session.cjs",
    "desktop/tests/live-chat-e2e.cjs", "desktop/tests/live-chat-fixture.py",
    "desktop/tests/offline-renderer-smoke.cjs", "desktop/tests/offline-session.test.cjs",
    "frontend/components/OfflineAiPanel.vue", "frontend/components/chat/OfflineSnapshotBar.vue",
    "frontend/tests/offline-ai.test.js", "frontend/tests/offline-snapshot.test.js",
    "src/wechat_decrypt_tool/local_key_scan.py", "src/wechat_decrypt_tool/offline_ai.py",
    "src/wechat_decrypt_tool/offline_context_protocol.py", "src/wechat_decrypt_tool/offline_file_watch.py",
    "src/wechat_decrypt_tool/offline_incremental.py", "src/wechat_decrypt_tool/offline_integrity.py",
    "src/wechat_decrypt_tool/offline_policy.py", "src/wechat_decrypt_tool/offline_secrets.py",
    "src/wechat_decrypt_tool/offline_snapshot.py", "src/wechat_decrypt_tool/resources/offline_export_runtime.js",
    "src/wechat_decrypt_tool/routers/offline_ai.py", "src/wechat_decrypt_tool/routers/offline_snapshot.py",
    "src/wechat_decrypt_tool/routers/offline_wrapped.py",
}

def git(*args):
    return subprocess.check_output(["git", "-C", str(UPSTREAM), *args])

def build():
    manifest = json.loads((ROOT / "scripts/upstream-source-manifest.json").read_text(encoding="utf-8"))
    entries = {entry["path"]: entry for entry in manifest["files"]}
    if git("rev-parse", "HEAD").decode().strip() != COMMIT:
        raise ValueError("Unexpected upstream base")
    modified = git("diff", "--name-only", "HEAD").decode().splitlines()
    changes = []
    cache = ROOT / ".source-cache"
    for relative in modified:
        if relative not in entries:
            raise ValueError("Modified file missing from public base manifest: " + relative)
        original = git("show", f"{COMMIT}:{relative}")
        if blob_sha(original) != entries[relative]["sha"]:
            raise ValueError("Pinned Git base differs")
        cache.mkdir(exist_ok=True)
        (cache / entries[relative]["sha"]).write_bytes(original)
        base = canonical(original)
        target = canonical(safe_path(UPSTREAM, relative).read_bytes())
        # Line-level diff keeps only inserted/replacement text. Deleted original
        # source is represented by byte offsets, not copied into the repository.
        old_lines, new_lines = base.splitlines(keepends=True), target.splitlines(keepends=True)
        offsets = [0]
        for line in old_lines: offsets.append(offsets[-1] + len(line))
        edits = [{"start": offsets[i], "end": offsets[j], "insert_base64": base64.b64encode(b"".join(new_lines[a:b])).decode()}
                 for operation, i, j, a, b in difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_opcodes()
                 if operation != "equal"]
        change = {"path": relative, "base_sha256": sha256(base), "target_sha256": sha256(target), "edits": edits}
        assert apply_changes(base, change) == target
        changes.append(change)
    new_files = []
    approved = NEW_FILES | {path.relative_to(UPSTREAM).as_posix() for path in (UPSTREAM / "tests_offline").glob("*.py")}
    for relative in sorted(approved):
        source = safe_path(UPSTREAM, relative)
        content = canonical(source.read_bytes())
        target = safe_path(ROOT / "source-overlay/files", relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        new_files.append({"path": relative, "sha256": sha256(content)})
    output = {"format": "wechat-local-source-changes/1", "upstream_commit": COMMIT,
              "changes": changes, "new_files": new_files}
    (ROOT / "source-overlay/source-changes.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"modified_files": len(changes), "new_files": len(new_files)}))

if __name__ == "__main__": build()
