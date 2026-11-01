"""Setup only: fetch pinned public blobs and apply reviewed text changes.

This downloader is never imported by the application. Existing modified files
must match either the pinned base or the declared output, otherwise fail closed.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile
import os
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

def sha256(data):
    return hashlib.sha256(data).hexdigest()

def blob_sha(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()

def safe_path(root, relative):
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative or ":" in relative:
        raise ValueError("Unsafe distribution path")
    result = root.joinpath(*path.parts)
    if not result.absolute().is_relative_to(root.absolute()):
        raise ValueError("Distribution path escapes its target: " + relative)
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink() or current.is_junction():
            raise ValueError("Linked distribution path rejected: " + relative)
    return result

def canonical(data):
    return data.decode("utf-8").replace("\r\n", "\n").encode("utf-8")

def apply_changes(base, change):
    if sha256(base) != change["base_sha256"]:
        raise ValueError("Pinned source base mismatch")
    end = 0
    result = bytearray()
    for edit in change["edits"]:
        start, stop = edit["start"], edit["end"]
        if not end <= start <= stop <= len(base):
            raise ValueError("Invalid source change offsets")
        result.extend(base[end:start]); result.extend(base64.b64decode(edit["insert_base64"], validate=True))
        end = stop
    result.extend(base[end:])
    result = bytes(result)
    if sha256(result) != change["target_sha256"]:
        raise ValueError("Source reconstruction checksum mismatch")
    return result

def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".source-", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

def prepare(target, cache, *, offline=False, workers=12):
    manifest = json.loads((ROOT / "scripts/upstream-source-manifest.json").read_text(encoding="utf-8"))
    changes = json.loads((ROOT / "source-overlay/source-changes.json").read_text(encoding="utf-8"))
    by_path = {entry["path"]: entry for entry in changes["changes"]}
    if changes["upstream_commit"] != manifest["commit"]:
        raise ValueError("Distribution base commit mismatch")
    def fetch(entry):
        relative = entry["path"]
        path = safe_path(target, relative)
        change = by_path.get(relative)
        if path.exists():
            current = path.read_bytes()
            if change and sha256(canonical(current)) == change["target_sha256"]:
                return
            if blob_sha(current) == entry["sha"]:
                if change:
                    atomic_write(path, apply_changes(canonical(current), change))
                return
            raise ValueError("Existing file differs from both reviewed base and target: " + relative)
        cached = cache / entry["sha"]
        if cached.exists():
            data = cached.read_bytes()
        elif offline:
            raise ValueError("Missing pinned setup cache: " + relative)
        else:
            url = f"https://raw.githubusercontent.com/LifeArchiveProject/WeChatDataAnalysis/{manifest['commit']}/{relative}"
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read(10_000_001)
            if len(data) > 10_000_000 or blob_sha(data) != entry["sha"]:
                raise ValueError("Public source checksum mismatch: " + relative)
            atomic_write(cached, data)
        if blob_sha(data) != entry["sha"]:
            raise ValueError("Pinned setup cache checksum mismatch: " + relative)
        atomic_write(path, apply_changes(canonical(data), change) if change else data)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(fetch, manifest["files"]))
    for entry in changes["new_files"]:
        source = safe_path(ROOT / "source-overlay/files", entry["path"])
        data = canonical(source.read_bytes())
        if sha256(data) != entry["sha256"]:
            raise ValueError("Local source overlay checksum mismatch")
        destination = safe_path(target, entry["path"])
        if destination.exists():
            if sha256(canonical(destination.read_bytes())) != entry["sha256"]:
                raise ValueError("Refusing to overwrite locally edited overlay: " + entry["path"])
        else:
            atomic_write(destination, data)
    return {"public_base_files": len(manifest["files"]), "modified_files": len(by_path), "new_files": len(changes["new_files"])}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, default=ROOT / "upstream_local")
    parser.add_argument("--cache", type=Path, default=ROOT / ".source-cache")
    parser.add_argument("--offline", action="store_true")
    arguments = parser.parse_args()
    print(json.dumps(prepare(arguments.target.resolve(), arguments.cache.resolve(), offline=arguments.offline)))
