"""360度動画マーカー (Spherical Metadata) の検出と保持のテスト。

Insta360 等が書き出した 360 度 MP4 を GoPro 化したとき、
360 度マーカーが消えないことを保証する。
"""

import io
import struct
import unittest

from gpmf_tool import gopro, mp4, telemetry
from gpmf_tool.tests.test_mp4_inject import build_synthetic_mp4, _box

SPHERICAL_XML = (
    b'<?xml version="1.0"?>'
    b'<rdf:SphericalVideo xmlns:GSpherical="http://ns.google.com/videos/1.0/spherical/">'
    b'<GSpherical:Spherical>true</GSpherical:Spherical>'
    b'<GSpherical:Stitched>true</GSpherical:Stitched>'
    b'<GSpherical:ProjectionType>equirectangular</GSpherical:ProjectionType>'
    b'</rdf:SphericalVideo>'
)


def build_360_mp4():
    """映像 trak の中に Spherical V1 (uuid) を持つ 360 度 MP4 を合成する。"""
    raw = build_synthetic_mp4(moov_first=False, duration_sec=5)
    tops = mp4.scan_top_level(io.BytesIO(raw))
    moov_top = next(b for b in tops if b.type == b"moov")
    moov = mp4.parse_box_tree(
        raw[moov_top.offset:moov_top.offset + moov_top.size], b"moov")

    # 映像 trak に uuid (spherical v1) を追加
    trak = next(moov.find_all(b"trak"))
    uuid_box = _box(b"uuid", mp4._SPHERICAL_V1_UUID + SPHERICAL_XML)
    trak.children.extend(mp4._parse_children(uuid_box, 0, len(uuid_box)))

    ftyp = raw[tops[0].offset:tops[0].offset + tops[0].size]
    mdat_top = next(b for b in tops if b.type == b"mdat")
    mdat = raw[mdat_top.offset:mdat_top.offset + mdat_top.size]
    # moov 末尾レイアウト。stco は元の mdat 位置を指したままだが
    # 注入時に remap されるので検証には影響しない
    return ftyp + mdat + moov.serialize()


class TestSpherical(unittest.TestCase):

    def test_detect_360(self):
        f = io.BytesIO(build_360_mp4())
        sph = mp4.detect_spherical(f)
        self.assertTrue(sph["v1"])
        self.assertTrue(sph["is_360"])
        self.assertEqual(sph["projection"], "equirectangular")

    def test_plain_video_not_360(self):
        f = io.BytesIO(build_synthetic_mp4(moov_first=True))
        sph = mp4.detect_spherical(f)
        self.assertFalse(sph["is_360"])
        self.assertFalse(sph["v1"])
        self.assertFalse(sph["v2"])

    def test_360_marker_survives_gopro_injection(self):
        """核心: GoPro MAX 化しても 360 度マーカーが保持される。"""
        src = io.BytesIO(build_360_mp4())
        payloads, durations = telemetry.build_device_only_payloads(
            5.0, "GoPro Max")
        dst = io.BytesIO()
        mp4.inject_gpmf_track(
            src, dst, payloads, durations,
            udta_extra=gopro.build_udta_boxes(
                gopro.DEVICE_PRESETS["max"], serial_seed="insta360"),
            new_ftyp=mp4.build_ftyp_gopro(),
            handler_renames=gopro.HANDLER_RENAMES)

        dst.seek(0)
        sph = mp4.detect_spherical(dst)
        self.assertTrue(sph["is_360"], "360度マーカーが消えた")
        self.assertTrue(sph["v1"])
        self.assertEqual(sph["projection"], "equirectangular")

        # GoPro 化も同時に成立している
        dst.seek(0)
        tele = mp4.detect_telemetry(dst)
        self.assertTrue(tele["gpmd"])

        # uuid ボックスが映像 trak 内に残っている
        dst.seek(0)
        tops = mp4.scan_top_level(dst)
        moov = mp4.parse_box_tree(
            mp4.read_box_bytes(dst, next(b for b in tops if b.type == b"moov")),
            b"moov")
        found = False
        for trak in moov.find_all(b"trak"):
            for c in trak.children:
                if c.type == b"uuid" and c.payload.startswith(
                        mp4._SPHERICAL_V1_UUID):
                    found = True
        self.assertTrue(found, "uuid(spherical) ボックスが trak から消えた")

    def test_v2_sv3d_detected(self):
        raw = build_synthetic_mp4(moov_first=True)
        # sv3d 相当のバイト列が moov にあれば V2 と判定
        f = io.BytesIO(raw.replace(b"VideoHandler", b"sv3d\x00Handler"))
        sph = mp4.detect_spherical(f)
        self.assertTrue(sph["v2"])


if __name__ == "__main__":
    unittest.main()
