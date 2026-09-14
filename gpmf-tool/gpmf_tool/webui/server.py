"""結合選択画面 (Web UI) のローカル HTTP サーバ。

- 127.0.0.1 の空きポートにだけ bind する (外部からは到達できない)
- ``/api/*`` は起動ごとに生成するトークン (``X-Token`` ヘッダ、または
  ``<img>``/``<video>`` 用にクエリ ``t``) が無いと 403
- 静的ファイルはパッケージ内 ``static/`` からのみ配信 (パストラバーサル不可)
- 重い処理 (フォルダ精査・結合) はバックグラウンドのジョブとして走らせ、
  ページ側がポーリングで進捗を取る

標準ライブラリだけで動く。PyInstaller で固めた場合も ``__file__`` 起点で
静的ファイルを見つけられる (spec の datas で同じ相対位置に置く)。
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
RECENT_FILE = os.path.join(os.path.expanduser("~"), ".gpmf_tool_recent.json")
RECENT_MAX = 10

# 配信を許す静的ファイルの拡張子 → Content-Type
_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

_VIDEO_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".360": "video/mp4",
}

_CONFIDENCE_JA = {"high": "高", "medium": "中", "low": "低"}


def _humanize(e: BaseException) -> str:
    """例外を日本語の 1 行にする (CLI と同じ変換)。"""
    try:
        from ..__main__ import humanize_error
        return humanize_error(e)
    except Exception:
        return str(e) or e.__class__.__name__


# ---------------------------------------------------------------------------
# OS ネイティブのダイアログ (tkinter 無しで済むものを優先)
# ---------------------------------------------------------------------------

def _run_capture(cmd: List[str], timeout: float = 600.0) -> Optional[str]:
    """外部コマンドを実行し、正常終了なら stdout の 1 行目を返す。"""
    kwargs: Dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=timeout,
                              **kwargs)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    text = proc.stdout.decode("utf-8", "replace").strip()
    line = text.splitlines()[0].strip() if text else ""
    return line or None


def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _as_quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _tk_dialog(kind: str, title: str, initial: Optional[str]) -> Optional[str]:
    """最後の手段: 隠し Tk ルートでファイルダイアログを出す。"""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None
    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        if kind == "folder":
            p = filedialog.askdirectory(title=title, initialdir=initial or None,
                                        parent=root)
        else:
            p = filedialog.askopenfilename(
                title=title, initialdir=initial or None, parent=root,
                filetypes=[("GPX", "*.gpx *.GPX"), ("すべて", "*.*")])
        return p or None
    except Exception:
        return None
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


def native_dialog(kind: str = "folder", title: str = "フォルダを選択",
                  initial: Optional[str] = None,
                  allow_tk: bool = True) -> Optional[str]:
    """OS ネイティブのフォルダ/ファイル選択ダイアログを開く。

    kind: "folder" | "file" (file は GPX 想定)。
    キャンセル、または使える手段が無ければ None (ページ側はテキスト入力に
    フォールバックする)。
    """
    if sys.platform == "darwin":
        # osascript: 手前のアプリに紐付けてダイアログを前面に出す
        if kind == "folder":
            expr = f"choose folder with prompt {_as_quote(title)}"
            if initial and os.path.isdir(initial):
                expr += f" default location (POSIX file {_as_quote(initial)})"
        else:
            expr = f"choose file with prompt {_as_quote(title)}"
        script = ("tell application (path to frontmost application as text) "
                  f"to POSIX path of ({expr})")
        got = _run_capture(["osascript", "-e", script])
        if got:
            return got.rstrip("/") if kind == "folder" and len(got) > 1 else got
        return None

    if sys.platform == "win32":
        if kind == "folder":
            body = (
                "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                f"$d.Description = {_ps_quote(title)}; "
                "$d.ShowNewFolderButton = $true; "
                + (f"$d.SelectedPath = {_ps_quote(initial)}; "
                   if initial and os.path.isdir(initial) else "")
                + "if ($d.ShowDialog() -eq 'OK') { Write-Output $d.SelectedPath }"
            )
        else:
            body = (
                "$d = New-Object System.Windows.Forms.OpenFileDialog; "
                f"$d.Title = {_ps_quote(title)}; "
                "$d.Filter = 'GPX (*.gpx)|*.gpx|すべてのファイル (*.*)|*.*'; "
                + (f"$d.InitialDirectory = {_ps_quote(initial)}; "
                   if initial and os.path.isdir(initial) else "")
                + "if ($d.ShowDialog() -eq 'OK') { Write-Output $d.FileName }"
            )
        script = ("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
                  "Add-Type -AssemblyName System.Windows.Forms; " + body)
        for exe in ("powershell", "pwsh"):
            if shutil.which(exe):
                got = _run_capture([exe, "-NoProfile", "-STA",
                                    "-NonInteractive", "-Command", script])
                if got:
                    return got
                break
        return _tk_dialog(kind, title, initial) if allow_tk else None

    # Linux / その他: zenity → kdialog → tkinter
    if shutil.which("zenity"):
        cmd = ["zenity", "--file-selection", f"--title={title}"]
        if kind == "folder":
            cmd.append("--directory")
        else:
            cmd.append("--file-filter=GPX | *.gpx *.GPX")
            cmd.append("--file-filter=すべて | *")
        if initial and os.path.isdir(initial):
            cmd.append(f"--filename={initial.rstrip('/')}/")
        got = _run_capture(cmd)
        if got:
            return got
        return None
    if shutil.which("kdialog"):
        start = initial if initial and os.path.isdir(initial) else "~"
        if kind == "folder":
            cmd = ["kdialog", "--title", title, "--getexistingdirectory", start]
        else:
            cmd = ["kdialog", "--title", title, "--getopenfilename", start,
                   "*.gpx *.GPX|GPX"]
        got = _run_capture(cmd)
        return got or None
    return _tk_dialog(kind, title, initial) if allow_tk else None


def reveal_path(path: str) -> None:
    """パスを OS のファイラ/既定アプリで開く。"""
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# 最近使ったフォルダ
# ---------------------------------------------------------------------------

def load_recent(path: Optional[str] = None) -> List[str]:
    path = path or RECENT_FILE
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [p for p in data if isinstance(p, str)][:RECENT_MAX]
    except Exception:
        pass
    return []


def add_recent(folder: str, path: Optional[str] = None) -> List[str]:
    path = path or RECENT_FILE
    items = [p for p in load_recent(path) if p != folder]
    items.insert(0, folder)
    items = items[:RECENT_MAX]
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    return items


# ---------------------------------------------------------------------------
# browse.Group / FileEntry → JSON
# ---------------------------------------------------------------------------

def entry_id(path: str) -> str:
    return hashlib.sha1(os.path.realpath(path).encode("utf-8", "surrogateescape")
                        ).hexdigest()[:16]


def entry_to_json(e: Any) -> dict:
    """browse.FileEntry を JSON 用 dict にする (欠けた属性は既定値)。"""
    g = lambda name, default=None: getattr(e, name, default)  # noqa: E731
    created = g("created")
    path = g("path", "") or ""
    return {
        "id": entry_id(path),
        "path": path,
        "name": g("name", os.path.basename(path)),
        "size": int(g("size", 0) or 0),
        "size_text": g("size_text", ""),
        "duration": float(g("duration", 0.0) or 0.0),
        "duration_text": g("duration_text", "-"),
        "width": int(g("width", 0) or 0),
        "height": int(g("height", 0) or 0),
        "resolution_text": g("resolution_text", "-"),
        "fps": float(g("fps", 0.0) or 0.0),
        "codec": g("codec", "") or "",
        "created_iso": created.isoformat() if created else None,
        "created_text": g("created_text", "-"),
        "kind_text": g("kind_text", "動画"),
        "has_gpmd": bool(g("has_gpmd", False)),
        "has_gps": bool(g("has_gps", False)),
        "is_360": bool(g("is_360", False)),
        "error": g("error"),
        "warning": g("warning"),
        "selected": bool(g("selected", True)),
    }


def group_to_json(grp: Any, index: int) -> dict:
    g = lambda name, default=None: getattr(grp, name, default)  # noqa: E731
    entries = [entry_to_json(e) for e in (g("entries", []) or [])]
    confidence = (g("confidence", "") or "").lower()
    return {
        "id": f"g{index}",
        "is_split": bool(g("is_split", len(entries) >= 2)),
        "title": g("title", "") or "",
        "reason": g("reason", "") or "",
        "confidence": confidence,
        "confidence_text": _CONFIDENCE_JA.get(confidence, ""),
        "vendor": g("vendor", "") or "",
        "total_size": int(g("total_size", 0) or 0),
        "total_duration": float(g("total_duration", 0.0) or 0.0),
        "entries": entries,
    }


def default_join_output(files: List[str], out_dir: str, gopro: bool) -> str:
    """結合の出力名: <末尾の数字/_/- を除いた stem>_結合[_gopro]<ext>。"""
    stem, ext = os.path.splitext(os.path.basename(files[0]))
    stem = stem.rstrip("0123456789_-") or stem
    suffix = "_結合_gopro" if gopro else "_結合"
    base = os.path.join(out_dir, f"{stem}{suffix}{ext or '.mp4'}")
    if not os.path.exists(base):
        return base
    n = 2
    while True:
        cand = os.path.join(out_dir, f"{stem}{suffix} ({n}){ext or '.mp4'}")
        if not os.path.exists(cand):
            return cand
        n += 1


# ---------------------------------------------------------------------------
# アプリ状態 (サーバ 1 つにつき 1 つ)
# ---------------------------------------------------------------------------

class WebUIApp:
    """ジョブ・エントリ登録簿・サムネイルキャッシュを保持する。"""

    def __init__(self, folder: Optional[str] = None,
                 default_device: Optional[str] = None,
                 allow_tk_dialog: bool = True):
        self.token = secrets.token_urlsafe(24)
        self.initial_folder = folder
        self.default_device = default_device
        self.allow_tk_dialog = allow_tk_dialog
        self.lock = threading.Lock()
        self.scan_jobs: Dict[str, dict] = {}
        self.join_jobs: Dict[str, dict] = {}
        self.entries: Dict[str, str] = {}       # id → path
        self.thumb_cache: Dict[str, Optional[tuple]] = {}
        self.quit_event = threading.Event()
        self.busy = False                        # 結合中はスキャンも拒否

    # --- スキャン --------------------------------------------------------
    def start_scan(self, path: str, recursive: bool) -> str:
        from .. import browse
        job_id = secrets.token_hex(6)
        job = {"state": "running", "done": 0, "total": 0, "current": "",
               "groups": None, "error": None, "path": path,
               "recursive": recursive}
        with self.lock:
            self.scan_jobs[job_id] = job

        def progress(done, total, name):
            job["done"], job["total"], job["current"] = done, total, name

        def work():
            try:
                groups = browse.scan_folder([path], recursive=recursive,
                                            progress=progress)
                out = [group_to_json(g, i) for i, g in enumerate(groups)]
                with self.lock:
                    for g in out:
                        for e in g["entries"]:
                            self.entries[e["id"]] = e["path"]
                job["groups"] = out
                job["state"] = "done"
                if os.path.isdir(path):
                    add_recent(path)
            except Exception as e:  # noqa: BLE001
                job["error"] = _humanize(e)
                job["state"] = "error"

        threading.Thread(target=work, daemon=True, name="webui-scan").start()
        return job_id

    def diagnose(self, job: dict) -> str:
        """スキャン済みフォルダについて判定の材料を全部書き出す。"""
        from .. import split_detect
        from ..__main__ import collect_videos
        files = collect_videos([job["path"]],
                               recursive=bool(job.get("recursive")))
        head = [f"フォルダ: {job['path']}",
                f"動画: {len(files)} 個", ""]
        if not files:
            return "\n".join(head + ["(動画がありません)"])
        return "\n".join(head) + split_detect.diagnose(files)

    # --- 結合 ------------------------------------------------------------
    def start_join(self, req: dict) -> str:
        from .. import concat
        job_id = secrets.token_hex(6)
        groups = req.get("groups") or []
        out_dir = req.get("out_dir") or ""
        gopro = bool(req.get("gopro"))
        device = req.get("device") or self.default_device or "hero9"
        gpx = req.get("gpx") or None
        from_video = bool(req.get("from_video"))
        try:
            rate = float(req.get("rate") or 10.0)
        except (TypeError, ValueError):
            rate = 10.0
        job = {"state": "running", "log": [], "done": 0, "total": len(groups),
               "results": [], "error": None, "out_dir": out_dir}
        with self.lock:
            self.join_jobs[job_id] = job
            self.busy = True

        def log(msg: str) -> None:
            job["log"].append(str(msg))

        def work():
            failed: List[str] = []
            try:
                os.makedirs(out_dir, exist_ok=True)
                for gi, g in enumerate(groups, 1):
                    files = list(g.get("files") or [])
                    if len(files) < 2:
                        log(f"[{gi}/{len(groups)}] 2本未満のためスキップ")
                        job["done"] = gi
                        continue
                    out = default_join_output(files, out_dir, gopro)
                    log(f"--- [{gi}/{len(groups)}] {len(files)} 個を結合 → "
                        f"{os.path.basename(out)} ---")
                    for f in files:
                        log(f"    + {os.path.basename(f)}")
                    try:
                        stats = concat.concat_files(
                            files, out, log=log,
                            gopro_device=device if gopro else None,
                            gpx=gpx if gopro else None,
                            from_video=from_video if gopro else False,
                            rate=rate)
                        shot = stats.get("shot_at")
                        res = {
                            "output": out,
                            "name": os.path.basename(out),
                            "duration_sec": stats.get("duration_sec", 0),
                            "bytes": stats.get("bytes", 0),
                            "gopro": stats.get("gopro"),
                            "shot_at": (shot.strftime("%Y/%m/%d %H:%M:%S")
                                        if shot else None),
                            "error": None,
                        }
                        d = res["duration_sec"]
                        log(f"  完了: {out}")
                        log(f"    長さ {int(d // 60)}分{d % 60:.0f}秒 / "
                            f"{res['bytes'] / 1024 ** 3:.2f} GB")
                        if res["gopro"]:
                            log(f"    GoPro化: {res['gopro']}")
                        if res["shot_at"]:
                            log(f"    撮影日時: {res['shot_at']} (先頭素材から引き継ぎ)")
                    except Exception as e:  # noqa: BLE001
                        msg = _humanize(e)
                        failed.append(f"{os.path.basename(out)}: {msg}")
                        log(f"  エラー: {msg}")
                        res = {"output": out, "name": os.path.basename(out),
                               "duration_sec": 0, "bytes": 0, "gopro": None,
                               "shot_at": None, "error": msg}
                        # 失敗した書きかけファイルは残さない
                        try:
                            if os.path.exists(out):
                                os.remove(out)
                        except OSError:
                            pass
                    job["results"].append(res)
                    job["done"] = gi
                ok = sum(1 for r in job["results"] if not r["error"])
                log(f"=== 結合おわり: 成功 {ok} / 失敗 {len(failed)} ===")
                if failed:
                    job["error"] = "\n".join(failed)
                job["state"] = "error" if (failed and not ok) else "done"
            except Exception as e:  # noqa: BLE001
                job["error"] = _humanize(e)
                log(f"エラー: {job['error']}")
                job["state"] = "error"
            finally:
                with self.lock:
                    self.busy = False

        threading.Thread(target=work, daemon=True, name="webui-join").start()
        return job_id

    # --- サムネイル ------------------------------------------------------
    def thumbnail(self, eid: str) -> Optional[tuple]:
        """(content-type, bytes) か None。"""
        with self.lock:
            if eid in self.thumb_cache:
                return self.thumb_cache[eid]
            path = self.entries.get(eid)
        if not path:
            return None
        from .. import thumbs
        try:
            data = thumbs.get_thumbnail(path)
        except Exception:
            data = None
        result = None
        if data:
            if data[:3] == b"\xff\xd8\xff":
                result = ("image/jpeg", data)
            elif data[:8] == b"\x89PNG\r\n\x1a\n":
                result = ("image/png", data)
            else:
                result = ("application/octet-stream", data)
        with self.lock:
            self.thumb_cache[eid] = result
        return result


# ---------------------------------------------------------------------------
# HTTP ハンドラ
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    server_version = "gpmf-webui/1.0"
    protocol_version = "HTTP/1.1"

    @property
    def app(self) -> WebUIApp:
        return self.server.app  # type: ignore[attr-defined]

    # ログはうるさいので GPMF_DEBUG のときだけ
    def log_message(self, fmt, *args):  # noqa: D401
        if os.environ.get("GPMF_DEBUG"):
            super().log_message(fmt, *args)

    # --- 応答ヘルパ ------------------------------------------------------
    def _send_bytes(self, status: int, ctype: str, body: bytes,
                    extra: Optional[dict] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj: Any, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, "application/json; charset=utf-8", body)

    def _error(self, status: int, msg: str) -> None:
        self._json({"error": msg}, status)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        raw = self.rfile.read(min(n, 4 * 1024 * 1024))
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _authorized(self, query: dict) -> bool:
        tok = self.headers.get("X-Token") or (query.get("t") or [""])[0]
        return bool(tok) and secrets.compare_digest(tok, self.app.token)

    # --- ルーティング ----------------------------------------------------
    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if path == "/" or path == "/index.html":
                return self._static("index.html")
            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            if path.startswith("/api/"):
                if not self._authorized(query):
                    return self._error(403, "トークンが不正です")
                return self._api_get(path, query)
            self._error(404, "見つかりません")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    def do_POST(self):  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if not path.startswith("/api/"):
                return self._error(404, "見つかりません")
            if not self._authorized(query):
                # ボディは読み捨てる
                self._read_json()
                return self._error(403, "トークンが不正です")
            body = self._read_json()
            return self._api_post(path, body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # --- 静的ファイル ----------------------------------------------------
    def _static(self, name: str) -> None:
        # ディレクトリ区切りや ".." を含むものは受け付けない
        if (not name or "/" in name or "\\" in name or ".." in name
                or name.startswith(".")):
            return self._error(404, "見つかりません")
        ext = os.path.splitext(name)[1].lower()
        ctype = _STATIC_TYPES.get(ext)
        full = os.path.realpath(os.path.join(STATIC_DIR, name))
        root = os.path.realpath(STATIC_DIR)
        if (ctype is None or not full.startswith(root + os.sep)
                or not os.path.isfile(full)):
            return self._error(404, "見つかりません")
        with open(full, "rb") as f:
            data = f.read()
        self._send_bytes(200, ctype, data)

    # --- GET API ---------------------------------------------------------
    def _api_get(self, path: str, query: dict) -> None:
        app = self.app
        if path == "/api/config":
            return self._json(self._config())
        if path == "/api/devices":
            from .. import gopro
            return self._json({
                "devices": sorted(gopro.DEVICE_PRESETS),
                "labels": {k: v.device_name for k, v in gopro.DEVICE_PRESETS.items()},
                "default": app.default_device or gopro.DEFAULT_PRESET,
            })
        if path.startswith("/api/scan/"):
            job = app.scan_jobs.get(path[len("/api/scan/"):])
            if job is None:
                return self._error(404, "そのジョブはありません")
            return self._json({k: v for k, v in job.items()})
        if path.startswith("/api/join/"):
            job = app.join_jobs.get(path[len("/api/join/"):])
            if job is None:
                return self._error(404, "そのジョブはありません")
            return self._json({k: v for k, v in job.items()})
        if path == "/api/thumb":
            eid = (query.get("id") or [""])[0]
            got = app.thumbnail(eid)
            if not got:
                return self._error(404, "サムネイルがありません")
            ctype, data = got
            self._send_bytes(200, ctype, data,
                             {"Cache-Control": "private, max-age=3600"})
            return
        if path == "/api/file":
            eid = (query.get("id") or [""])[0]
            return self._stream_file(app.entries.get(eid))
        if path == "/api/diagnose":
            job = app.scan_jobs.get((query.get("job") or [""])[0])
            if job is None:
                return self._error(404, "先にフォルダをスキャンしてください")
            try:
                return self._json({"text": app.diagnose(job)})
            except Exception as e:  # noqa: BLE001
                return self._error(500, _humanize(e))
        self._error(404, "見つかりません")

    def _config(self) -> dict:
        from .. import gopro
        app = self.app
        return {
            "folder": app.initial_folder,
            "platform": sys.platform,
            "os_name": platform.system(),
            "devices": sorted(gopro.DEVICE_PRESETS),
            "device_labels": {k: v.device_name
                              for k, v in gopro.DEVICE_PRESETS.items()},
            "default_device": app.default_device or gopro.DEFAULT_PRESET,
            "device_explicit": bool(app.default_device),
            "recent": load_recent(),
            "home": os.path.expanduser("~"),
            "busy": app.busy,
        }

    # --- Range 対応のファイル配信 ---------------------------------------
    def _stream_file(self, path: Optional[str]) -> None:
        if not path or not os.path.isfile(path):
            return self._error(404, "ファイルがありません")
        size = os.path.getsize(path)
        ctype = _VIDEO_TYPES.get(os.path.splitext(path)[1].lower(),
                                 "application/octet-stream")
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        status = 200
        if rng and rng.startswith("bytes="):
            spec = rng[len("bytes="):].split(",")[0].strip()
            try:
                a, b = spec.split("-", 1)
                if a == "" and b == "":
                    raise ValueError
                if a == "":           # bytes=-N … 末尾 N バイト
                    n = int(b)
                    start = max(0, size - n)
                    end = size - 1
                else:
                    start = int(a)
                    end = int(b) if b else size - 1
                    end = min(end, size - 1)
                if start > end or start >= size:
                    raise ValueError
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "private, max-age=3600")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        # 巨大ファイルをメモリに載せない: 1MB ずつ流す
        chunk = 1024 * 1024
        with open(path, "rb") as f:
            f.seek(start)
            remain = length
            while remain > 0:
                buf = f.read(min(chunk, remain))
                if not buf:
                    break
                self.wfile.write(buf)
                remain -= len(buf)

    # --- POST API --------------------------------------------------------
    def _api_post(self, path: str, body: dict) -> None:
        app = self.app
        if path == "/api/pick-folder" or path == "/api/pick-outdir":
            title = body.get("title") or (
                "出力先フォルダを選択" if path.endswith("outdir")
                else "動画のあるフォルダを選択")
            got = native_dialog("folder", title, body.get("initial"),
                                allow_tk=app.allow_tk_dialog)
            return self._json({"path": got})
        if path == "/api/pick-gpx":
            got = native_dialog("file", body.get("title") or "GPX ファイルを選択",
                                body.get("initial"), allow_tk=app.allow_tk_dialog)
            return self._json({"path": got})
        if path == "/api/recent":
            return self._json({"recent": load_recent()})
        if path == "/api/scan":
            folder = (body.get("path") or "").strip()
            folder = os.path.expanduser(folder)
            if not folder:
                return self._error(400, "フォルダを指定してください")
            if not os.path.isdir(folder):
                return self._error(400, f"フォルダが見つかりません: {folder}")
            if app.busy:
                return self._error(409, "結合の実行中はスキャンできません")
            job = app.start_scan(folder, bool(body.get("recursive")))
            return self._json({"job": job})
        if path == "/api/join":
            groups = body.get("groups") or []
            out_dir = os.path.expanduser((body.get("out_dir") or "").strip())
            if not out_dir:
                return self._error(400, "出力先フォルダを指定してください")
            if not groups:
                return self._error(400, "結合するグループがありません")
            for g in groups:
                for f in (g.get("files") or []):
                    if not os.path.isfile(f):
                        return self._error(400, f"ファイルが見つかりません: {f}")
            if app.busy:
                return self._error(409, "すでに結合を実行中です")
            job = app.start_join(dict(body, out_dir=out_dir))
            return self._json({"job": job})
        if path == "/api/open":
            p = body.get("path") or ""
            if not p or not os.path.exists(p):
                return self._error(400, "パスが見つかりません")
            try:
                reveal_path(p)
            except Exception as e:  # noqa: BLE001
                return self._error(500, _humanize(e))
            return self._json({"ok": True})
        if path == "/api/exists":
            p = os.path.expanduser(body.get("path") or "")
            return self._json({"exists": os.path.exists(p),
                               "is_dir": os.path.isdir(p)})
        if path == "/api/quit":
            self._json({"ok": True})
            app.quit_event.set()
            return
        self._error(404, "見つかりません")


# ---------------------------------------------------------------------------
# サーバ起動
# ---------------------------------------------------------------------------

class WebUIServer:
    """ThreadingHTTPServer をデーモンスレッドで回すラッパ。"""

    def __init__(self, folder: Optional[str] = None,
                 default_device: Optional[str] = None,
                 port: int = 0, allow_tk_dialog: bool = True):
        self.app = WebUIApp(folder=folder, default_device=default_device,
                            allow_tk_dialog=allow_tk_dialog)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.app = self.app  # type: ignore[attr-defined]
        self.port = self.httpd.server_address[1]
        self.thread: Optional[threading.Thread] = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def url(self) -> str:
        """トークン付きの初回アクセス URL。"""
        return f"{self.base_url}/?t={self.app.token}"

    def start(self) -> "WebUIServer":
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       kwargs={"poll_interval": 0.25},
                                       daemon=True, name="webui-http")
        self.thread.start()
        return self

    def stop(self) -> None:
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass

    def open_browser(self) -> bool:
        try:
            return webbrowser.open(self.url)
        except Exception:
            return False

    def wait(self, poll: float = 0.5) -> None:
        """Ctrl+C か「終了」ボタン (POST /api/quit) までブロックする。"""
        try:
            while not self.app.quit_event.is_set():
                time.sleep(poll)
        except KeyboardInterrupt:
            pass


_shared: Optional[WebUIServer] = None
_shared_lock = threading.Lock()


def launch_in_background(folder: Optional[str] = None,
                         default_device: Optional[str] = None,
                         open_browser: bool = True) -> str:
    """Tk GUI などから呼ぶ: サーバが無ければ立て、ブラウザで開いて URL を返す。

    tkinter のダイアログは呼び出し元のメインループと衝突するので使わない。
    """
    global _shared
    with _shared_lock:
        if _shared is None or _shared.app.quit_event.is_set():
            _shared = WebUIServer(folder=folder, default_device=default_device,
                                  allow_tk_dialog=False).start()
        else:
            if folder:
                _shared.app.initial_folder = folder
            if default_device:
                _shared.app.default_device = default_device
        srv = _shared
    if open_browser:
        srv.open_browser()
    return srv.url


def serve_blocking(folder: Optional[str] = None, port: int = 0,
                   open_browser: bool = True, log=print) -> int:
    """CLI (`gpmf ui`) 用: サーバを立てて終了までブロックする。"""
    if folder:
        folder = os.path.abspath(os.path.expanduser(folder))
        if not os.path.isdir(folder):
            raise FileNotFoundError(folder)
    srv = WebUIServer(folder=folder, port=port).start()
    log(f"結合画面: {srv.url}")
    log("ブラウザで開いています。終了するには画面の「終了」か Ctrl+C。")
    if open_browser and not srv.open_browser():
        log("ブラウザを自動で開けませんでした。上の URL を手で開いてください。")
    srv.wait()
    srv.stop()
    log("終了しました。")
    return 0
