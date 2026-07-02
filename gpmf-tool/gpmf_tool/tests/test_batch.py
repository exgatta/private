"""一括処理 (batch) のテスト。"""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from gpmf_tool import mp4
from gpmf_tool.__main__ import (collect_videos, _default_output, inject_file,
                                main)
from gpmf_tool.tests.test_mp4_inject import build_synthetic_mp4


class TestBatch(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for i, (mf, dur) in enumerate([(True, 3), (False, 4), (True, 2)]):
            with open(os.path.join(self.dir, f"clip{i}.mp4"), "wb") as f:
                f.write(build_synthetic_mp4(moov_first=mf, duration_sec=dur))
        # 動画でないファイルと、出力物っぽい名前のファイル
        with open(os.path.join(self.dir, "readme.txt"), "w") as f:
            f.write("x")
        with open(os.path.join(self.dir, "old_gopro.mp4"), "wb") as f:
            f.write(build_synthetic_mp4(moov_first=True, duration_sec=1))

    def test_collect_videos_filters(self):
        found = collect_videos([self.dir])
        names = sorted(os.path.basename(p) for p in found)
        # .txt と *_gopro.mp4 は除外され、clip0..2 の 3 本
        self.assertEqual(names, ["clip0.mp4", "clip1.mp4", "clip2.mp4"])

    def test_default_output_naming(self):
        out = _default_output("/a/b/movie.mp4", "/out")
        self.assertEqual(out, os.path.join("/out", "movie_gopro.mp4"))
        out2 = _default_output("/a/b/movie.MOV", None)
        self.assertEqual(out2, os.path.join("/a/b", "movie_gopro.MOV"))

    def test_batch_processes_all(self):
        out_dir = os.path.join(self.dir, "out")
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["batch", self.dir, "-o", out_dir, "--device", "hero11"])
        log = buf.getvalue()
        self.assertIn("成功 3", log)
        for i in range(3):
            p = os.path.join(out_dir, f"clip{i}_gopro.mp4")
            self.assertTrue(os.path.isfile(p))
            with open(p, "rb") as f:
                self.assertIsNotNone(mp4.find_gpmd_trak(
                    mp4.parse_box_tree(
                        mp4.read_box_bytes(
                            f, next(b for b in mp4.scan_top_level(f)
                                    if b.type == b"moov")), b"moov")))

    def test_batch_skips_existing(self):
        out_dir = os.path.join(self.dir, "out2")
        main(["batch", self.dir, "-o", out_dir, "--device", "hero9"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["batch", self.dir, "-o", out_dir, "--device", "hero9"])
        self.assertIn("スキップ 3", buf.getvalue())

    def test_gpx_cache_reused(self):
        # 同じ GPX を 2 ファイルに使うとき load は 1 回で済む
        calls = {"n": 0}
        import gpmf_tool.telemetry as tel
        orig = tel.load_gpx

        def counting_load(path):
            calls["n"] += 1
            return orig(path)

        tel.load_gpx = counting_load
        try:
            import gpmf_tool.__main__ as m
            # __main__ は telemetry を参照するので同じ関数が使われる
            gpx = os.path.join(self.dir, "t.gpx")
            with open(gpx, "w") as f:
                f.write('<?xml version="1.0"?><gpx version="1.1" '
                        'xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
                        '<trkpt lat="35.0" lon="139.0"><ele>1</ele>'
                        '<time>2024-01-01T00:00:00Z</time></trkpt>'
                        '<trkpt lat="35.01" lon="139.0"><ele>2</ele>'
                        '<time>2024-01-01T00:00:10Z</time></trkpt>'
                        '</trkseg></trk></gpx>')
            out_dir = os.path.join(self.dir, "out3")
            m.main(["batch", self.dir, "-o", out_dir, "--gpx", gpx,
                    "--device", "hero11"])
            self.assertEqual(calls["n"], 1, "GPX が使い回されていない")
        finally:
            tel.load_gpx = orig


if __name__ == "__main__":
    unittest.main()
