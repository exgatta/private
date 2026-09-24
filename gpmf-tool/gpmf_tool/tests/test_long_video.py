"""長尺動画 (duration が 32bit を超える) のテスト。

Insta360 等はムービータイムスケールがマイクロ秒 (1,000,000) のことがあり、
約 71.6 分を超えると duration が 32bit に収まらず struct.error になっていた。
64bit (version 1) の tkhd / mdhd へ自動フォールバックすることを検証する。
"""

import io
import struct
import unittest

from gpmf_tool import gopro, klv, mp4, telemetry
from gpmf_tool.tests.test_mp4_inject import (VIDEO_DATA, _box, _full,
                                             _MATRIX)

MAX32 = 0xFFFFFFFF


def build_long_mp4(duration_sec: int, timescale: int = 1_000_000) -> bytes:
    """マイクロ秒タイムスケールの長尺 MP4 を合成する (mvhd は version 1)。"""
    duration = duration_sec * timescale
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2avc1")
    mdat = _box(b"mdat", VIDEO_DATA)

    # mvhd version 1 (64bit duration)
    mvhd = _full(b"mvhd", 1, 0,
                 struct.pack(">QQIQ", 0, 0, timescale, duration)
                 + struct.pack(">iH", 0x00010000, 0x0100) + b"\x00" * 10
                 + _MATRIX + b"\x00" * 24 + struct.pack(">I", 2))
    tkhd = _full(b"tkhd", 1, 3,
                 struct.pack(">QQIIQ", 0, 0, 1, 0, duration)
                 + b"\x00" * 8 + struct.pack(">hhhh", 0, 0, 0, 0)
                 + _MATRIX + struct.pack(">II", 640 << 16, 480 << 16))
    mdhd = _full(b"mdhd", 1, 0,
                 struct.pack(">QQIQ", 0, 0, timescale, duration)
                 + struct.pack(">Hh", 0x55C4, 0))
    hdlr = _full(b"hdlr", 0, 0,
                 b"\x00" * 4 + b"vide" + b"\x00" * 12 + b"VideoHandler\x00")
    stsd = _full(b"stsd", 0, 0, struct.pack(">I", 1)
                 + _box(b"avc1", b"\x00" * 6 + struct.pack(">H", 1) + b"\x00" * 70))
    # stts の delta は 32bit なので、実ファイル同様に複数サンプルへ分割する
    n_samples = 100
    delta = duration // n_samples
    stts = _full(b"stts", 0, 0,
                 struct.pack(">I", 1) + struct.pack(">II", n_samples, delta))
    stsc = _full(b"stsc", 0, 0, struct.pack(">I", 1) + struct.pack(">III", 1, 1, 1))
    stsz = _full(b"stsz", 0, 0, struct.pack(">II", 0, 1)
                 + struct.pack(">I", len(VIDEO_DATA)))
    stco = _full(b"stco", 0, 0,
                 struct.pack(">I", 1) + struct.pack(">I", len(ftyp) + 8))
    stbl = _box(b"stbl", stsd + stts + stsc + stsz + stco)
    minf = _box(b"minf", _full(b"vmhd", 0, 1, b"\x00" * 8) + stbl)
    mdia = _box(b"mdia", mdhd + hdlr + minf)
    moov = _box(b"moov", mvhd + _box(b"trak", tkhd + mdia))
    return ftyp + mdat + moov


class TestLongVideo(unittest.TestCase):

    def test_mvhd_v1_parsed(self):
        f = io.BytesIO(build_long_mp4(5000))
        self.assertAlmostEqual(mp4.movie_duration_seconds(f), 5000.0, places=1)

    def test_trak_uses_64bit_when_needed(self):
        trak = mp4.build_gpmd_trak(3, 1_000_000, 5000 * 1_000_000,
                                   [100], [1000], 1000)
        box = mp4.parse_box_tree(trak, b"trak")
        self.assertEqual(box.find(b"tkhd").payload[0], 1, "tkhd が 64bit でない")
        self.assertEqual(box.find(b"mdia", b"mdhd").payload[0], 1)

    def test_trak_stays_32bit_when_small(self):
        trak = mp4.build_gpmd_trak(3, 1_000_000, 74 * 1_000_000,
                                   [100], [1000], 1000)
        box = mp4.parse_box_tree(trak, b"trak")
        self.assertEqual(box.find(b"tkhd").payload[0], 0)
        self.assertEqual(box.find(b"mdia", b"mdhd").payload[0], 0)

    def test_inject_long_video_end_to_end(self):
        """従来 'argument out of range' で失敗していた長尺動画の注入。"""
        duration_sec = 5000  # 約83分 → 32bit超え
        src = io.BytesIO(build_long_mp4(duration_sec))
        payloads, durations = telemetry.build_device_only_payloads(
            float(duration_sec), "GoPro Max")
        dst = io.BytesIO()
        stats = mp4.inject_gpmf_track(
            src, dst, payloads, durations,
            udta_extra=gopro.build_udta_boxes(
                gopro.DEVICE_PRESETS["max"], serial_seed="long"),
            new_ftyp=mp4.build_ftyp_gopro(),
            handler_renames=gopro.HANDLER_RENAMES)
        self.assertEqual(stats["payload_count"], duration_sec)

        # 注入結果が読み戻せる
        dst.seek(0)
        samples = mp4.extract_gpmf_samples(dst)
        self.assertEqual(len(samples), duration_sec)
        items = klv.parse(samples[0].data)
        self.assertEqual(items[0].find_first("DVNM").value(), "GoPro Max")

        # 元の映像データが無傷
        dst.seek(0)
        tops = mp4.scan_top_level(dst)
        moov = mp4.parse_box_tree(
            mp4.read_box_bytes(dst, next(b for b in tops if b.type == b"moov")),
            b"moov")
        vtrak = next(t for t in moov.find_all(b"trak")
                     if mp4.parse_hdlr(
                         t.find(b"mdia", b"hdlr").payload)["handler"] == b"vide")
        off = mp4.parse_stco(
            vtrak.find(b"mdia", b"minf", b"stbl", b"stco").payload, False)[0]
        dst.seek(off)
        self.assertEqual(dst.read(len(VIDEO_DATA)), VIDEO_DATA)


if __name__ == "__main__":
    unittest.main()
