"""結合選択画面 (Web UI) のテスト。

1. サーバ API を http.client で直接叩く (合成 MP4 のフォルダを精査・結合)
2. Playwright + headless Chromium で実際のページを操作する
   (playwright が無い / Chromium が起動できない環境ではスキップ)
"""

import datetime
import glob
import http.client
import json
import os
import struct
import tempfile
import time
import unittest
from unittest import mock

from gpmf_tool import mp4, thumbs
from gpmf_tool.tests.test_browse import _fake_jpeg
from gpmf_tool.tests.test_concat import build_multi_sample_mp4
from gpmf_tool.webui import server as webui

EPOCH = datetime.datetime(1904, 1, 1, tzinfo=datetime.timezone.utc)
BASE = datetime.datetime(2025, 9, 15, 12, 0, tzinfo=datetime.timezone.utc)

# Playwright テストのスクリーンショット保存先
SCREENSHOT = os.environ.get(
    "GPMF_WEBUI_SCREENSHOT",
    "/tmp/claude-0/-home-user-gmail-manager/"
    "bd5cb4cb-486f-5982-990f-e906ea7db5a0/scratchpad/webui.png")


def make_video(folder: str, name: str, shot=None, n: int = 30) -> str:
    """撮影時刻 (mvhd の creation_time) を書き込んだ合成 MP4 を作る。"""
    data = bytearray(build_multi_sample_mp4("X", n))
    if shot is not None:
        ct = int((shot - EPOCH).total_seconds())
        i = data.find(b"mvhd")
        data[i + 8:i + 16] = struct.pack(">II", ct, ct)
    p = os.path.join(folder, name)
    with open(p, "wb") as f:
        f.write(bytes(data))
    return p


def make_png(w: int = 64, h: int = 36) -> bytes:
    """ブラウザが実際にデコードできる小さな PNG (グラデーション) を作る。"""
    import zlib
    rows = []
    for y in range(h):
        row = bytearray([0])  # フィルタ無し
        for x in range(w):
            row += bytes((x * 255 // max(1, w - 1), y * 255 // max(1, h - 1), 128))
        rows.append(bytes(row))

    def chunk(t, d):
        return (struct.pack(">I", len(d)) + t + d
                + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows)))
            + chunk(b"IEND", b""))


def populate(folder: str) -> dict:
    """分割 3 本 + 単独 1 本 + 壊れた 1 本 + サイドカー画像を用意する。

    a0.THM は JPEG マーカーだけのダミー (サーバ側の判定用)、
    a1.png はブラウザが本当に表示できる PNG、a2 はサムネイル無し。
    """
    paths = {}
    for i in range(3):
        paths[f"a{i}"] = make_video(folder, f"a{i}.mp4",
                                    BASE + datetime.timedelta(seconds=i))
    paths["solo"] = make_video(folder, "solo.mp4",
                               BASE + datetime.timedelta(hours=2))
    broken = os.path.join(folder, "broken.mp4")
    with open(broken, "wb") as f:
        f.write(b"not really an mp4" * 10)
    paths["broken"] = broken
    with open(os.path.join(folder, "a0.THM"), "wb") as f:
        f.write(_fake_jpeg())
    with open(os.path.join(folder, "a1.png"), "wb") as f:
        f.write(make_png())
    return paths


