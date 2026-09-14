"""stsd の比較用正規化 (mp4.normalize_stsd) のテスト。

ファイルごとに変わって当然の値 (btrt / esds のビットレート) だけを消し、
コーデック・解像度・デコーダ設定の違いは残ることを検証する。
"""

import struct
import unittest

from gpmf_tool import mp4
from gpmf_tool.mp4 import _box, _full
from gpmf_tool.tests.test_concat import make_esds, make_mp4a_entry


def _stsd(*entries: bytes) -> bytes:
    return (b"\x00\x00\x00\x00" + struct.pack(">I", len(entries))
            + b"".join(entries))


def _avc1(width=1920, height=1080, avcc=b"\x01\x64\x00\x28\xff", btrt=None):
    body = (b"\x00" * 6 + struct.pack(">H", 1) + b"\x00" * 16
            + struct.pack(">HH", width, height) + b"\x00" * 50
            + _box(b"avcC", avcc))
    if btrt is not None:
        body += _box(b"btrt", btrt)
    return _box(b"avc1", body)


class TestNormalizeStsd(unittest.TestCase):

    def test_btrt_ignored_for_video(self):
        a = _stsd(_avc1(btrt=struct.pack(">III", 1000, 120_000_000, 98_765_432)))
        b = _stsd(_avc1(btrt=struct.pack(">III", 900, 110_000_000, 12_345_678)))
        c = _stsd(_avc1())
        self.assertNotEqual(a, b)
        self.assertEqual(mp4.normalize_stsd(a), mp4.normalize_stsd(b))
        self.assertEqual(mp4.normalize_stsd(a), mp4.normalize_stsd(c))

    def test_video_real_differences_kept(self):
        a = mp4.normalize_stsd(_stsd(_avc1()))
        self.assertNotEqual(a, mp4.normalize_stsd(_stsd(_avc1(width=1280, height=720))))
        self.assertNotEqual(a, mp4.normalize_stsd(_stsd(_avc1(avcc=b"\x01\x64\x00\x29\xff"))))
        hvc1 = _box(b"hvc1", _box(b"avc1", b"")[8:] + b"\x00" * 78)
        self.assertNotEqual(a, mp4.normalize_stsd(_stsd(hvc1)))

    def test_esds_bitrate_ignored_for_audio(self):
        a = _stsd(_box(b"mp4a", make_mp4a_entry(128000, 160000)))
        b = _stsd(_box(b"mp4a", make_mp4a_entry(97531, 150000)))
        self.assertNotEqual(a, b)
        self.assertEqual(mp4.normalize_stsd(a), mp4.normalize_stsd(b))
        # 正規化後は bufferSizeDB/max/avg が 0 埋めされている
        norm = mp4.normalize_stsd(a)
        i = norm.find(b"esds")
        self.assertNotEqual(i, -1)
        self.assertIn(b"\x40\x15" + b"\x00" * 11, norm[i:])

    def test_audio_real_differences_kept(self):
        a = mp4.normalize_stsd(_stsd(_box(b"mp4a", make_mp4a_entry(128000))))
        for other in (make_mp4a_entry(128000, sample_rate=44100),
                      make_mp4a_entry(128000, channels=1),
                      make_mp4a_entry(128000, dsi=b"\x12\x10")):
            self.assertNotEqual(a, mp4.normalize_stsd(_stsd(_box(b"mp4a", other))))

    def test_qt_version1_audio_entry(self):
        """QuickTime 版 (version 1: 固定部 +16 バイト) でも esds を見つける。"""
        def entry(avg):
            return (b"\x00" * 6 + struct.pack(">H", 1)
                    + struct.pack(">HH", 1, 0) + b"\x00" * 4   # version 1
                    + struct.pack(">HHHH", 2, 16, 0, 0)
                    + struct.pack(">I", 48000 << 16)
                    + struct.pack(">IIII", 1024, 2, 2, 4)      # v1 拡張
                    + make_esds(avg, 200000))
        a = _stsd(_box(b"mp4a", entry(100000)))
        b = _stsd(_box(b"mp4a", entry(123456)))
        self.assertEqual(mp4.normalize_stsd(a), mp4.normalize_stsd(b))

    def test_unknown_entry_and_garbage_passthrough(self):
        gpmd = _stsd(_box(b"gpmd", b"\x00" * 6 + struct.pack(">H", 1)))
        self.assertEqual(mp4.normalize_stsd(gpmd), gpmd)
        self.assertEqual(mp4.normalize_stsd(b"\x00\x01"), b"\x00\x01")
        broken = b"\x00\x00\x00\x00" + struct.pack(">I", 1) + b"\x00\x00\x00\x03avc"
        self.assertEqual(mp4.normalize_stsd(broken), broken)
        # 子ボックスのサイズが壊れていても例外にならず、元の情報が失われない
        bad_child = _stsd(_box(b"avc1", b"\x00" * 78 + b"\x00\x00\x00\x02xx"))
        self.assertIsInstance(mp4.normalize_stsd(bad_child), bytes)

    def test_full_box_helper_unused_but_importable(self):
        self.assertTrue(callable(_full))


if __name__ == "__main__":
    unittest.main()
