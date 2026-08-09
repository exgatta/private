"""動画基本情報 (撮影日時・解像度・fps・コーデック) 抽出のテスト。"""

import datetime
import io
import struct
import unittest

from gpmf_tool import mp4
from gpmf_tool.tests.test_mp4_inject import _box, _full, _MATRIX, VIDEO_DATA


def build_rich_mp4(shot=None, w=5760, h=2880, fps=30, dur_sec=74,
                   codec=b"avc1", ts=1_000_000):
    epoch = datetime.datetime(1904, 1, 1, tzinfo=datetime.timezone.utc)
    ct = int((shot - epoch).total_seconds()) if shot else 0
    dur = dur_sec * ts
    mvhd = _full(b"mvhd", 0, 0,
                 struct.pack(">IIII", ct, ct, ts, dur)
                 + struct.pack(">iH", 0x10000, 0x100) + b"\x00" * 10
                 + _MATRIX + b"\x00" * 24 + struct.pack(">I", 2))
    entry = (b"\x00" * 6 + struct.pack(">H", 1) + b"\x00" * 16
             + struct.pack(">HH", w, h) + b"\x00" * 50)
    stsd = _full(b"stsd", 0, 0, struct.pack(">I", 1) + _box(codec, entry))
    mdhd = _full(b"mdhd", 0, 0,
                 struct.pack(">IIII", ct, ct, ts, dur) + struct.pack(">Hh", 0x55C4, 0))
    hdlr = _full(b"hdlr", 0, 0,
                 b"\x00" * 4 + b"vide" + b"\x00" * 12 + b"VideoHandler\x00")
    frames = fps * dur_sec
    stts = _full(b"stts", 0, 0,
                 struct.pack(">I", 1) + struct.pack(">II", frames, dur // frames))
    stsc = _full(b"stsc", 0, 0, struct.pack(">I", 1) + struct.pack(">III", 1, 1, 1))
    stsz = _full(b"stsz", 0, 0, struct.pack(">II", 0, 1)
                 + struct.pack(">I", len(VIDEO_DATA)))
    stco = _full(b"stco", 0, 0, struct.pack(">I", 1) + struct.pack(">I", 9999))
    stbl = _box(b"stbl", stsd + stts + stsc + stsz + stco)
    minf = _box(b"minf", _full(b"vmhd", 0, 1, b"\x00" * 8) + stbl)
    trak = _box(b"trak", _full(b"tkhd", 0, 3,
                struct.pack(">IIIII", ct, ct, 1, 0, dur) + b"\x00" * 8
                + struct.pack(">hhhh", 0, 0, 0, 0) + _MATRIX
                + struct.pack(">II", w << 16, h << 16))
                + _box(b"mdia", mdhd + hdlr + minf))
    moov = _box(b"moov", mvhd + trak)
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isom")
    return ftyp + _box(b"mdat", VIDEO_DATA) + moov


class TestMediaSummary(unittest.TestCase):

    def test_full_info(self):
        shot = datetime.datetime(2025, 9, 15, 12, 54, 2,
                                 tzinfo=datetime.timezone.utc)
        m = mp4.media_summary(io.BytesIO(build_rich_mp4(shot=shot)))
        self.assertAlmostEqual(m["duration_sec"], 74.0, places=1)
        self.assertEqual(m["creation_time"], shot)
        self.assertEqual((m["width"], m["height"]), (5760, 2880))
        self.assertAlmostEqual(m["fps"], 30.0, places=1)
        self.assertEqual(m["video_codec"], "H.264 (AVC)")

    def test_hevc_codec_name(self):
        m = mp4.media_summary(io.BytesIO(build_rich_mp4(codec=b"hvc1")))
        self.assertEqual(m["video_codec"], "H.265 (HEVC)")

    def test_no_creation_time(self):
        m = mp4.media_summary(io.BytesIO(build_rich_mp4(shot=None)))
        self.assertIsNone(m["creation_time"])

    def test_mp4_time_conversion(self):
        # 1904 起点。0 は None
        self.assertIsNone(mp4.mp4_time_to_datetime(0))
        dt = mp4.mp4_time_to_datetime(int(
            (datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
             - datetime.datetime(1904, 1, 1, tzinfo=datetime.timezone.utc))
            .total_seconds()))
        self.assertEqual(dt.year, 2020)


if __name__ == "__main__":
    unittest.main()
