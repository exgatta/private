"""内部メタデータ書き出し (metadump) のテスト。

映像・音声のデータは出さず、メーカー独自のデータトラックの先頭/末尾
サンプルと udta・stsd・elst が読める形で出ることを検証する。
"""

import os
import struct
import tempfile
import unittest

from gpmf_tool import metadump, mp4
from gpmf_tool.mp4 import _box, _full
from gpmf_tool.tests.test_concat import build_multi_sample_mp4
from gpmf_tool.tests.test_mp4_inject import _MATRIX


def _add_meta_track_and_udta(data: bytes, samples, udta_payload: bytes) -> bytes:
    """合成 MP4 に 'meta' ハンドラのデータトラックと udta を足す。

    データは mdat の末尾に追記し、moov を作り直す (オフセット補正込み)。
    """
    tops = []
    pos = 0
    while pos < len(data):
        size, typ = struct.unpack(">I4s", data[pos:pos + 8])
        tops.append((typ, pos, size))
        pos += size
    mdat = next(t for t in tops if t[0] == b"mdat")
    moov_t = next(t for t in tops if t[0] == b"moov")
    blob = b"".join(samples)
    # 新しい mdat = 旧 mdat 中身 + blob
    old_mdat_body = data[mdat[1] + 8:mdat[1] + mdat[2]]
    new_mdat = _box(b"mdat", old_mdat_body + blob)
    # 既存トラックのオフセットは mdat の位置が変わらなければそのまま
    assert mdat[1] + mdat[2] == moov_t[1], "mdat の直後に moov がある前提"
    meta_start = mdat[1] + 8 + len(old_mdat_body)
    offs = []
    p = meta_start
    for s in samples:
        offs.append(p)
        p += len(s)
    total = len(samples) * 100
    tkhd = _full(b"tkhd", 0, 3, struct.pack(">IIIII", 0, 0, 9, 0, total)
                 + b"\x00" * 8 + struct.pack(">hhhh", 0, 0, 0, 0)
                 + _MATRIX + struct.pack(">II", 0, 0))
    mdhd = _full(b"mdhd", 0, 0, struct.pack(">IIII", 0, 0, 1000, total)
                 + struct.pack(">Hh", 0x55C4, 0))
    hdlr = _full(b"hdlr", 0, 0, b"\x00" * 4 + b"meta" + b"\x00" * 12
                 + b"DJI meta\x00")
    stsd = _full(b"stsd", 0, 0, struct.pack(">I", 1)
                 + _box(b"djmd", b"\x00" * 6 + struct.pack(">H", 1)))
    stts = _full(b"stts", 0, 0, struct.pack(">I", 1)
                 + struct.pack(">II", len(samples), 100))
    stsc = _full(b"stsc", 0, 0, struct.pack(">I", 1) + struct.pack(">III", 1, 1, 1))
    stsz = _full(b"stsz", 0, 0, struct.pack(">II", 0, len(samples))
                 + b"".join(struct.pack(">I", len(s)) for s in samples))
    stco = _full(b"stco", 0, 0, struct.pack(">I", len(offs))
                 + b"".join(struct.pack(">I", o) for o in offs))
    stbl = _box(b"stbl", stsd + stts + stsc + stsz + stco)
    minf = _box(b"minf", _full(b"nmhd", 0, 0, b"") + stbl)
    elst = _full(b"elst", 0, 0, struct.pack(">I", 1)
                 + struct.pack(">Iii", total, 0, 0x00010000))
    trak = _box(b"trak", tkhd + _box(b"edts", elst)
                + _box(b"mdia", mdhd + hdlr + minf))
    moov_bytes = data[moov_t[1]:moov_t[1] + moov_t[2]]
    moov = mp4.parse_box_tree(moov_bytes, b"moov")
    moov.children.append(mp4.parse_box_tree(trak, b"trak"))
    moov.children.append(mp4.Box(b"udta", is_container=True, children=[
        mp4.Box(b"dji0", payload=udta_payload)]))
    return data[:mdat[1]] + new_mdat + moov.serialize()


class TestMetaDump(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _write(self, name, data):
        p = os.path.join(self.dir, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_dump_shows_meta_track_samples_but_not_media(self):
        samples = [b"FRAME%04d-secret-id-XYZ" % i for i in range(10)]
        data = _add_meta_track_and_udta(
            build_multi_sample_mp4("V", 6, n_audio=3), samples,
            b"DJI-Pocket-SN123456")
        p = self._write("DJI_20260914110954_0006_D.MP4", data)
        text = metadump.dump_file(p, n_samples=2)
        self.assertIn("##### DJI_20260914110954_0006_D.MP4", text)
        self.assertIn("ftyp: major=isom", text)
        self.assertIn('種類=meta 名前="DJI meta"', text)
        self.assertIn("stsd: エントリ djmd", text)
        self.assertIn("elst: (seg=1000 media=0 rate=1.0)", text)
        self.assertIn("udta:", text)
        self.assertIn("dji0 (19 バイト)", text)
        self.assertIn("DJI-Pocket-SN123", text)     # ASCII 欄 (16 バイト/行)
        # 先頭 2 サンプルと末尾 2 サンプル
        self.assertIn("[先頭] サンプル#1", text)
        self.assertIn("[先頭] サンプル#2", text)
        self.assertIn("[末尾] サンプル#9", text)
        self.assertIn("[末尾] サンプル#10", text)
        self.assertNotIn("サンプル#5", text)
        self.assertIn("FRAME0000-secret", text)
        self.assertIn("FRAME0009-secret", text)
        # 映像・音声の中身は出ない (サンプルデータのタグ "VV"/"VA" が無い)
        self.assertIn("映像/音声のためデータは出力しない", text)
        self.assertNotIn("VV0", text)
        self.assertNotIn("VA0", text)

    def test_dump_files_tolerates_broken(self):
        good = self._write("a.mp4", build_multi_sample_mp4("A", 3))
        bad = self._write("b.mp4", b"not an mp4" * 10)
        text = metadump.dump_files([good, bad])
        self.assertIn("== 内部メタデータ (2 ファイル) ==", text)
        self.assertIn("##### a.mp4", text)
        self.assertIn("##### b.mp4", text)
        self.assertIn("読めません", text)

    def test_hexdump_truncates(self):
        lines = metadump.hexdump(bytes(range(256)) * 2, max_bytes=32)
        self.assertEqual(len(lines), 3)
        self.assertIn("先頭 32 バイトのみ", lines[-1])


if __name__ == "__main__":
    unittest.main()
