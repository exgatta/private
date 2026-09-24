"""他機種テレメトリ (sources.py) のテスト。"""

import io
import os
import struct
import tempfile
import unittest

from gpmf_tool import mp4, sources
from gpmf_tool.tests.test_mp4_inject import _box, _full, _MATRIX, VIDEO_DATA
from gpmf_tool.tests.test_detect import _with_xyz


# --- 埋め込み字幕トラック付き MP4 を合成する ---------------------------------

def build_subtitle_mp4(texts, dur_ms=1000):
    timescale = 1000
    total = dur_ms * len(texts)
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2")

    samples = [struct.pack(">H", len(t.encode())) + t.encode("utf-8")
               for t in texts]
    blob = b"".join(samples)
    ftyp_len = len(ftyp)
    mdat_offset = ftyp_len
    sample_start = mdat_offset + 8

    mvhd = _full(b"mvhd", 0, 0,
                 struct.pack(">IIII", 0, 0, timescale, total)
                 + struct.pack(">iH", 0x00010000, 0x0100) + b"\x00" * 10
                 + _MATRIX + b"\x00" * 24 + struct.pack(">I", 2))
    tkhd = _full(b"tkhd", 0, 3,
                 struct.pack(">IIIII", 0, 0, 1, 0, total)
                 + b"\x00" * 8 + struct.pack(">hhhh", 0, 0, 0, 0)
                 + _MATRIX + struct.pack(">II", 0, 0))
    mdhd = _full(b"mdhd", 0, 0,
                 struct.pack(">IIII", 0, 0, timescale, total)
                 + struct.pack(">Hh", 0x55C4, 0))
    hdlr = _full(b"hdlr", 0, 0,
                 b"\x00" * 4 + b"sbtl" + b"\x00" * 12 + b"Subtitle\x00")
    tx3g = _box(b"tx3g", b"\x00" * 6 + struct.pack(">H", 1) + b"\x00" * 38)
    stsd = _full(b"stsd", 0, 0, struct.pack(">I", 1) + tx3g)
    stts = _full(b"stts", 0, 0,
                 struct.pack(">I", 1) + struct.pack(">II", len(texts), dur_ms))
    stsc = _full(b"stsc", 0, 0,
                 struct.pack(">I", 1) + struct.pack(">III", 1, len(texts), 1))
    stsz = _full(b"stsz", 0, 0, struct.pack(">II", 0, len(samples))
                 + b"".join(struct.pack(">I", len(s)) for s in samples))
    stco = _full(b"stco", 0, 0,
                 struct.pack(">I", 1) + struct.pack(">I", sample_start))
    stbl = _box(b"stbl", stsd + stts + stsc + stsz + stco)
    minf = _box(b"minf", _box(b"gmhd", b"") + stbl)
    mdia = _box(b"mdia", mdhd + hdlr + minf)
    trak = _box(b"trak", tkhd + mdia)
    moov = _box(b"moov", mvhd + trak)
    mdat = _box(b"mdat", blob)
    return ftyp + mdat + moov


class TestSRTParsing(unittest.TestCase):

    def test_dji_label_dialect(self):
        srt = ("1\n00:00:00,000 --> 00:00:01,000\n"
               "2024-06-01 09:00:00.000 [latitude: 35.6586] "
               "[longitude: 139.7454] [rel_alt: 0.0 abs_alt: 12.3]\n")
        pts, start = sources.parse_srt(srt)
        self.assertEqual(len(pts), 1)
        self.assertAlmostEqual(pts[0].lat, 35.6586, places=4)
        self.assertAlmostEqual(pts[0].lon, 139.7454, places=4)
        self.assertAlmostEqual(pts[0].ele, 12.3, places=1)
        self.assertEqual(start.year, 2024)

    def test_dji_paren_dialect_lon_first(self):
        # DJI は GPS(経度, 緯度, ...) 順。lon=139>90 で判別
        srt = ("1\n00:00:00,000 --> 00:00:00,500\n"
               "GPS(139.7454,35.6586,14) BAROMETER:12.3\n")
        pts, _ = sources.parse_srt(srt)
        self.assertAlmostEqual(pts[0].lat, 35.6586, places=4)
        self.assertAlmostEqual(pts[0].lon, 139.7454, places=4)

    def test_time_from_cue(self):
        srt = ("1\n00:00:00,000 --> 00:00:01,000\n[latitude: 35.0] [longitude: 139.0]\n\n"
               "2\n00:00:02,000 --> 00:00:03,000\n[latitude: 35.1] [longitude: 139.1]\n")
        pts, _ = sources.parse_srt(srt)
        self.assertEqual([p.time for p in pts], [0.0, 2.0])

    def test_no_gps_returns_empty(self):
        srt = "1\n00:00:00,000 --> 00:00:01,000\nHello world\n"
        pts, _ = sources.parse_srt(srt)
        self.assertEqual(pts, [])


class TestLoadVideoTelemetry(unittest.TestCase):

    def test_embedded_subtitle_track(self):
        data = build_subtitle_mp4([
            "2024-06-01 09:00:00 [latitude: 35.10] [longitude: 139.20] [abs_alt: 5.0]",
            "2024-06-01 09:00:01 [latitude: 35.11] [longitude: 139.21] [abs_alt: 6.0]",
        ])
        f = io.BytesIO(data)
        entries = sources.extract_subtitle_entries(f)
        self.assertEqual(len(entries), 2)
        f.seek(0)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            tf.write(data)
            path = tf.name
        try:
            got = sources.load_video_telemetry(path)
            self.assertIsNotNone(got)
            pts, start, label = got
            self.assertIn("字幕", label)
            self.assertEqual(len(pts), 2)
            self.assertAlmostEqual(pts[1].lon, 139.21, places=2)
        finally:
            os.unlink(path)

    def test_sidecar_srt(self):
        with tempfile.TemporaryDirectory() as d:
            from gpmf_tool.tests.test_mp4_inject import build_synthetic_mp4
            mp4_path = os.path.join(d, "DJI_0001.mp4")
            with open(mp4_path, "wb") as f:
                f.write(build_synthetic_mp4(moov_first=True, duration_sec=3))
            with open(os.path.join(d, "DJI_0001.srt"), "w") as f:
                f.write("1\n00:00:00,000 --> 00:00:01,000\n"
                        "[latitude: 35.5] [longitude: 139.5] [abs_alt: 3.0]\n")
            got = sources.load_video_telemetry(mp4_path)
            self.assertIsNotNone(got)
            pts, _, label = got
            self.assertIn("外部SRT", label)
            self.assertAlmostEqual(pts[0].lat, 35.5, places=3)

    def test_smartphone_single_point(self):
        data = _with_xyz("+35.6586+139.7454+12.3/")
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            tf.write(data)
            path = tf.name
        try:
            got = sources.load_video_telemetry(path)
            self.assertIsNotNone(got)
            pts, start, label = got
            self.assertIn("撮影地点", label)
            self.assertAlmostEqual(pts[0].lat, 35.6586, places=4)
            # 静止1点は同一座標2点で表現
            self.assertEqual(pts[0].lat, pts[1].lat)
        finally:
            os.unlink(path)

    def test_nothing_returns_none(self):
        from gpmf_tool.tests.test_mp4_inject import build_synthetic_mp4
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            tf.write(build_synthetic_mp4(moov_first=True))
            path = tf.name
        try:
            self.assertIsNone(sources.load_video_telemetry(path))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
