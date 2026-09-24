"""MP4 注入 → 抽出のラウンドトリップテスト。

合成した最小 MP4 (ftyp + moov + mdat / ftyp + mdat + moov) に GPMF を注入し、
- gpmd トラックが抽出できること
- 既存トラックの stco がレイアウト変更後も正しいデータを指すこと
- udta / ftyp / hdlr の GoPro 化
を検証する。
"""

import datetime
import io
import struct
import unittest

from gpmf_tool import gopro, klv, mp4, telemetry

VIDEO_DATA = b"VIDEO_SAMPLE_DATA_0123456789"


def _box(t, body):
    return struct.pack(">I", 8 + len(body)) + t + body


def _full(t, version, flags, body):
    return _box(t, struct.pack(">B", version) + flags.to_bytes(3, "big") + body)


_MATRIX = struct.pack(">9i", 0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000)


def build_synthetic_mp4(moov_first: bool, duration_sec: int = 3) -> bytes:
    """最小構成の MP4 (映像トラック 1 本) を合成する。"""
    timescale = 600
    duration = duration_sec * timescale

    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2avc1")
    mdat = _box(b"mdat", VIDEO_DATA)

    def build_moov(mdat_offset: int) -> bytes:
        mvhd = _full(b"mvhd", 0, 0,
                     struct.pack(">IIII", 0, 0, timescale, duration)
                     + struct.pack(">iH", 0x00010000, 0x0100) + b"\x00" * 10
                     + _MATRIX + b"\x00" * 24
                     + struct.pack(">I", 2))  # next_track_id
        tkhd = _full(b"tkhd", 0, 3,
                     struct.pack(">IIIII", 0, 0, 1, 0, duration)
                     + b"\x00" * 8 + struct.pack(">hhhh", 0, 0, 0, 0)
                     + _MATRIX + struct.pack(">II", 640 << 16, 480 << 16))
        mdhd = _full(b"mdhd", 0, 0,
                     struct.pack(">IIII", 0, 0, timescale, duration)
                     + struct.pack(">Hh", 0x55C4, 0))
        hdlr = _full(b"hdlr", 0, 0,
                     b"\x00" * 4 + b"vide" + b"\x00" * 12 + b"VideoHandler\x00")
        stsd = _full(b"stsd", 0, 0, struct.pack(">I", 1)
                     + _box(b"avc1", b"\x00" * 6 + struct.pack(">H", 1)
                            + b"\x00" * 70))
        stts = _full(b"stts", 0, 0,
                     struct.pack(">I", 1) + struct.pack(">II", 1, duration))
        stsc = _full(b"stsc", 0, 0,
                     struct.pack(">I", 1) + struct.pack(">III", 1, 1, 1))
        stsz = _full(b"stsz", 0, 0,
                     struct.pack(">II", 0, 1) + struct.pack(">I", len(VIDEO_DATA)))
        stco = _full(b"stco", 0, 0,
                     struct.pack(">I", 1) + struct.pack(">I", mdat_offset + 8))
        stbl = _box(b"stbl", stsd + stts + stsc + stsz + stco)
        vmhd = _full(b"vmhd", 0, 1, b"\x00" * 8)
        minf = _box(b"minf", vmhd + stbl)
        mdia = _box(b"mdia", mdhd + hdlr + minf)
        trak = _box(b"trak", tkhd + mdia)
        return _box(b"moov", mvhd + trak)

    if moov_first:
        # moov のサイズは mdat_offset に依存しないので 2 パス不要
        probe = build_moov(0)
        mdat_offset = len(ftyp) + len(probe)
        return ftyp + build_moov(mdat_offset) + mdat
    mdat_offset = len(ftyp)
    return ftyp + mdat + build_moov(mdat_offset)


