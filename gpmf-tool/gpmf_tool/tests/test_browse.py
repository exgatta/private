"""フォルダ精査・サムネイル取得のテスト (GUI 非依存の部分)。"""

import datetime
import os
import struct
import tempfile
import unittest

from gpmf_tool import browse, thumbs
from gpmf_tool.tests.test_concat import build_multi_sample_mp4

EPOCH = datetime.datetime(1904, 1, 1, tzinfo=datetime.timezone.utc)


def _fake_jpeg(size: int = 2000) -> bytes:
    """JPEG のマーカーを持つダミー画像。"""
    return b"\xff\xd8\xff\xe0" + b"\x00" * size + b"\xff\xd9"


class TestFormatting(unittest.TestCase):

    def test_size(self):
        self.assertEqual(browse.format_size(500), "500 B")
        self.assertEqual(browse.format_size(2048), "2 KB")
        self.assertEqual(browse.format_size(5 * 1024 ** 2), "5 MB")
        self.assertEqual(browse.format_size(3 * 1024 ** 3), "3.00 GB")

    def test_duration(self):
        self.assertEqual(browse.format_duration(0), "-")
        self.assertEqual(browse.format_duration(75), "1:15")
        self.assertEqual(browse.format_duration(3725), "1:02:05")


class TestScanFolder(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _make(self, name, shot=None, n=30):
        data = bytearray(build_multi_sample_mp4("X", n))
        if shot is not None:
            ct = int((shot - EPOCH).total_seconds())
            i = data.find(b"mvhd")
            data[i + 8:i + 16] = struct.pack(">II", ct, ct)
        p = os.path.join(self.dir, name)
        with open(p, "wb") as f:
            f.write(bytes(data))
        return p

    def test_groups_and_fields(self):
        base = datetime.datetime(2025, 9, 15, 12, 0, tzinfo=datetime.timezone.utc)
        for i in range(3):
            self._make(f"a{i}.mp4", base + datetime.timedelta(seconds=i))
        self._make("solo.mp4", base + datetime.timedelta(hours=2))

        groups = browse.scan_folder([self.dir])
        split = [g for g in groups if g.is_split]
        solo = [g for g in groups if not g.is_split]
        self.assertEqual(len(split), 1)
        self.assertEqual(len(split[0].entries), 3)
        self.assertEqual(len(solo), 1)

        e = split[0].entries[0]
        self.assertEqual(e.resolution_text, "1920 x 1080")
        self.assertTrue(e.size > 0)
        self.assertIn("2025/09/15", e.created_text)
        self.assertEqual(e.kind_text, "動画")

    def test_selection_affects_totals(self):
        base = datetime.datetime(2025, 9, 15, 12, 0, tzinfo=datetime.timezone.utc)
        for i in range(3):
            self._make(f"a{i}.mp4", base + datetime.timedelta(seconds=i))
        g = [x for x in browse.scan_folder([self.dir]) if x.is_split][0]
        full = g.total_size
        self.assertEqual(len(g.selected_entries), 3)

        g.entries[0].selected = False
        self.assertEqual(len(g.selected_entries), 2)
        self.assertLess(g.total_size, full)

    def test_broken_file_marked(self):
        p = os.path.join(self.dir, "broken.mp4")
        with open(p, "wb") as f:
            f.write(b"not really an mp4" * 10)
        entry = browse.analyze_file(p)
        self.assertIsNotNone(entry.error)
        self.assertEqual(entry.resolution_text, "-")

    def test_summarize(self):
        base = datetime.datetime(2025, 9, 15, 12, 0, tzinfo=datetime.timezone.utc)
        for i in range(2):
            self._make(f"a{i}.mp4", base + datetime.timedelta(seconds=i))
        text = browse.summarize(browse.scan_folder([self.dir]))
        self.assertIn("動画 2 個", text)

    def test_empty_folder(self):
        self.assertEqual(browse.scan_folder([self.dir]), [])


class TestThumbnails(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        thumbs.clear_cache()

    def test_find_jpeg_in_blob(self):
        blob = b"junk" + _fake_jpeg() + b"tail"
        found = thumbs._find_jpeg(blob)
        self.assertIsNotNone(found)
        self.assertTrue(found.startswith(b"\xff\xd8\xff"))
        self.assertTrue(found.endswith(b"\xff\xd9"))

    def test_tiny_jpeg_ignored(self):
        # ノイズ程度の短いものは拾わない
        self.assertIsNone(thumbs._find_jpeg(b"\xff\xd8\xff" + b"x" * 10 + b"\xff\xd9"))

    def test_sidecar_thumbnail(self):
        video = os.path.join(self.dir, "GX010001.mp4")
        with open(video, "wb") as f:
            f.write(b"\x00" * 100)
        thm = os.path.join(self.dir, "GX010001.THM")
        with open(thm, "wb") as f:
            f.write(_fake_jpeg())
        data = thumbs.sidecar_thumbnail(video)
        self.assertIsNotNone(data)
        self.assertTrue(data.startswith(b"\xff\xd8\xff"))

    def test_no_thumbnail_returns_none(self):
        video = os.path.join(self.dir, "plain.mp4")
        with open(video, "wb") as f:
            f.write(build_multi_sample_mp4("A", 3))
        # ffmpeg を使わない設定なら None
        self.assertIsNone(thumbs.get_thumbnail(video, use_ffmpeg=False))

    def test_embedded_thumbnail_found(self):
        """udta に JPEG を入れた MP4 からサムネを取り出す。"""
        from gpmf_tool import mp4
        from gpmf_tool.mp4 import _box
        raw = build_multi_sample_mp4("A", 4)
        with open(os.path.join(self.dir, "t.mp4"), "wb") as f:
            f.write(raw)
        path = os.path.join(self.dir, "t.mp4")
        with open(path, "rb") as f:
            tops = mp4.scan_top_level(f)
            moov_top = next(b for b in tops if b.type == b"moov")
            moov = mp4.parse_box_tree(mp4.read_box_bytes(f, moov_top), b"moov")
            ftyp = mp4.read_box_bytes(
                f, next(b for b in tops if b.type == b"ftyp"))
            mdat_top = next(b for b in tops if b.type == b"mdat")
            mdat = mp4.read_box_bytes(f, mdat_top)
        thmb = _box(b"thmb", _fake_jpeg())
        moov.children.append(
            mp4.Box(type=b"udta", is_container=True,
                    children=mp4._parse_children(thmb, 0, len(thmb))))
        out = os.path.join(self.dir, "with_thumb.mp4")
        with open(out, "wb") as f:
            f.write(ftyp + mdat + moov.serialize())
        data = thumbs.embedded_thumbnail(out)
        self.assertIsNotNone(data)
        self.assertTrue(data.startswith(b"\xff\xd8\xff"))

    def test_cache_used(self):
        video = os.path.join(self.dir, "c.mp4")
        with open(video, "wb") as f:
            f.write(build_multi_sample_mp4("A", 3))
        thumbs.get_thumbnail(video, use_ffmpeg=False)
        self.assertIn(video, thumbs._CACHE)
        thumbs.clear_cache()
        self.assertNotIn(video, thumbs._CACHE)



class TestAnalyzeRobustness(unittest.TestCase):
    """付加情報の取得だけ失敗しても「読めません」にならない。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_error_message_is_japanese_and_specific(self):
        p = os.path.join(self.dir, "x.mp4")
        with open(p, "wb") as f:
            f.write(b"\x00" * 64)
        e = browse.analyze_file(p)
        self.assertIsNotNone(e.error)
        # 生の英語例外ではなく理由が入っている
        self.assertNotEqual(e.error, "")

    def test_missing_file(self):
        e = browse.analyze_file(os.path.join(self.dir, "nope.mp4"))
        self.assertIn("開けません", e.error)

    def test_side_info_failure_is_only_warning(self):
        from unittest import mock
        from gpmf_tool import mp4
        p = os.path.join(self.dir, "ok.mp4")
        with open(p, "wb") as f:
            f.write(build_multi_sample_mp4("A", 5))
        with mock.patch.object(mp4, "detect_spherical",
                               side_effect=RuntimeError("boom")):
            e = browse.analyze_file(p)
        self.assertIsNone(e.error, "本体は読めているのに読めません扱い")
        self.assertIn("360度判定に失敗", e.warning)
        self.assertEqual(e.resolution_text, "1920 x 1080")
if __name__ == "__main__":
    unittest.main()


class TestCreatedTextNoTimezoneShift(unittest.TestCase):
    """日本時間の PC でも撮影日時がファイル名の時刻とずれない。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self._tz = os.environ.get("TZ")

    def tearDown(self):
        if self._tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._tz
        if hasattr(__import__("time"), "tzset"):
            __import__("time").tzset()

    def test_created_text_is_camera_clock(self):
        import time
        shot = datetime.datetime(2026, 9, 14, 14, 56, 35,
                                 tzinfo=datetime.timezone.utc)
        data = bytearray(build_multi_sample_mp4("X", 30))
        ct = int((shot - EPOCH).total_seconds())
        i = data.find(b"mvhd")
        data[i + 8:i + 16] = struct.pack(">II", ct, ct)
        p = os.path.join(self.dir, "DJI_20260914145635_0011_D.MP4")
        with open(p, "wb") as f:
            f.write(bytes(data))
        if hasattr(time, "tzset"):
            os.environ["TZ"] = "Asia/Tokyo"
            time.tzset()
        e = browse.analyze_file(p)
        # 旧実装は astimezone() で 23:56 (翌日になることも) と表示していた
        self.assertEqual(e.created_text, "2026/09/14 14:56")

    def test_dji_utc_mvhd_shows_filename_time(self):
        """Osmo Pocket 4 Pro は mvhd に UTC を書く (実測: 名前 13:04:11 JST に
        対し動画内 04:04:12)。表示はファイル名の時刻 (JST) にする。"""
        inner = datetime.datetime(2026, 9, 13, 4, 4, 12,
                                  tzinfo=datetime.timezone.utc)
        data = bytearray(build_multi_sample_mp4("X", 30))
        ct = int((inner - EPOCH).total_seconds())
        i = data.find(b"mvhd")
        data[i + 8:i + 16] = struct.pack(">II", ct, ct)
        p = os.path.join(self.dir, "DJI_20260913130411_0001_D.MP4")
        with open(p, "wb") as f:
            f.write(bytes(data))
        e = browse.analyze_file(p)
        self.assertEqual(e.created_text, "2026/09/13 13:04")
        self.assertEqual(e.created_source, "filename")
        self.assertIn("動画内の記録 04:04 は -9:00 ずれている", e.created_note)
        # 差分計算用の値は動画内のまま (判定は同じ基準同士で比べる)
        self.assertEqual(e.created, inner)
        # ファイル名に時刻が無いファイルは補足なし
        q = os.path.join(self.dir, "GH010001.MP4")
        with open(q, "wb") as f:
            f.write(bytes(data))
        e2 = browse.analyze_file(q)
        self.assertEqual(e2.created_text, "2026/09/13 04:04")
        self.assertEqual(e2.created_note, "")
