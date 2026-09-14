"""分割動画の結合 (再エンコードなし) のテスト。

DJI / Insta360 が自動分割したファイルを 1 本にまとめる機能を検証する。
各サンプルに固有のデータを入れ、結合後も **順序とデータが完全に一致** する
ことを確認するのが要。
"""

import io
import os
import struct
import tempfile
import unittest

from gpmf_tool import concat, mp4
from gpmf_tool.mp4 import _box, _full
from gpmf_tool.tests.test_mp4_inject import _MATRIX


def _sample_bytes(tag: str, i: int) -> bytes:
    """サンプルごとに異なる中身 (後で順序を検証するため)。"""
    return f"<{tag}-{i:04d}>".encode().ljust(16, b".")


def build_multi_sample_mp4(tag: str, n_video: int, n_audio: int = 0,
                           timescale: int = 600, frame_dur: int = 20,
                           keyframe_every: int = 3,
                           samples_per_chunk: int = 2) -> bytes:
    """複数サンプル・複数トラックの MP4 を合成する。

    tag はサンプルデータに埋め込まれ、どのファイル由来か判別できる。
    """
    vid_samples = [_sample_bytes(f"{tag}V", i) for i in range(n_video)]
    aud_samples = [_sample_bytes(f"{tag}A", i) for i in range(n_audio)]

    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2avc1")
    blob = b"".join(vid_samples) + b"".join(aud_samples)
    mdat = _box(b"mdat", blob)
    mdat_data = len(ftyp) + 8           # mdat 中身の開始位置
    aud_start = mdat_data + sum(len(s) for s in vid_samples)

    duration = n_video * frame_dur

    def chunks_for(samples, start_off, per_chunk):
        """(チャンク先頭オフセット列, stsc) を作る。"""
        offs, i = [], 0
        pos = start_off
        while i < len(samples):
            offs.append(pos)
            grp = samples[i:i + per_chunk]
            pos += sum(len(s) for s in grp)
            i += per_chunk
        return offs

    def make_trak(track_id, handler, samples, start_off, per_chunk,
                  dur_per_sample, with_stss, width=0, height=0):
        offs = chunks_for(samples, start_off, per_chunk)
        total = len(samples) * dur_per_sample
        tkhd = _full(b"tkhd", 0, 3,
                     struct.pack(">IIIII", 0, 0, track_id, 0, total)
                     + b"\x00" * 8 + struct.pack(">hhhh", 0, 0, 0, 0)
                     + _MATRIX + struct.pack(">II", width << 16, height << 16))
        mdhd = _full(b"mdhd", 0, 0,
                     struct.pack(">IIII", 0, 0, timescale, total)
                     + struct.pack(">Hh", 0x55C4, 0))
        hname = b"VideoHandler\x00" if handler == b"vide" else b"SoundHandler\x00"
        hdlr = _full(b"hdlr", 0, 0, b"\x00" * 4 + handler + b"\x00" * 12 + hname)
        codec = b"avc1" if handler == b"vide" else b"mp4a"
        entry = (b"\x00" * 6 + struct.pack(">H", 1) + b"\x00" * 16
                 + struct.pack(">HH", width, height) + b"\x00" * 50)
        stsd = _full(b"stsd", 0, 0, struct.pack(">I", 1) + _box(codec, entry))
        stts = _full(b"stts", 0, 0, struct.pack(">I", 1)
                     + struct.pack(">II", len(samples), dur_per_sample))
        stsc = _full(b"stsc", 0, 0, struct.pack(">I", 1)
                     + struct.pack(">III", 1, per_chunk, 1))
        stsz = _full(b"stsz", 0, 0, struct.pack(">II", 0, len(samples))
                     + b"".join(struct.pack(">I", len(s)) for s in samples))
        stco = _full(b"stco", 0, 0, struct.pack(">I", len(offs))
                     + b"".join(struct.pack(">I", o) for o in offs))
        tables = stsd + stts + stsc + stsz + stco
        if with_stss:
            keys = [i + 1 for i in range(len(samples))
                    if i % keyframe_every == 0]
            tables += _full(b"stss", 0, 0, struct.pack(">I", len(keys))
                            + b"".join(struct.pack(">I", k) for k in keys))
        stbl = _box(b"stbl", tables)
        vmhd = _full(b"vmhd", 0, 1, b"\x00" * 8)
        minf = _box(b"minf", vmhd + stbl)
        return _box(b"trak", tkhd + _box(b"mdia", mdhd + hdlr + minf))

    mvhd = _full(b"mvhd", 0, 0,
                 struct.pack(">IIII", 0, 0, timescale, duration)
                 + struct.pack(">iH", 0x00010000, 0x0100) + b"\x00" * 10
                 + _MATRIX + b"\x00" * 24 + struct.pack(">I", 3))
    traks = make_trak(1, b"vide", vid_samples, mdat_data, samples_per_chunk,
                      frame_dur, True, 1920, 1080)
    if n_audio:
        traks += make_trak(2, b"soun", aud_samples, aud_start, 1,
                           frame_dur, False)
    moov = _box(b"moov", mvhd + traks)
    return ftyp + mdat + moov