def make_test_points(n=30, rate=10.0):
    pts = []
    for i in range(n):
        t = i / rate
        pts.append(telemetry.GPSPoint(
            time=t, lat=35.6586 + t * 1e-5, lon=139.7454 + t * 1e-5,
            ele=100.0 + t, speed2d=1.5, speed3d=1.6))
    return pts


class TestInjectExtract(unittest.TestCase):

    def _inject(self, moov_first: bool):
        src_bytes = build_synthetic_mp4(moov_first=moov_first, duration_sec=3)
        start = datetime.datetime(2024, 1, 2, 3, 4, 5,
                                  tzinfo=datetime.timezone.utc)
        points = make_test_points(30)
        payloads, durations = telemetry.build_payloads(
            points, 3.0, "HERO9 Black", start)
        self.assertEqual(len(payloads), 3)
        self.assertEqual(durations, [1000, 1000, 1000])

        preset = gopro.DEVICE_PRESETS["hero9"]
        udta = gopro.build_udta_boxes(preset, serial_seed="test")

        src, dst = io.BytesIO(src_bytes), io.BytesIO()
        stats = mp4.inject_gpmf_track(
            src, dst, payloads, durations,
            udta_extra=udta,
            new_ftyp=mp4.build_ftyp_gopro(),
            handler_renames=gopro.HANDLER_RENAMES,
        )
        self.assertEqual(stats["track_id"], 2)
        return src_bytes, dst.getvalue(), payloads

    def _verify(self, out_bytes, payloads):
        out = io.BytesIO(out_bytes)

        # --- 既存映像トラックの stco がまだ正しいデータを指す ---
        tops = mp4.scan_top_level(out)
        moov_top = next(b for b in tops if b.type == b"moov")
        moov = mp4.parse_box_tree(mp4.read_box_bytes(out, moov_top), b"moov")
        video_trak = next(t for t in moov.find_all(b"trak")
                          if mp4.parse_hdlr(
                              t.find(b"mdia", b"hdlr").payload)["handler"] == b"vide")
        stco = mp4.parse_stco(
            video_trak.find(b"mdia", b"minf", b"stbl", b"stco").payload, False)
        out.seek(stco[0])
        self.assertEqual(out.read(len(VIDEO_DATA)), VIDEO_DATA,
                         "映像チャンクオフセットの補正が壊れている")

        # --- moov はトップレベル最後 (レイアウト保証) ---
        self.assertEqual(tops[-1].type, b"moov")

        # --- gpmd サンプルが元のペイロードと一致 ---
        samples = mp4.extract_gpmf_samples(out)
        self.assertEqual([s.data for s in samples], payloads)
        self.assertAlmostEqual(samples[1].time_sec, 1.0)
        self.assertAlmostEqual(samples[1].duration_sec, 1.0)

        # --- GPMF 内容の検証 ---
        items = klv.parse(samples[0].data)
        devc = items[0]
        self.assertEqual(devc.key, "DEVC")
        self.assertEqual(devc.find_first("DVNM").value(), "HERO9 Black")
        gps5 = devc.find_first("GPS5")
        self.assertEqual(len(gps5.values), 10)  # 10 Hz × 1 秒
        lat = gps5.values[0][0] / telemetry.GPS5_SCALE[0]
        self.assertAlmostEqual(lat, 35.6586, places=5)

        # --- GoPro 識別情報 ---
        udta = moov.find(b"udta")
        types = [c.type for c in udta.children]
        for t in (b"FIRM", b"LENS", b"CAME", b"MUID", b"GPMF"):
            self.assertIn(t, types)
        firm = next(c for c in udta.children if c.type == b"FIRM")
        self.assertEqual(firm.payload, b"HD9.01.01.72.00")

        # udta GPMF ボックスの中身もパース可能
        gpmf_box = next(c for c in udta.children if c.type == b"GPMF")
        udta_items = klv.parse(gpmf_box.payload)
        self.assertEqual(udta_items[0].find_first("MINF").value(), "HERO9 Black")

        # --- ftyp が GoPro 風 / hdlr 名が変更済み ---
        self.assertEqual(tops[0].type, b"ftyp")
        out.seek(tops[0].offset)
        self.assertIn(b"mp41", out.read(tops[0].size))
        hdlr_info = mp4.parse_hdlr(video_trak.find(b"mdia", b"hdlr").payload)
        self.assertEqual(hdlr_info["name"], "GoPro AVC")

    def test_roundtrip_moov_first(self):
        _, out_bytes, payloads = self._inject(moov_first=True)
        self._verify(out_bytes, payloads)

    def test_roundtrip_moov_last(self):
        _, out_bytes, payloads = self._inject(moov_first=False)
        self._verify(out_bytes, payloads)

    def test_double_inject_rejected(self):
        _, out_bytes, _ = self._inject(moov_first=True)
        payloads, durations = telemetry.build_device_only_payloads(3.0, "X")
        with self.assertRaises(mp4.MP4Error):
            mp4.inject_gpmf_track(io.BytesIO(out_bytes), io.BytesIO(),
                                  payloads, durations)

    def test_movie_duration(self):
        src = io.BytesIO(build_synthetic_mp4(moov_first=True, duration_sec=3))
        self.assertAlmostEqual(mp4.movie_duration_seconds(src), 3.0)

    def test_no_gpmd_track_error(self):
        src = io.BytesIO(build_synthetic_mp4(moov_first=True))
        with self.assertRaises(mp4.MP4Error):
            mp4.extract_gpmf_samples(src)


