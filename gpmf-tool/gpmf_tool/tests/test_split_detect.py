"""メーカー別の命名規則を使った「強制分割」判定 (split_detect) のテスト。

合成 MP4 に撮影時刻 (mvhd creation_time) を書き込み、ファイル名だけを
各カメラの流儀にして判定結果を検証する。サイズの証拠は巨大ファイルを
作らずに済むよう _file_size を差し替える。
"""

import datetime
import os
import random
import struct
import tempfile
import unittest
from unittest import mock

from gpmf_tool import browse, concat, split_detect
from gpmf_tool.tests.test_concat import build_multi_sample_mp4

EPOCH = datetime.datetime(1904, 1, 1, tzinfo=datetime.timezone.utc)
BASE = datetime.datetime(2025, 9, 15, 12, 54, 2, tzinfo=datetime.timezone.utc)
GIB = 1 << 30


def set_creation_time(data: bytes, shot) -> bytes:
    """mvhd (version 0) の creation/modification time を shot にする。

    shot=None なら 0 (記録なし) にする。
    """
    data = bytearray(data)
    ct = 0 if shot is None else int((shot - EPOCH).total_seconds())
    i = data.find(b"mvhd")
    data[i + 8:i + 16] = struct.pack(">II", ct, ct)
    return bytes(data)