class _Client:
    """テスト用の最小 HTTP クライアント。"""

    def __init__(self, srv: webui.WebUIServer):
        self.port = srv.port
        self.token = srv.app.token

    def raw(self, method, path, body=None, headers=None, token=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        hdrs = dict(headers or {})
        if token:
            hdrs["X-Token"] = self.token
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        payload = resp.read()
        result = (resp.status, {k.lower(): v for k, v in resp.getheaders()},
                  payload)
        conn.close()
        return result

    def json(self, method, path, body=None, **kw):
        status, _, payload = self.raw(method, path, body, **kw)
        try:
            obj = json.loads(payload.decode("utf-8"))
        except Exception:
            obj = None
        return status, obj

    def wait_job(self, kind, job, timeout=60.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            status, st = self.json("GET", f"/api/{kind}/{job}")
            assert status == 200, st
            if st["state"] != "running":
                return st
            time.sleep(0.05)
        raise AssertionError(f"{kind} ジョブが時間内に終わりません")


class TestHelpers(unittest.TestCase):

    def test_default_join_output_strips_trailing_digits(self):
        d = tempfile.mkdtemp()
        files = [os.path.join(d, "DJI_0001.MP4"), os.path.join(d, "DJI_0002.MP4")]
        self.assertEqual(webui.default_join_output(files, d, False),
                         os.path.join(d, "DJI_結合.MP4"))
        self.assertEqual(webui.default_join_output(files, d, True),
                         os.path.join(d, "DJI_結合_gopro.MP4"))
        # 既にあれば (2) を付ける
        with open(os.path.join(d, "DJI_結合.MP4"), "wb"):
            pass
        self.assertEqual(webui.default_join_output(files, d, False),
                         os.path.join(d, "DJI_結合 (2).MP4"))

    def test_recent_dedup_and_limit(self):
        path = os.path.join(tempfile.mkdtemp(), "recent.json")
        for i in range(12):
            webui.add_recent(f"/f/{i}", path)
        webui.add_recent("/f/5", path)
        got = webui.load_recent(path)
        self.assertEqual(len(got), webui.RECENT_MAX)
        self.assertEqual(got[0], "/f/5")
        self.assertEqual(got.count("/f/5"), 1)

    def test_entry_to_json_tolerates_missing_attrs(self):
        class Stub:  # browse.FileEntry の一部だけ持つオブジェクト
            path = "/x/y.mp4"
        j = webui.entry_to_json(Stub())
        self.assertEqual(j["name"], "y.mp4")
        self.assertEqual(j["size"], 0)
        self.assertTrue(j["selected"])
        self.assertIsNone(j["created_iso"])


class TestWebUIServer(unittest.TestCase):
    """ライブサーバに対する API テスト。"""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.out = tempfile.mkdtemp()
        cls.paths = populate(cls.dir)
        cls.recent_file = os.path.join(tempfile.mkdtemp(), "recent.json")
        cls._patch = mock.patch.object(webui, "RECENT_FILE", cls.recent_file)
        cls._patch.start()
        # ffmpeg が入っている環境でも結果が変わらないように
        cls._patch_ff = mock.patch.object(thumbs, "ffmpeg_thumbnail",
                                          return_value=None)
        cls._patch_ff.start()
        thumbs.clear_cache()
        cls.srv = webui.WebUIServer(folder=cls.dir).start()
        cls.c = _Client(cls.srv)
        cls._groups = None

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        cls._patch.stop()
        cls._patch_ff.stop()

    def scanned(self):
        """1 度だけスキャンして結果 (groups) を使い回す。"""
        if self._groups is None:
            status, r = self.c.json("POST", "/api/scan",
                                    {"path": self.dir, "recursive": False})
            self.assertEqual(status, 200, r)
            st = self.c.wait_job("scan", r["job"])
            self.assertEqual(st["state"], "done", st)
            type(self)._groups = st["groups"]
        return self._groups

    def entry(self, name):
        for g in self.scanned():
            for e in g["entries"]:
                if e["name"] == name:
                    return e
        raise AssertionError(name)

    # --- 静的ファイル / セキュリティ -------------------------------------
    def test_index_and_static(self):
        status, hdr, body = self.c.raw("GET", "/", token=False)
        self.assertEqual(status, 200)
        self.assertIn("text/html", hdr["content-type"])
        self.assertIn(b"app.js", body)
        status, hdr, body = self.c.raw("GET", "/static/app.js", token=False)
        self.assertEqual(status, 200)
        self.assertIn("javascript", hdr["content-type"])
        self.assertIn(b"X-Token", body)
        status, _, _ = self.c.raw("GET", "/static/app.css", token=False)
        self.assertEqual(status, 200)

    def test_path_traversal_blocked(self):
        for p in ("/static/../server.py", "/static/..%2Fserver.py",
                  "/static/../../__main__.py", "/static/sub/app.js",
                  "/static/", "/static/.hidden", "/static/server.py"):
            status, _, body = self.c.raw("GET", p, token=False)
            self.assertEqual(status, 404, p)
            self.assertNotIn(b"ThreadingHTTPServer", body)

    def test_token_required(self):
        status, _ = self.c.json("GET", "/api/config", token=False)
        self.assertEqual(status, 403)
        status, _ = self.c.json("GET", "/api/config", token=False,
                                headers={"X-Token": "wrong"})
        self.assertEqual(status, 403)
        status, _ = self.c.json("POST", "/api/scan", {"path": self.dir},
                                token=False)
        self.assertEqual(status, 403)
        status, cfg = self.c.json("GET", "/api/config")
        self.assertEqual(status, 200)
        self.assertEqual(cfg["folder"], self.dir)
        # <img>/<video> 用: クエリ t でも通る
        status, _ = self.c.json("GET", f"/api/config?t={self.srv.app.token}",
                                token=False)
        self.assertEqual(status, 200)

    def test_devices(self):
        status, d = self.c.json("GET", "/api/devices")
        self.assertEqual(status, 200)
        self.assertIn("max", d["devices"])
        self.assertEqual(d["devices"], sorted(d["devices"]))
        self.assertIn(d["default"], d["devices"])

    # --- スキャン ----------------------------------------------------------
    def test_scan_groups_shape(self):
        groups = self.scanned()
        split = [g for g in groups if g["is_split"]]
        self.assertEqual(len(split), 1)
        self.assertEqual([e["name"] for e in split[0]["entries"]],
                         ["a0.mp4", "a1.mp4", "a2.mp4"])
        for key in ("id", "is_split", "title", "reason", "confidence",
                    "vendor", "total_size", "total_duration", "entries"):
            self.assertIn(key, split[0])
        e = split[0]["entries"][0]
        for key in ("id", "path", "name", "size", "size_text", "duration",
                    "duration_text", "width", "height", "resolution_text",
                    "fps", "codec", "created_iso", "created_text",
                    "kind_text", "has_gpmd", "has_gps", "is_360", "error",
                    "warning", "selected"):
            self.assertIn(key, e)
        self.assertEqual(e["resolution_text"], "1920 x 1080")
        self.assertTrue(e["created_iso"].startswith("2025-09-15"))
        self.assertIsNone(e["error"])
        self.assertTrue(e["selected"])
        broken = self.entry("broken.mp4")
        self.assertIsNotNone(broken["error"])
        # 最近使ったフォルダに記録される (ホームではなくテスト用ファイル)
        status, r = self.c.json("POST", "/api/recent", {})
        self.assertEqual(status, 200)
        self.assertIn(self.dir, r["recent"])

    def test_diagnose_api(self):
        self.scanned()
        job = next(iter(self.srv.app.scan_jobs))
        status, r = self.c.json("GET", f"/api/diagnose?job={job}")
        self.assertEqual(status, 200, r)
        self.assertIn("== 判定結果 ==", r["text"])
        self.assertIn("a0.mp4", r["text"])
        self.assertIn("読み取り失敗", r["text"])      # broken.mp4
        status, r = self.c.json("GET", "/api/diagnose?job=nope")
        self.assertEqual(status, 404)
        self.assertIn("スキャン", r["error"])

    def test_scan_bad_folder(self):
        status, r = self.c.json("POST", "/api/scan",
                                {"path": os.path.join(self.dir, "nope")})
        self.assertEqual(status, 400)
        self.assertIn("フォルダ", r["error"])
        status, r = self.c.json("GET", "/api/scan/doesnotexist")
        self.assertEqual(status, 404)

    # --- サムネイル / 動画配信 --------------------------------------------
    def test_thumb_ok_and_404(self):
        a0 = self.entry("a0.mp4")   # a0.THM がある
        status, hdr, body = self.c.raw("GET", f"/api/thumb?id={a0['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(hdr["content-type"], "image/jpeg")
        self.assertTrue(body.startswith(b"\xff\xd8\xff"))
        a1 = self.entry("a1.mp4")   # a1.png (本物の PNG)
        status, hdr, body = self.c.raw("GET", f"/api/thumb?id={a1['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(hdr["content-type"], "image/png")
        self.assertTrue(body.startswith(b"\x89PNG"))
        a2 = self.entry("a2.mp4")   # サムネイル無し
        status, _, _ = self.c.raw("GET", f"/api/thumb?id={a2['id']}")
        self.assertEqual(status, 404)
        status, _, _ = self.c.raw("GET", "/api/thumb?id=unknown")
        self.assertEqual(status, 404)

    def test_file_range(self):
        a1 = self.entry("a1.mp4")
        with open(a1["path"], "rb") as f:
            data = f.read()
        url = f"/api/file?id={a1['id']}"
        # 全体
        status, hdr, body = self.c.raw("GET", url)
        self.assertEqual(status, 200)
        self.assertEqual(hdr["accept-ranges"], "bytes")
        self.assertEqual(hdr["content-type"], "video/mp4")
        self.assertEqual(body, data)
        # 範囲
        status, hdr, body = self.c.raw("GET", url, headers={"Range": "bytes=10-29"})
        self.assertEqual(status, 206)
        self.assertEqual(hdr["content-range"], f"bytes 10-29/{len(data)}")
        self.assertEqual(hdr["content-length"], "20")
        self.assertEqual(body, data[10:30])
        # 末尾まで / 末尾 N バイト
        status, _, body = self.c.raw("GET", url, headers={"Range": "bytes=100-"})
        self.assertEqual(status, 206)
        self.assertEqual(body, data[100:])
        status, _, body = self.c.raw("GET", url, headers={"Range": "bytes=-7"})
        self.assertEqual(status, 206)
        self.assertEqual(body, data[-7:])
        # 範囲外
        status, _, _ = self.c.raw("GET", url,
                                  headers={"Range": f"bytes={len(data) + 5}-"})
        self.assertEqual(status, 416)
        status, _, _ = self.c.raw("GET", "/api/file?id=unknown")
        self.assertEqual(status, 404)

    # --- 結合 --------------------------------------------------------------
    def test_join_end_to_end(self):
        files = [self.paths[f"a{i}"] for i in range(3)]
        status, r = self.c.json("POST", "/api/join", {
            "groups": [{"files": files}], "out_dir": self.out,
            "gopro": False, "device": "max", "gpx": None,
            "from_video": False, "rate": 10})
        self.assertEqual(status, 200, r)
        st = self.c.wait_job("join", r["job"])
        self.assertEqual(st["state"], "done", st)
        self.assertIsNone(st["error"])
        self.assertEqual(st["done"], 1)
        self.assertEqual(len(st["results"]), 1)
        res = st["results"][0]
        self.assertIsNone(res["error"])
        self.assertEqual(os.path.basename(res["output"]), "a_結合.mp4")
        self.assertTrue(os.path.isfile(res["output"]))
        self.assertGreater(res["bytes"], 0)
        self.assertAlmostEqual(res["duration_sec"], 3.0, places=2)
        self.assertTrue(any("完了" in line for line in st["log"]))
        with open(res["output"], "rb") as f:
            types = [b.type for b in mp4.scan_top_level(f)]
        self.assertIn(b"moov", types)
        self.assertIn(b"mdat", types)

    def test_join_with_gopro(self):
        files = [self.paths[f"a{i}"] for i in range(3)]
        out = tempfile.mkdtemp()
        status, r = self.c.json("POST", "/api/join", {
            "groups": [{"files": files}], "out_dir": out,
            "gopro": True, "device": "max"})
        self.assertEqual(status, 200, r)
        st = self.c.wait_job("join", r["job"])
        self.assertEqual(st["state"], "done", st)
        res = st["results"][0]
        self.assertEqual(res["gopro"], "GoPro Max")
        self.assertTrue(res["output"].endswith("a_結合_gopro.mp4"))
        with open(res["output"], "rb") as f:
            self.assertTrue(mp4.detect_telemetry(f)["gpmd"])

    def test_join_failure_is_japanese(self):
        # 1 本だけ → concat が MP4Error を出す → 日本語のまま返る
        status, r = self.c.json("POST", "/api/join", {
            "groups": [{"files": [self.paths["a0"], self.paths["broken"]]}],
            "out_dir": self.out})
        self.assertEqual(status, 200, r)
        st = self.c.wait_job("join", r["job"])
        self.assertEqual(st["state"], "error")
        self.assertTrue(st["error"])
        self.assertIsNotNone(st["results"][0]["error"])
        # 書きかけの出力は残らない
        self.assertFalse(os.path.exists(st["results"][0]["output"]))

    def test_join_validation(self):
        status, r = self.c.json("POST", "/api/join",
                                {"groups": [], "out_dir": self.out})
        self.assertEqual(status, 400)
        status, r = self.c.json("POST", "/api/join", {
            "groups": [{"files": ["/no/such/file.mp4", self.paths["a0"]]}],
            "out_dir": self.out})
        self.assertEqual(status, 400)
        self.assertIn("見つかりません", r["error"])

    # --- その他 ------------------------------------------------------------
    def test_open_bad_path(self):
        status, r = self.c.json("POST", "/api/open",
                                {"path": os.path.join(self.dir, "zzz")})
        self.assertEqual(status, 400)

    def test_unknown_api(self):
        status, _ = self.c.json("GET", "/api/nothing")
        self.assertEqual(status, 404)
        status, _ = self.c.json("POST", "/api/nothing", {})
        self.assertEqual(status, 404)

    def test_quit_sets_event(self):
        # 別サーバで試す (共有サーバを止めないように)
        srv = webui.WebUIServer().start()
        try:
            c = _Client(srv)
            status, r = c.json("POST", "/api/quit", {})
            self.assertEqual(status, 200)
            self.assertTrue(srv.app.quit_event.wait(2.0))
        finally:
            srv.stop()


# ---------------------------------------------------------------------------
# Playwright (headless Chromium) でページを実際に操作する
# ---------------------------------------------------------------------------

try:
    from playwright.sync_api import sync_playwright  # type: ignore
    HAVE_PLAYWRIGHT = True
except Exception:  # ImportError など
    HAVE_PLAYWRIGHT = False


def _chromium_candidates():
    """既定 (None) → PLAYWRIGHT_BROWSERS_PATH 配下の実行ファイルの順に試す。"""
    cands = [None]
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if root and os.path.isdir(root):
        pats = ["chromium_headless_shell-*/*/headless_shell",
                "chromium_headless_shell-*/*/chrome-headless-shell",
                "chromium-*/*/chrome", "chromium-*/*/chrome.exe",
                "chromium-*/*/Chromium.app/Contents/MacOS/Chromium"]
        for pat in pats:
            cands += sorted(glob.glob(os.path.join(root, pat)), reverse=True)
    return cands


@unittest.skipUnless(HAVE_PLAYWRIGHT, "playwright が入っていない")
class TestWebUIBrowser(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.paths = populate(cls.dir)
        cls.recent_file = os.path.join(tempfile.mkdtemp(), "recent.json")
        cls._patch = mock.patch.object(webui, "RECENT_FILE", cls.recent_file)
        cls._patch.start()
        cls._patch_ff = mock.patch.object(thumbs, "ffmpeg_thumbnail",
                                          return_value=None)
        cls._patch_ff.start()
        thumbs.clear_cache()
        cls.srv = webui.WebUIServer().start()   # フォルダはページ側で入力する
        cls.pw = sync_playwright().start()
        cls.browser = None
        errors = []
        for exe in _chromium_candidates():
            try:
                cls.browser = cls.pw.chromium.launch(headless=True,
                                                     executable_path=exe)
                break
            except Exception as e:  # noqa: BLE001
                errors.append(f"{exe}: {str(e).splitlines()[0][:120]}")
        if cls.browser is None:
            cls.pw.stop()
            cls.srv.stop()
            cls._patch.stop()
            cls._patch_ff.stop()
            raise unittest.SkipTest("Chromium を起動できない: " + " / ".join(errors))

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "browser", None):
            cls.browser.close()
        cls.pw.stop()
        cls.srv.stop()
        cls._patch.stop()
        cls._patch_ff.stop()

    def test_page_flow(self):
        page = self.browser.new_page(viewport={"width": 1280, "height": 800})
        js_errors = []
        page.on("pageerror", lambda e: js_errors.append(str(e)))
        page.goto(self.srv.url)
        page.wait_for_selector("#folder")

        # ネイティブダイアログは headless では出せないのでパスを直接入力
        page.fill("#folder", self.dir)
        page.click("#btn-scan")
        page.wait_for_selector("tr.group", timeout=30000)
        page.wait_for_selector("tr.item", timeout=30000)

        # グループ見出し + 3 行 (単独動画は既定で非表示)
        self.assertEqual(page.locator("tr.group").count(), 1)
        self.assertEqual(page.locator("tr.item").count(), 3)
        head = page.locator("tr.group .gtitle").inner_text()
        self.assertIn("分割された1本の撮影", head)
        self.assertIn("3個", head)
        self.assertIn("選択中 3 ファイル", page.locator("#status-text").inner_text())
        self.assertIn("結合対象 1 件", page.locator("#status-text").inner_text())
        self.assertFalse(page.locator("#btn-join").is_disabled())

        # 単独の動画も表示 → 行が増え、壊れたファイルは灰色行 + ⚠
        page.check("#opt-solo")
        page.wait_for_function("document.querySelectorAll('tr.item').length === 5")
        self.assertEqual(page.locator("tr.item.broken").count(), 1)
        self.assertEqual(page.locator("tr.item.broken .warn-icon").count(), 1)
        self.assertTrue(page.locator("tr.item.broken input[type=checkbox]").is_disabled())
        page.uncheck("#opt-solo")
        page.wait_for_function("document.querySelectorAll('tr.item').length === 3")

        # チェックを外すとステータスバーの件数が変わる
        page.locator("tr.item input[type=checkbox]").first.uncheck()
        page.wait_for_function(
            "document.querySelector('#status-text').textContent.includes('選択中 2 ファイル')")
        page.locator("tr.item input[type=checkbox]").first.check()
        page.wait_for_function(
            "document.querySelector('#status-text').textContent.includes('選択中 3 ファイル')")

        # 並べ替え: 名前で 1 回 (昇順) → もう 1 回 (降順) で逆順になる
        def names():
            return page.locator("tr.item .fname").all_inner_texts()
        page.click("th[data-key=name]")
        page.wait_for_selector("th[data-key=name] .sort-mark")
        asc = names()
        self.assertEqual(asc, sorted(asc))
        page.click("th[data-key=name]")
        page.wait_for_function(
            "document.querySelector('th[data-key=name] .sort-mark').textContent === '▼'")
        desc = names()
        self.assertEqual(desc, list(reversed(asc)))
        self.assertNotEqual(desc, asc)

        # 行クリックで詳細ペインが埋まる / Space でチェック切替
        page.click("tr.item >> nth=0")
        self.assertIn("a2.mp4", page.locator("#details-title").inner_text())
        page.keyboard.press("Space")
        page.wait_for_function(
            "document.querySelector('#status-text').textContent.includes('選択中 2 ファイル')")
        page.keyboard.press("Space")

        # サムネイル: 本物の PNG がある a1 は <img> として表示され、
        # ダミー JPEG (a0) と無し (a2) は 画像→動画→プレースホルダ と降格する
        page.wait_for_function(
            "[...document.querySelectorAll('.thumb img')]"
            ".some(i => i.complete && i.naturalWidth > 0)", timeout=15000)
        page.wait_for_function(
            "document.querySelectorAll('.thumb .ph, .thumb video').length >= 2",
            timeout=15000)

        # 判定の詳細 (診断) パネル
        self.assertFalse(page.locator("#btn-diag").is_disabled())
        page.click("#btn-diag")
        page.wait_for_function(
            "document.querySelector('#diag-text').textContent.includes('== 判定結果 ==')",
            timeout=15000)
        self.assertIn("a0.mp4", page.locator("#diag-text").inner_text())
        page.keyboard.press("Escape")
        page.wait_for_function(
            "document.querySelector('#diag').classList.contains('hidden')")

        os.makedirs(os.path.dirname(SCREENSHOT), exist_ok=True)
        page.screenshot(path=SCREENSHOT, full_page=True)
        self.assertTrue(os.path.isfile(SCREENSHOT))
        self.assertEqual(js_errors, [])
        page.close()


if __name__ == "__main__":
    unittest.main()
