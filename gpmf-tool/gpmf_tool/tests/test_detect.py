"""位置情報・テレメトリ検出のテスト。"""

import io
import struct
import unittest

from gpmf_tool import gopro, mp4, telemetry
from gpmf_tool.tests.test_mp4_inject import build_synthetic_mp4, _box


def _with_xyz(iso: str) -> bytes:
    """合成 MP4 の moov/udta に ©xyz (ISO6709) を足す。"""
    raw = build_synthetic_mp4(moov_first=True, duration_sec=4)
    tops = mp4.scan_top_level(io.BytesIO(raw))
    moov_top = next(b for b in tops if b.type == b"moov")
    moov = mp4.parse_box_tree(
        raw[moov_top.offset:moov_top.offset + moov_top.size], b"moov")
    payload = struct.pack(">HH", len(iso), 0x15C7) + iso.encode("ascii")
    xyz = _box(b"\xa9xyz", payload)
    moov.children.append(mp4.Box(type=b"udta", is_container=True,
                                 children=mp4._parse_children(xyz, 0, len(xyz))))
    ftyp = raw[tops[0].offset:tops[0].offset + tops[0].size]
    mdat_top = next(b for b in tops if b.type == b"mdat")
    mdat = raw[mdat_top.offset:mdat_top.offset + mdat_top.size]
    return ftyp + moov.serialize() + mdat


class TestDetect(unittest.TestCase):

    def test_plain_video_has_nothing(self):
        f = io.BytesIO(build_synthetic_mp4(moov_first=True))
        t = mp4.detect_telemetry(f)
        self.assertFalse(t["gpmd"])
        self.assertFalse(t["camm"])
        self.assertIsNone(t["location_iso6709"])
        self.assertEqual(t["formats"], [])

    def test_phone_location(self):
        f = io.BytesIO(_with_xyz("+35.6586+139.7454+12.3/"))
        t = mp4.detect_telemetry(f)
        self.assertIsNotNone(t["location_iso6709"])
        lat, lon, ele = t["location_iso6709"]
        self.assertAlmostEqual(lat, 35.6586, places=4)
        self.assertAlmostEqual(lon, 139.7454, places=4)
        self.assertAlmostEqual(ele, 12.3, places=1)
        self.assertIn("撮影地点の GPS 座標 (ISO6709)", t["formats"])

    def test_location_without_altitude(self):
        f = io.BytesIO(_with_xyz("+35.0+139.0/"))
        t = mp4.detect_telemetry(f)
        lat, lon, ele = t["location_iso6709"]
        self.assertIsNone(ele)

    def test_gopro_injected_detected_as_gpmd(self):
        src = io.BytesIO(build_synthetic_mp4(moov_first=True, duration_sec=3))
        payloads, durations = telemetry.build_device_only_payloads(3.0, "X")
        dst = io.BytesIO()
        mp4.inject_gpmf_track(src, dst, payloads, durations,
                              udta_extra=gopro.build_udta_boxes(
                                  gopro.DEVICE_PRESETS["hero9"], "s"))
        dst.seek(0)
        t = mp4.detect_telemetry(dst)
        self.assertTrue(t["gpmd"])
        self.assertIn("GoPro GPMF (gpmd トラック)", t["formats"])
        self.assertIn("GPMF", t["gopro_udta"])

    def test_iso6709_parser(self):
        self.assertEqual(mp4._parse_iso6709("+35.5-139.5/")[:2], (35.5, -139.5))
        self.assertIsNone(mp4._parse_iso6709("garbage"))


if __name__ == "__main__":
    unittest.main()