class _Base(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _make(self, name, shot=BASE, n_samples=30, width=None):
        """1.0 秒 (30 x 20/600) の合成動画を name で保存する。"""
        data = set_creation_time(build_multi_sample_mp4("X", n_samples), shot)
        if width is not None:
            data = bytearray(data)
            pos = data.find(struct.pack(">HH", 1920, 1080))
            data[pos:pos + 4] = struct.pack(">HH", width, 720)
            data = bytes(data)
        p = os.path.join(self.dir, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def _names(self, group):
        return [os.path.basename(p) for p in group.files]

    def _assert_partition(self, paths, groups):
        """全入力がちょうど 1 回ずつ現れる。"""
        flat = [p for g in groups for p in g.files]
        self.assertEqual(sorted(flat), sorted(paths))
        self.assertEqual(len(flat), len(set(flat)))


# ---------------------------------------------------------------------------
# GoPro
# ---------------------------------------------------------------------------

class TestGoPro(_Base):

    def test_chapters_merge_and_other_file_number_separate(self):
        # GoPro は全チャプターに同じ撮影時刻を書くことがある
        a = self._make("GH010001.MP4")
        b = self._make("GH020001.MP4")
        c = self._make("GH030001.MP4")
        d = self._make("GH010002.MP4")
        groups = split_detect.detect_groups([d, c, a, b])
        self._assert_partition([a, b, c, d], groups)
        merged = [g for g in groups if len(g.files) == 3][0]
        self.assertEqual(self._names(merged),
                         ["GH010001.MP4", "GH020001.MP4", "GH030001.MP4"])
        self.assertEqual(merged.vendor, "gopro")
        self.assertEqual(merged.confidence, "high")
        self.assertIn("チャプター 01→03", merged.reason)
        self.assertIn("0001", merged.reason)
        singles = [g for g in groups if len(g.files) == 1]
        self.assertEqual(self._names(singles[0]), ["GH010002.MP4"])

    def test_legacy_gopr_gp(self):
        a = self._make("GOPR0042.MP4")
        b = self._make("GP010042.MP4")
        c = self._make("GP020042.MP4")
        other = self._make("GOPR0043.MP4")
        groups = split_detect.detect_groups([c, other, b, a])
        merged = [g for g in groups if len(g.files) == 3][0]
        self.assertEqual(self._names(merged),
                         ["GOPR0042.MP4", "GP010042.MP4", "GP020042.MP4"])
        self.assertEqual(merged.confidence, "high")
        self.assertEqual(len(groups), 2)

    def test_chapter_gap_splits_run(self):
        a = self._make("GX010001.MP4")
        c = self._make("GX030001.MP4")
        groups = split_detect.detect_groups([a, c])
        self.assertEqual(len(groups), 2)

    def test_missing_first_chapter_is_medium(self):
        b = self._make("GX020001.MP4")
        c = self._make("GX030001.MP4")
        g = split_detect.detect_groups([b, c])[0]
        self.assertEqual(len(g.files), 2)
        self.assertEqual(g.confidence, "medium")
        self.assertIn("先頭チャプター", g.reason)

    def test_time_gap_contradiction_never_merges(self):
        a = self._make("GH010001.MP4", BASE)
        b = self._make("GH020001.MP4", BASE + datetime.timedelta(hours=3))
        groups = split_detect.detect_groups([a, b])
        self.assertEqual(len(groups), 2)

    def test_360_extension(self):
        a = self._make("GS010042.360")
        b = self._make("GS020042.360")
        g = split_detect.detect_groups([a, b])[0]
        self.assertEqual(len(g.files), 2)
        self.assertEqual(g.vendor, "gopro")


# ---------------------------------------------------------------------------
# DJI
# ---------------------------------------------------------------------------

class TestDJI(_Base):

    def test_new_naming_same_id_identical_time_merges(self):
        a = self._make("DJI_20260914145635_0011_D.MP4")
        b = self._make("DJI_20260914145635_0012_D.MP4")
        c = self._make("DJI_20260914145635_0013_D.MP4")
        groups = split_detect.detect_groups([c, a, b])
        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertEqual(self._names(g), ["DJI_20260914145635_0011_D.MP4",
                                          "DJI_20260914145635_0012_D.MP4",
                                          "DJI_20260914145635_0013_D.MP4"])
        self.assertEqual(g.vendor, "dji")
        self.assertEqual(g.confidence, "high")
        self.assertIn("20260914145635", g.reason)
        self.assertIn("0011→0013", g.reason)

    def test_osmo_pocket_per_segment_timestamps_merge(self):
        """Osmo Pocket / Action はセグメントごとに開始時刻を名前に書く。

        各ファイルは 1.0 秒なので、名前の時刻が 1 秒ずつ進む 3 本は
        強制分割された 1 本の撮影として結合されなければならない
        (旧実装は日時をIDとみなして全部単独にしていた)。
        """
        a = self._make("DJI_20260914145635_0011_D.MP4")
        b = self._make("DJI_20260914145636_0012_D.MP4")
        c = self._make("DJI_20260914145637_0013_D.MP4")
        groups = split_detect.detect_groups([c, a, b])
        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertEqual(self._names(g), ["DJI_20260914145635_0011_D.MP4",
                                          "DJI_20260914145636_0012_D.MP4",
                                          "DJI_20260914145637_0013_D.MP4"])
        self.assertEqual(g.confidence, "high")
        self.assertIn("時刻が連続", g.reason)

    def test_osmo_pocket_two_recordings_in_one_folder(self):
        """連番は続くが 30 分空く → 別撮影 2 組 (ユーザーの実フォルダ相当)。"""
        a = self._make("DJI_20260914145635_0011_D.MP4")
        b = self._make("DJI_20260914145636_0012_D.MP4")
        c = self._make("DJI_20260914152600_0013_D.MP4")
        d = self._make("DJI_20260914152601_0014_D.MP4")
        groups = split_detect.detect_groups([d, b, c, a])
        self.assertEqual(sorted(len(g.files) for g in groups), [2, 2])
        names = [self._names(g) for g in groups]
        self.assertIn(["DJI_20260914145635_0011_D.MP4",
                       "DJI_20260914145636_0012_D.MP4"], names)
        self.assertIn(["DJI_20260914152600_0013_D.MP4",
                       "DJI_20260914152601_0014_D.MP4"], names)

    def test_new_naming_stamp_tolerance_scales_with_duration(self):
        # 名前の時刻が長さから 5% 以内ずれていても続きとみなす
        # (1.0 秒のファイルなので許容は tol=120s が効く。ここでは gap=2s)
        a = self._make("DJI_20260914145635_0011_D.MP4")
        b = self._make("DJI_20260914145637_0012_D.MP4")
        self.assertEqual(len(split_detect.detect_groups([a, b])), 1)

    def test_new_naming_different_id_adjacent_not_merged(self):
        # 連番は続いているが撮影IDが違う → 別撮影 (旧実装はまとめていた)
        a = self._make("DJI_20260914145635_0011_D.MP4")
        b = self._make("DJI_20260914150000_0012_D.MP4")
        groups = split_detect.detect_groups([a, b])
        self.assertEqual(len(groups), 2)

    def test_new_naming_counter_gap_not_merged(self):
        a = self._make("DJI_20260914145635_0011_D.MP4")
        c = self._make("DJI_20260914145635_0013_D.MP4")
        self.assertEqual(len(split_detect.detect_groups([a, c])), 2)

    def test_new_naming_zero_creation_time_still_merges(self):
        a = self._make("DJI_20260914145635_0011_D.MP4", shot=None)
        b = self._make("DJI_20260914145635_0012_D.MP4", shot=None)
        g = split_detect.detect_groups([b, a])[0]
        self.assertEqual(len(g.files), 2)
        self.assertEqual(g.confidence, "high")

    def test_osmo_pocket_next_stamp_inside_previous_duration_merges(self):
        """次のファイル名の時刻が「前の開始 + 前の長さ」より手前でも続き。

        同じカメラで前の撮影が終わる前に別の撮影は始められないので、
        前の動画の範囲内に次の時刻があれば強制分割の続きと判断する
        (長さの記録が実際より長い機種でも取りこぼさない)。
        """
        # 各 300 秒。0012 は 0011 の 85 秒後 (範囲内)、0013 は 0012 の
        # 終わり (14:58:00 + 5:00 = 15:03:00) + 許容 2 分より後 → 別撮影
        a = self._make("DJI_20260914145635_0011_D.MP4", n_samples=9000)
        b = self._make("DJI_20260914145800_0012_D.MP4", n_samples=9000)
        c = self._make("DJI_20260914151000_0013_D.MP4", n_samples=9000)
        groups = split_detect.detect_groups([c, b, a])
        self.assertEqual(sorted(len(g.files) for g in groups), [1, 2])
        merged = [g for g in groups if len(g.files) == 2][0]
        self.assertEqual(self._names(merged), ["DJI_20260914145635_0011_D.MP4",
                                               "DJI_20260914145800_0012_D.MP4"])
        self.assertEqual(merged.confidence, "high")

    def test_osmo_pocket_filename_wins_over_odd_internal_time(self):
        """ファイル名の時刻が続いていれば、動画内の撮影時刻が変でも続き。"""
        a = self._make("DJI_20260914145635_0011_D.MP4", BASE)
        b = self._make("DJI_20260914145636_0012_D.MP4",
                       BASE + datetime.timedelta(hours=5))
        g = split_detect.detect_groups([a, b])[0]
        self.assertEqual(len(g.files), 2)

    def test_reversed_filename_time_never_merges(self):
        a = self._make("DJI_20260914145635_0011_D.MP4")
        b = self._make("DJI_20260914120000_0012_D.MP4")
        self.assertEqual(len(split_detect.detect_groups([a, b])), 2)

    def test_zero_mvhd_duration_uses_track_duration(self):
        """mvhd の duration が 0 でもトラックの長さで判定できる。"""
        a = self._make("DJI_20260914145635_0011_D.MP4", n_samples=9000)
        b = self._make("DJI_20260914150135_0012_D.MP4", n_samples=9000)
        for p in (a, b):
            with open(p, "rb") as f:
                data = bytearray(f.read())
            i = data.find(b"mvhd")
            data[i + 20:i + 24] = b"\x00\x00\x00\x00"   # duration = 0
            with open(p, "wb") as f:
                f.write(data)
        g = split_detect.detect_groups([a, b])[0]
        self.assertEqual(len(g.files), 2, g.reason)
        text = split_detect.diagnose([a, b])
        self.assertIn("mvhd 0:00", text)
        self.assertIn("トラック 5:00", text)
        # 一覧の「長さ」もトラックの長さで埋まる ("-" にならない)
        entry = browse.analyze_file(a)
        self.assertEqual(entry.duration_text, "5:00")

    def test_single_reason_explains_neighbours_with_numbers(self):
        a = self._make("DJI_20260914145635_0011_D.MP4", n_samples=9000)
        b = self._make("DJI_20260914145800_0012_D.MP4", n_samples=9000)
        c = self._make("DJI_20260914151000_0013_D.MP4", n_samples=9000)
        d = self._make("DJI_20260914151000_0014_D.MP4", n_samples=9000,
                       width=1280)
        groups = split_detect.detect_groups([a, b, c, d])
        solo_c = [g for g in groups if g.files == [c]][0]
        self.assertIn("前の 0012 とは別撮影", solo_c.reason)
        self.assertIn("ファイル名の時刻差 12:00", solo_c.reason)
        self.assertIn("前の長さ 5:00", solo_c.reason)
        self.assertIn("許容 2:00", solo_c.reason)
        self.assertIn("次の 0014 とは別撮影", solo_c.reason)
        self.assertIn("コーデック/解像度が違う", solo_c.reason)
        text = split_detect.describe_groups(groups)
        self.assertIn("別撮影", text)
        # 結合されたグループ側にも「次の 0013 とは別撮影」の理由が付く
        # (単独の動画が非表示でも、見出しだけで理由が分かる)
        merged = [g for g in groups if len(g.files) == 2][0]
        self.assertIn("次の 0013 とは別撮影", merged.reason)
        self.assertIn("ファイル名の時刻差 12:00", merged.reason)

    def test_diagnose_report(self):
        a = self._make("DJI_20260914145635_0011_D.MP4")
        b = self._make("DJI_20260914145636_0012_D.MP4")
        c = self._make("DJI_20260914160000_0013_D.MP4")
        text = split_detect.diagnose([c, b, a])
        self.assertIn("== ファイル ==", text)
        self.assertIn("== 隣同士の判断", text)
        self.assertIn("== 判定結果 ==", text)
        self.assertIn("DJI_20260914145635_0011_D.MP4 → "
                      "DJI_20260914145636_0012_D.MP4: 続き (結合)", text)
        self.assertIn("DJI_20260914145636_0012_D.MP4 → "
                      "DJI_20260914160000_0013_D.MP4: 別撮影", text)
        self.assertIn("命名規則: dji 番号 0011 名前の時刻 2026/09/14 14:56:35",
                      text)
        self.assertIn("トラック 映像", text)

    def test_old_naming_needs_time_evidence(self):
        # 同じ時刻 (証拠なし) → 単独のまま
        a = self._make("DJI_0011.MP4")
        b = self._make("DJI_0012.MP4")
        self.assertEqual(len(split_detect.detect_groups([a, b])), 2)

        # 時刻が連続 → 結合
        c = self._make("DJI_0021.MP4", BASE)
        d = self._make("DJI_0022.MP4", BASE + datetime.timedelta(seconds=1))
        groups = split_detect.detect_groups([d, c])
        merged = [g for g in groups if len(g.files) == 2]
        self.assertEqual(len(merged), 1)
        self.assertEqual(self._names(merged[0]), ["DJI_0021.MP4", "DJI_0022.MP4"])
        self.assertEqual(merged[0].vendor, "dji")
        self.assertIn("撮影時刻が連続", merged[0].reason)


# ---------------------------------------------------------------------------
# Insta360
# ---------------------------------------------------------------------------

class TestInsta360(_Base):

    def test_same_datetime_key_merges(self):
        a = self._make("VID_20250915_125402_00_062.mp4")
        b = self._make("VID_20250915_125402_00_063.mp4")
        x = self._make("VID_20250915_130500_00_064.mp4")
        groups = split_detect.detect_groups([x, b, a])
        self._assert_partition([a, b, x], groups)
        merged = [g for g in groups if len(g.files) == 2][0]
        self.assertEqual(self._names(merged),
                         ["VID_20250915_125402_00_062.mp4",
                          "VID_20250915_125402_00_063.mp4"])
        self.assertEqual(merged.vendor, "insta360")
        self.assertEqual(merged.confidence, "high")
        self.assertIn("20250915_125402", merged.reason)
        self.assertEqual(len(groups), 2)

    def test_segment_index_and_trailing_number(self):
        a = self._make("VID_20250915_125402_00_062_134709.mp4")
        b = self._make("VID_20250915_125402_00_062_001.mp4")
        c = self._make("VID_20250915_125402_00_062_002.mp4")
        groups = split_detect.detect_groups([c, a, b])
        merged = [g for g in groups if len(g.files) == 3][0]
        self.assertEqual(self._names(merged),
                         ["VID_20250915_125402_00_062_134709.mp4",
                          "VID_20250915_125402_00_062_001.mp4",
                          "VID_20250915_125402_00_062_002.mp4"])

    def test_lrv_excluded(self):
        a = self._make("VID_20250915_125402_00_062.mp4")
        b = self._make("VID_20250915_125402_00_063.mp4")
        lrv = self._make("LRV_20250915_125402_00_062.mp4")
        groups = split_detect.detect_groups([a, lrv, b])
        self._assert_partition([a, b, lrv], groups)
        solo = [g for g in groups if g.files == [lrv]][0]
        self.assertEqual(solo.confidence, "low")
        self.assertIn("LRV", solo.reason)
        self.assertEqual(len([g for g in groups if len(g.files) == 2]), 1)


# ---------------------------------------------------------------------------
# Sony / 一般 / 時刻のみ
# ---------------------------------------------------------------------------

class TestSonyGenericTime(_Base):

    def test_sony_consecutive_but_time_gap_separate(self):
        a = self._make("C0001.MP4", BASE)
        b = self._make("C0002.MP4", BASE + datetime.timedelta(minutes=20))
        self.assertEqual(len(split_detect.detect_groups([a, b])), 2)

    def test_sony_consecutive_and_continuous_merge(self):
        a = self._make("C0001.MP4", BASE)
        b = self._make("C0002.MP4", BASE + datetime.timedelta(seconds=1))
        g = split_detect.detect_groups([b, a])[0]
        self.assertEqual(self._names(g), ["C0001.MP4", "C0002.MP4"])
        self.assertEqual(g.vendor, "sony")
        self.assertIn("C0001→C0002", g.reason)

    def test_generic_counter_with_size_evidence(self):
        # 撮影時刻は全ファイル同一 (時刻の証拠なし) だが、末尾以外が
        # 4GB 付近で揃っている → 分割の痕跡として結合
        names = ["clip_001.mp4", "clip_002.mp4", "clip_003.mp4"]
        paths = [self._make(n) for n in names]
        sizes = {paths[0]: 4 * GIB - 1000, paths[1]: 4 * GIB - 5000,
                 paths[2]: 700_000_000}
        with mock.patch.object(split_detect, "_file_size",
                               lambda p: sizes.get(p, 0)):
            groups = split_detect.detect_groups(list(reversed(paths)))
        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertEqual(self._names(g), names)
        self.assertEqual(g.vendor, "generic")
        self.assertEqual(g.confidence, "medium")
        self.assertIn("分割サイズが揃っている", g.reason)

    def test_generic_counter_without_evidence_stays_single(self):
        paths = [self._make(n) for n in ("clip_001.mp4", "clip_002.mp4")]
        self.assertEqual(len(split_detect.detect_groups(paths)), 2)

    def test_generic_counter_with_time_is_medium(self):
        paths = [self._make(f"a{i}.mp4", BASE + datetime.timedelta(seconds=i))
                 for i in range(3)]
        g = split_detect.detect_groups(paths)[0]
        self.assertEqual(len(g.files), 3)
        self.assertEqual(g.confidence, "medium")
        self.assertIn("撮影時刻が連続", g.reason)

    def test_unknown_naming_time_only_is_low(self):
        a = self._make("morning.mp4", BASE)
        b = self._make("beach.mp4", BASE + datetime.timedelta(seconds=1))
        groups = split_detect.detect_groups([b, a])
        self.assertEqual(len(groups), 1)
        self.assertEqual(self._names(groups[0]), ["morning.mp4", "beach.mp4"])
        self.assertEqual(groups[0].confidence, "low")
        self.assertIn("撮影時刻が連続", groups[0].reason)

    def test_tolerance_is_configurable(self):
        a = self._make("a0.mp4", BASE)
        b = self._make("a1.mp4", BASE + datetime.timedelta(seconds=61))
        self.assertEqual(len(split_detect.detect_groups([a, b])), 1)
        self.assertEqual(
            len(split_detect.detect_groups([a, b], tolerance_sec=30)), 2)


# ---------------------------------------------------------------------------
# 絶対条件・入出力の保証
# ---------------------------------------------------------------------------

class TestHardConstraints(_Base):

    def test_resolution_mismatch_never_merges(self):
        a = self._make("GH010001.MP4")
        b = self._make("GH020001.MP4", width=1280)
        self.assertEqual(len(split_detect.detect_groups([a, b])), 2)

    def test_unparsable_file_is_low_single(self):
        p = os.path.join(self.dir, "GH020001.MP4")
        with open(p, "wb") as f:
            f.write(b"not an mp4" * 20)
        a = self._make("GH010001.MP4")
        groups = split_detect.detect_groups([a, p])
        self._assert_partition([a, p], groups)
        broken = [g for g in groups if g.files == [p]][0]
        self.assertEqual(broken.confidence, "low")
        self.assertIn("読み取りに失敗", broken.reason)

    def test_appledouble_and_dotfiles_are_singles(self):
        a = self._make("GH010001.MP4")
        junk = os.path.join(self.dir, "._GH020001.MP4")
        with open(junk, "wb") as f:
            f.write(b"\x00\x05\x16\x07" * 8)
        groups = split_detect.detect_groups([junk, a])
        self._assert_partition([a, junk], groups)
        j = [g for g in groups if g.files == [junk]][0]
        self.assertIn("付随ファイル", j.reason)

    def test_every_input_once_with_shuffled_mixed_folder(self):
        paths = [
            self._make("GH010001.MP4"), self._make("GH020001.MP4"),
            self._make("DJI_20260914145635_0011_D.MP4"),
            self._make("DJI_20260914145635_0012_D.MP4"),
            self._make("DJI_20260914150000_0013_D.MP4"),
            self._make("C0001.MP4", BASE + datetime.timedelta(hours=1)),
            self._make("C0002.MP4", BASE + datetime.timedelta(hours=2)),
            self._make("solo.mp4", BASE + datetime.timedelta(hours=3)),
        ]
        rnd = random.Random(7)
        for _ in range(5):
            shuffled = list(paths)
            rnd.shuffle(shuffled)
            groups = split_detect.detect_groups(shuffled)
            self._assert_partition(paths, groups)
            self.assertEqual(sorted(len(g.files) for g in groups),
                             [1, 1, 1, 1, 2, 2])

    def test_groups_sorted_by_first_creation_time(self):
        late = self._make("C0009.MP4", BASE + datetime.timedelta(hours=5))
        early = self._make("GH010001.MP4", BASE)
        groups = split_detect.detect_groups([late, early])
        self.assertEqual(groups[0].files, [early])
        self.assertEqual(groups[1].files, [late])


# ---------------------------------------------------------------------------
# 表示・既存 API との接続
# ---------------------------------------------------------------------------

class TestDescribeAndWrappers(_Base):

    def test_describe_contains_reason(self):
        a = self._make("GH010001.MP4")
        b = self._make("GH020001.MP4")
        solo = self._make("GH010002.MP4")
        groups = split_detect.detect_groups([a, b, solo])
        text = split_detect.describe_groups(groups)
        self.assertIn("チャプター 01→02", text)
        self.assertIn("確度: 高", text)
        self.assertIn("GH010002.MP4", text)
        self.assertIn("単独", text)

    def test_concat_wrapper_returns_paths(self):
        a = self._make("GH010001.MP4")
        b = self._make("GH020001.MP4")
        groups = concat.detect_split_groups([b, a])
        self.assertEqual(groups, [[a, b]])
        # パスのリストのリストでも説明できる
        self.assertIn("分割された1本の撮影", concat.describe_groups(groups))

    def test_browse_group_gets_reason_confidence_vendor(self):
        self._make("DJI_20260914145635_0011_D.MP4")
        self._make("DJI_20260914145635_0012_D.MP4")
        self._make("DJI_20260914150000_0013_D.MP4")
        groups = browse.scan_folder([self.dir])
        split = [g for g in groups if g.is_split]
        self.assertEqual(len(split), 1)
        self.assertEqual(split[0].vendor, "dji")
        self.assertEqual(split[0].confidence, "high")
        self.assertIn("DJI 連番", split[0].reason)


if __name__ == "__main__":
    unittest.main()