class TestGPXPipeline(unittest.TestCase):

    def test_resample_and_speed(self):
        points = [
            telemetry.GPSPoint(time=0, lat=35.0, lon=139.0, ele=0),
            telemetry.GPSPoint(time=10, lat=35.001, lon=139.0, ele=10),
        ]
        rs = telemetry.resample_track(points, duration_sec=10, rate_hz=10)
        self.assertEqual(len(rs), 100)
        self.assertAlmostEqual(rs[0].lat, 35.0, places=6)
        self.assertAlmostEqual(rs[-1].lat, 35.001, places=4)
        # 約 111m / 10s ≒ 11.1 m/s
        self.assertAlmostEqual(rs[50].speed2d, 11.1, delta=0.3)
        self.assertGreater(rs[50].speed3d, rs[50].speed2d)

    def test_fit_duration_stretch(self):
        points = [
            telemetry.GPSPoint(time=0, lat=35.0, lon=139.0, ele=0),
            telemetry.GPSPoint(time=100, lat=36.0, lon=139.0, ele=0),
        ]
        rs = telemetry.resample_track(points, duration_sec=10, rate_hz=1,
                                      fit_duration=True)
        # 動画 10 秒に 100 秒分のトラックが収まる
        # (最終サンプルは t=9s → ソースの 90s 地点 = lat 35.9)
        self.assertEqual(len(rs), 10)
        self.assertAlmostEqual(rs[-1].lat, 35.9, places=6)
        # 中間 (t=5s) はソース 50s 地点
        self.assertAlmostEqual(rs[5].lat, 35.5, places=6)

    def test_extract_gps_points_roundtrip(self):
        start = datetime.datetime(2024, 6, 1, tzinfo=datetime.timezone.utc)
        points = make_test_points(20)
        payloads, _ = telemetry.build_payloads(points, 2.0, "HERO9 Black", start)
        parsed = [(float(i), klv.parse(p)) for i, p in enumerate(payloads)]
        extracted = telemetry.extract_gps_points(parsed)
        self.assertEqual(len(extracted), 20)
        when, pt = extracted[0]
        self.assertAlmostEqual(pt.lat, points[0].lat, places=6)
        self.assertAlmostEqual(pt.ele, points[0].ele, places=2)
        self.assertEqual(when.year, 2024)


if __name__ == "__main__":
    unittest.main()