def _read_samples(path, track_index=0):
    """結合後ファイルから、指定トラックの全サンプルデータを順に読む。"""
    with open(path, "rb") as f:
        tops = mp4.scan_top_level(f)
        moov = mp4.parse_box_tree(
            mp4.read_box_bytes(f, next(b for b in tops if b.type == b"moov")),
            b"moov")
        trak = list(moov.find_all(b"trak"))[track_index]
        stbl = trak.find(b"mdia", b"minf", b"stbl")
        sizes = mp4.parse_stsz(stbl.find(b"stsz").payload)
        stsc = mp4.parse_stsc(stbl.find(b"stsc").payload)
        stco_box = stbl.find(b"stco")
        if stco_box is not None:
            offs = mp4.parse_stco(stco_box.payload, False)
        else:
            offs = mp4.parse_stco(stbl.find(b"co64").payload, True)
        out = []
        for off, size in mp4.sample_offsets(sizes, stsc, offs):
            f.seek(off)
            out.append(f.read(size))
        return out


class TestConcat(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _write(self, name, data):
        p = os.path.join(self.dir, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_sample_order_and_data_preserved(self):
        """核心: 結合後もサンプルの順序と中身が完全一致する。"""
        a = self._write("a.mp4", build_multi_sample_mp4("A", 7))
        b = self._write("b.mp4", build_multi_sample_mp4("B", 5))
        c = self._write("c.mp4", build_multi_sample_mp4("C", 4))
        out = os.path.join(self.dir, "joined.mp4")
        concat.concat_files([a, b, c], out)

        got = _read_samples(out)
        expect = ([_sample_bytes("AV", i) for i in range(7)]
                  + [_sample_bytes("BV", i) for i in range(5)]
                  + [_sample_bytes("CV", i) for i in range(4)])
        self.assertEqual(got, expect)

    def test_duration_is_sum(self):
        a = self._write("a.mp4", build_multi_sample_mp4("A", 10))
        b = self._write("b.mp4", build_multi_sample_mp4("B", 20))
        out = os.path.join(self.dir, "j.mp4")
        stats = concat.concat_files([a, b], out)
        # 30 サンプル x 20/600 秒 = 1.0 秒
        self.assertAlmostEqual(stats["duration_sec"], 30 * 20 / 600, places=3)
        with open(out, "rb") as f:
            self.assertAlmostEqual(mp4.movie_duration_seconds(f),
                                   30 * 20 / 600, places=3)

    def test_audio_track_also_merged(self):
        a = self._write("a.mp4", build_multi_sample_mp4("A", 6, n_audio=6))
        b = self._write("b.mp4", build_multi_sample_mp4("B", 6, n_audio=6))
        out = os.path.join(self.dir, "j.mp4")
        concat.concat_files([a, b], out)

        video = _read_samples(out, 0)
        audio = _read_samples(out, 1)
        self.assertEqual(video, [_sample_bytes("AV", i) for i in range(6)]
                         + [_sample_bytes("BV", i) for i in range(6)])
        self.assertEqual(audio, [_sample_bytes("AA", i) for i in range(6)]
                         + [_sample_bytes("BA", i) for i in range(6)])

    def test_keyframes_renumbered(self):
        """キーフレーム番号が2本目以降でずれて記録される。"""
        a = self._write("a.mp4", build_multi_sample_mp4("A", 6))
        b = self._write("b.mp4", build_multi_sample_mp4("B", 6))
        out = os.path.join(self.dir, "j.mp4")
        concat.concat_files([a, b], out)
        with open(out, "rb") as f:
            tops = mp4.scan_top_level(f)
            moov = mp4.parse_box_tree(
                mp4.read_box_bytes(f, next(b for b in tops if b.type == b"moov")),
                b"moov")
        stbl = next(moov.find_all(b"trak")).find(b"mdia", b"minf", b"stbl")
        keys = mp4.parse_stss(stbl.find(b"stss").payload)
        # 各ファイル 6 サンプルで 3 個おきキーフレーム → 1,4 と 7,10
        self.assertEqual(keys, [1, 4, 7, 10])

    def test_stts_merged(self):
        a = self._write("a.mp4", build_multi_sample_mp4("A", 5))
        b = self._write("b.mp4", build_multi_sample_mp4("B", 5))
        out = os.path.join(self.dir, "j.mp4")
        concat.concat_files([a, b], out)
        with open(out, "rb") as f:
            tops = mp4.scan_top_level(f)
            moov = mp4.parse_box_tree(
                mp4.read_box_bytes(f, next(b for b in tops if b.type == b"moov")),
                b"moov")
        stbl = next(moov.find_all(b"trak")).find(b"mdia", b"minf", b"stbl")
        stts = mp4.parse_stts(stbl.find(b"stts").payload)
        # 同じ delta なので 1 エントリにまとまる
        self.assertEqual(stts, [(10, 20)])

    def test_incompatible_codec_rejected(self):
        a = self._write("a.mp4", build_multi_sample_mp4("A", 4))
        # 解像度違い → stsd が異なる
        b = self._write("b.mp4", build_multi_sample_mp4("B", 4))
        # 解像度を変えた別ファイルを作る
        import re
        b2 = self._write("b2.mp4", build_multi_sample_mp4("B", 4))
        # build 関数は 1920x1080 固定なので、手動で stsd を変えたものを用意
        with open(b2, "rb") as bf:
            data = bytearray(bf.read())
        idx = data.find(b"avc1")
        # width(1920=0x0780) を 1280(0x0500) に書き換え
        pos = data.find(struct.pack(">HH", 1920, 1080), idx)
        data[pos:pos + 4] = struct.pack(">HH", 1280, 720)
        with open(b2, "wb") as f:
            f.write(bytes(data))
        out = os.path.join(self.dir, "j.mp4")
        with self.assertRaises(mp4.MP4Error) as cm:
            concat.concat_files([a, b2], out)
        self.assertIn("コーデック/解像度", str(cm.exception))

    def test_single_file_rejected(self):
        a = self._write("a.mp4", build_multi_sample_mp4("A", 3))
        with self.assertRaises(mp4.MP4Error):
            concat.concat_files([a], os.path.join(self.dir, "j.mp4"))

    def test_group_split_files(self):
        names = ["VID_001_0001.mp4", "VID_001_0002.mp4", "OTHER_0001.mp4"]
        paths = [os.path.join(self.dir, n) for n in names]
        groups = concat.group_split_files(paths)
        # 同系統のものがまとまる
        self.assertTrue(any(len(g) >= 2 for g in groups))


class TestSplitDetection(unittest.TestCase):
    """「1本の撮影が強制分割されたか」を撮影時刻の連続性で判定する。"""

    EPOCH = __import__("datetime").datetime(
        1904, 1, 1, tzinfo=__import__("datetime").timezone.utc)

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _make(self, name, shot, n_samples=30):
        data = bytearray(build_multi_sample_mp4("X", n_samples))
        ct = int((shot - self.EPOCH).total_seconds())
        i = data.find(b"mvhd")
        data[i + 8:i + 16] = struct.pack(">II", ct, ct)
        p = os.path.join(self.dir, name)
        with open(p, "wb") as f:
            f.write(bytes(data))
        return p

    def _base(self):
        import datetime
        return datetime.datetime(2025, 9, 15, 12, 0, 0,
                                 tzinfo=datetime.timezone.utc)

    def test_continuous_recording_grouped(self):
        """時刻が連続する = 強制分割 → 1グループ。"""
        import datetime
        base = self._base()
        # 各ファイルは 30サンプル x 20/600 = 1.0 秒
        paths = [self._make(f"a{i}.mp4", base + datetime.timedelta(seconds=i))
                 for i in range(3)]
        groups = concat.detect_split_groups(paths)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 3)

    def test_separate_recordings_not_grouped(self):
        """時刻が離れている = 別撮影 → 別グループ。"""
        import datetime
        base = self._base()
        a = self._make("a.mp4", base)
        b = self._make("b.mp4", base + datetime.timedelta(minutes=30))
        groups = concat.detect_split_groups([a, b])
        self.assertEqual(len(groups), 2)

    def test_mixed_two_recordings(self):
        import datetime
        base = self._base()
        g1 = [self._make(f"x{i}.mp4", base + datetime.timedelta(seconds=i))
              for i in range(3)]
        g2 = [self._make(f"y{i}.mp4",
                         base + datetime.timedelta(minutes=30, seconds=i))
              for i in range(2)]
        groups = concat.detect_split_groups(g1 + g2)
        self.assertEqual(sorted(len(g) for g in groups), [2, 3])

    def test_different_resolution_never_grouped(self):
        """時刻が連続でも構成が違えば別グループ。"""
        import datetime
        base = self._base()
        a = self._make("a.mp4", base)
        b = self._make("b.mp4", base + datetime.timedelta(seconds=1))
        # b の解像度を変える
        with open(b, "rb") as f:
            data = bytearray(f.read())
        pos = data.find(struct.pack(">HH", 1920, 1080))
        data[pos:pos + 4] = struct.pack(">HH", 1280, 720)
        with open(b, "wb") as f:
            f.write(bytes(data))
        groups = concat.detect_split_groups([a, b])
        self.assertEqual(len(groups), 2)

    def test_single_file_is_own_group(self):
        a = self._make("solo.mp4", self._base())
        groups = concat.detect_split_groups([a])
        self.assertEqual(groups, [[a]])


class TestJoinWithGoPro(unittest.TestCase):
    """結合と同時に GoPro 化する (一時ファイルなし・1パス)。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _write(self, name, data):
        p = os.path.join(self.dir, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_join_and_goproify(self):
        from gpmf_tool import klv
        a = self._write("a.mp4", build_multi_sample_mp4("A", 8, n_audio=8))
        b = self._write("b.mp4", build_multi_sample_mp4("B", 8, n_audio=8))
        out = os.path.join(self.dir, "j.mp4")
        stats = concat.concat_files([a, b], out, gopro_device="max")

        self.assertEqual(stats["gopro"], "GoPro Max")
        # 映像・音声データは無傷
        self.assertEqual(_read_samples(out, 0),
                         [_sample_bytes("AV", i) for i in range(8)]
                         + [_sample_bytes("BV", i) for i in range(8)])
        self.assertEqual(_read_samples(out, 1),
                         [_sample_bytes("AA", i) for i in range(8)]
                         + [_sample_bytes("BA", i) for i in range(8)])
        # GPMF が付いている
        with open(out, "rb") as f:
            samples = mp4.extract_gpmf_samples(f)
            self.assertTrue(samples)
            items = klv.parse(samples[0].data)
            self.assertEqual(items[0].find_first("DVNM").value(), "GoPro Max")
            f.seek(0)
            tele = mp4.detect_telemetry(f)
            self.assertTrue(tele["gpmd"])
            for box in ("FIRM", "LENS", "CAME", "MUID", "GPMF"):
                self.assertIn(box, tele["gopro_udta"])

    def test_handler_renamed_to_gopro(self):
        a = self._write("a.mp4", build_multi_sample_mp4("A", 4, n_audio=4))
        b = self._write("b.mp4", build_multi_sample_mp4("B", 4, n_audio=4))
        out = os.path.join(self.dir, "j.mp4")
        concat.concat_files([a, b], out, gopro_device="hero11")
        with open(out, "rb") as f:
            tops = mp4.scan_top_level(f)
            moov = mp4.parse_box_tree(
                mp4.read_box_bytes(f, next(b_ for b_ in tops
                                           if b_.type == b"moov")), b"moov")
        names = [mp4.parse_hdlr(t.find(b"mdia", b"hdlr").payload)["name"]
                 for t in moov.find_all(b"trak")]
        self.assertIn("GoPro AVC", names)
        self.assertIn("GoPro AAC", names)

    def test_without_gopro_no_extra_track(self):
        a = self._write("a.mp4", build_multi_sample_mp4("A", 4))
        b = self._write("b.mp4", build_multi_sample_mp4("B", 4))
        out = os.path.join(self.dir, "j.mp4")
        stats = concat.concat_files([a, b], out)
        self.assertIsNone(stats["gopro"])
        with open(out, "rb") as f:
            self.assertFalse(mp4.detect_telemetry(f)["gpmd"])


if __name__ == "__main__":
    unittest.main()
