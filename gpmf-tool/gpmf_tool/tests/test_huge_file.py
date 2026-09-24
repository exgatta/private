"""巨大ファイル (4GB 超 / co64) の取り扱いテスト。

Insta360 の長時間 360 度動画は 60GB を超えることがあり、
チャンクオフセットが 32bit に収まらず co64 が使われる。
注入時にそれらが壊れないことを保証する。
"""

import struct
import unittest

from gpmf_tool import mp4


def _stbl_with(box: mp4.Box) -> mp4.Box:
    return mp4.Box(type=b"moov", is_container=True, children=[
        mp4.Box(type=b"trak", is_container=True, children=[
            mp4.Box(type=b"mdia", is_container=True, children=[
                mp4.Box(type=b"minf", is_container=True, children=[
                    mp4.Box(type=b"stbl", is_container=True,
                            children=[box])])])])])


class TestHugeFile(unittest.TestCase):

    def test_co64_offsets_patched(self):
        """66GB 級の co64 オフセットが正しくずらされる。"""
        payload = (struct.pack(">I", 0) + struct.pack(">I", 2)
                   + struct.pack(">QQ", 70_000_000_000, 70_500_000_000))
        co64 = mp4.Box(type=b"co64", payload=payload)
        mp4.patch_chunk_offsets(_stbl_with(co64), remap=lambda o: o + 1000)
        vals = struct.unpack(">QQ", co64.payload[8:24])
        self.assertEqual(vals, (70_000_001_000, 70_500_001_000))

    def test_gpmd_uses_co64_beyond_4gb(self):
        """gpmd の格納位置が 4GB を超えるとき co64 を使う。"""
        trak = mp4.build_gpmd_trak(3, 1_000_000, 5412 * 1_000_000,
                                   [100], [1000],
                                   chunk_offset=70_000_000_000)
        stbl = mp4.parse_box_tree(trak, b"trak").find(
            b"mdia", b"minf", b"stbl")
        self.assertIsNotNone(stbl.find(b"co64"), "co64 が使われていない")
        self.assertIsNone(stbl.find(b"stco"))
        # 値も読み戻せる
        offs = mp4.parse_stco(stbl.find(b"co64").payload, is_co64=True)
        self.assertEqual(offs, [70_000_000_000])

    def test_gpmd_uses_stco_below_4gb(self):
        trak = mp4.build_gpmd_trak(3, 1_000_000, 74 * 1_000_000,
                                   [100], [1000], chunk_offset=1000)
        stbl = mp4.parse_box_tree(trak, b"trak").find(
            b"mdia", b"minf", b"stbl")
        self.assertIsNotNone(stbl.find(b"stco"))
        self.assertIsNone(stbl.find(b"co64"))

    def test_stco_overflow_raises_japanese_error(self):
        """32bit stco が 4GB を超える場合は日本語エラーで知らせる。"""
        payload = struct.pack(">I", 0) + struct.pack(">I", 1) + struct.pack(">I", 100)
        stco = mp4.Box(type=b"stco", payload=payload)
        with self.assertRaises(mp4.MP4Error) as cm:
            mp4.patch_chunk_offsets(_stbl_with(stco),
                                    remap=lambda o: o + 5_000_000_000)
        self.assertIn("32bit", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
