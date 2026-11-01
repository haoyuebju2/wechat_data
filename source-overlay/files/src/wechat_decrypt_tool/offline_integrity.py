"""Auditable local export assets/digests. No upstream publisher-signature claim."""
import hashlib
import html
import json
from pathlib import Path


class LocalIntegrity:
    @staticmethod
    def export_css(kind):
        return "body{font:15px system-ui,sans-serif;max-width:1100px;margin:24px auto;padding:16px;color:#253238}img,video{max-width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere}.message{padding:12px;border-bottom:1px solid #ddd}"

    @staticmethod
    def runtime_js():
        return (Path(__file__).parent / "resources/offline_export_runtime.js").read_text(encoding="utf-8")

    @staticmethod
    def asset_paths(export_id):
        return json.dumps(["assets/local-export.css", "assets/local-export.js", "assets/local-digests.js"])

    @staticmethod
    def integrity_sidecar_paths(export_id):
        return json.dumps(["_integrity/local-manifest.json", "_integrity/local-sha256.txt"])

    @staticmethod
    def gate_style():
        return '<meta http-equiv="Content-Security-Policy" content="default-src \'self\' data: blob:; connect-src \'none\'; img-src \'self\' data: blob:; media-src \'self\' data: blob:; script-src \'self\' \'unsafe-inline\'; style-src \'self\' \'unsafe-inline\'; object-src \'none\'; frame-src \'none\'; form-action \'none\'; base-uri \'none\'">'

    @staticmethod
    def attribution_html():
        return "<footer>本机离线导出 · 完整性文件为本地 SHA-256 校验，不是上游签名</footer>"

    @staticmethod
    def integrity_script_tag(src):
        return '<script defer src="' + html.escape(src, quote=True) + '"></script>'

    @staticmethod
    def record_bytes(name, data):
        data = data.encode() if isinstance(data, str) else bytes(data)
        return json.dumps({"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})

    @staticmethod
    def record_file(path, name):
        digest = hashlib.sha256()
        length = 0
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                length += len(chunk)
                digest.update(chunk)
        return json.dumps({"path": name, "size": length, "sha256": digest.hexdigest()})

    @staticmethod
    def page_fragment_js(export_id, arc_js, page_no, fragment_html):
        # This is local page data, never an instruction to request a remote URL.
        payload = json.dumps({"exportId": export_id, "page": page_no, "html": fragment_html}, ensure_ascii=True).replace("<", "\\u003c")
        return "window.__OFFLINE_EXPORT_PAGES__=window.__OFFLINE_EXPORT_PAGES__||{};window.__OFFLINE_EXPORT_PAGES__[" + json.dumps(str(page_no)) + "]=" + payload + ";"

    @staticmethod
    def seal_export(export_id, entries, assets):
        return json.dumps(seal_local_entries(export_id, json.loads(entries), json.loads(assets)), ensure_ascii=False)


def seal_local_entries(export_id, entries, html_assets=None):
    manifest = json.dumps({"format": "local-sha256/1", "exportId": export_id,
                           "entries": list(entries), "assets": html_assets or {}}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(manifest.encode()).hexdigest()
    return {"manifestCanonical": manifest, "manifestJson": manifest, "signature": "local-sha256:" + digest,
            "authoritativeSealFormat": "local-sha256/1", "bundle": "/* Local SHA-256 manifest: " + digest + " */"}
