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



class TestCameraWallTime(unittest.TestCase):
    """撮影日時はカメラの時計の値をそのまま表示する (TZ 変換で 9 時間ずれない)。"""

    def test_creation_local_is_wall_clock(self):
        shot = datetime.datetime(2026, 9, 14, 14, 56, 35,
                                 tzinfo=datetime.timezone.utc)
        m = mp4.media_summary(io.BytesIO(build_rich_mp4(shot=shot)))
        self.assertEqual(m["creation_local"],
                         datetime.datetime(2026, 9, 14, 14, 56, 35))
        self.assertIsNone(m["creation_local"].tzinfo)
        self.assertEqual(m["creation_source"], "camera")

    def test_camera_wall_time_strips_tz(self):
        dt = datetime.datetime(2026, 9, 14, 14, 56, 35,
                               tzinfo=datetime.timezone.utc)
        self.assertEqual(mp4.camera_wall_time(dt),
                         datetime.datetime(2026, 9, 14, 14, 56, 35))
        self.assertIsNone(mp4.camera_wall_time(None))

    def test_wall_time_from_name(self):
        self.assertEqual(
            mp4.wall_time_from_name("/x/DJI_20260913130411_0001_D.MP4"),
            datetime.datetime(2026, 9, 13, 13, 4, 11))
        self.assertEqual(
            mp4.wall_time_from_name("VID_20250915_125402_00_062.mp4"),
            datetime.datetime(2025, 9, 15, 12, 54, 2))
        self.assertEqual(
            mp4.wall_time_from_name("LRV_20250915_125402_00_062.mp4"),
            datetime.datetime(2025, 9, 15, 12, 54, 2))
        self.assertIsNone(mp4.wall_time_from_name("GH010001.MP4"))
        self.assertIsNone(mp4.wall_time_from_name("DJI_0001.MP4"))
        self.assertIsNone(mp4.wall_time_from_name("DJI_20261399999999_0001_D.MP4"))

    def test_quicktime_creationdate_preferred(self):
        # iPhone 相当: タイムゾーン付きの正確な記録があればそれを使う
        blob = (b"xxxx" + b"com.apple.quicktime.creationdate" + b"\x00" * 8
                + b"2025-09-15T12:54:02+0900" + b"yyyy")
        aware, wall = mp4.parse_quicktime_creationdate(blob)
        self.assertEqual(wall, datetime.datetime(2025, 9, 15, 12, 54, 2))
        self.assertEqual(aware.utcoffset(), datetime.timedelta(hours=9))
        self.assertIsNone(mp4.parse_quicktime_creationdate(b"no key here"))
if __name__ == "__main__":
    unittest.main()
