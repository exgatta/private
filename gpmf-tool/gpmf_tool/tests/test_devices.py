"""機種プリセット (HERO / MAX / Fusion) のテスト。"""

import io
import unittest

from gpmf_tool import gopro, klv, mp4, telemetry
from gpmf_tool.tests.test_mp4_inject import build_synthetic_mp4


class TestDevicePresets(unittest.TestCase):

    def test_max_and_fusion_exist(self):
        self.assertIn("max", gopro.DEVICE_PRESETS)
        self.assertIn("fusion", gopro.DEVICE_PRESETS)
        self.assertTrue(gopro.DEVICE_PRESETS["max"].is_360)
        self.assertTrue(gopro.DEVICE_PRESETS["fusion"].is_360)
        self.assertFalse(gopro.DEVICE_PRESETS["hero11"].is_360)

    def test_inject_as_max(self):
        src = io.BytesIO(build_synthetic_mp4(moov_first=True, duration_sec=3))
        payloads, durations = telemetry.build_device_only_payloads(
            3.0, gopro.DEVICE_PRESETS["max"].device_name)
        dst = io.BytesIO()
        mp4.inject_gpmf_track(
            src, dst, payloads, durations,
            udta_extra=gopro.build_udta_boxes(
                gopro.DEVICE_PRESETS["max"], serial_seed="max-test"))
        dst.seek(0)
        # gpmd の DVNM が GoPro Max
        samples = mp4.extract_gpmf_samples(dst)
        items = klv.parse(samples[0].data)
        self.assertEqual(items[0].find_first("DVNM").value(), "GoPro Max")
        # udta FIRM が MAX 用
        dst.seek(0)
        tops = mp4.scan_top_level(dst)
        moov = mp4.parse_box_tree(
            mp4.read_box_bytes(dst, next(b for b in tops if b.type == b"moov")),
            b"moov")
        firm = next(c for c in moov.find(b"udta").children
                    if c.type == b"FIRM")
        self.assertEqual(firm.payload, b"H19.03.02.00")

    def test_max_in_cli_choices(self):
        # CLI/GUI の選択肢に自動で入る
        self.assertIn("max", sorted(gopro.DEVICE_PRESETS))


if __name__ == "__main__":
    unittest.main()
