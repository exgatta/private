"""エラーメッセージ日本語化のテスト。"""

import errno
import io
import unittest
from contextlib import redirect_stderr

from gpmf_tool import klv, mp4
from gpmf_tool.__main__ import (humanize_error, main,
                                _translate_argparse,
                                _ARGPARSE_REPLACEMENTS)


class TestHumanizeError(unittest.TestCase):

    def test_enospc(self):
        e = OSError(errno.ENOSPC, "No space left on device", "/out.mp4")
        msg = humanize_error(e)
        self.assertIn("ディスクの空き容量", msg)
        self.assertIn("/out.mp4", msg)
        self.assertNotIn("No space", msg)

    def test_permission(self):
        e = PermissionError(errno.EACCES, "Permission denied", "/x")
        self.assertIn("アクセス権", humanize_error(e))

    def test_not_found(self):
        e = FileNotFoundError(errno.ENOENT, "No such file", "/missing")
        msg = humanize_error(e)
        self.assertIn("見つかりません", msg)
        self.assertIn("/missing", msg)

    def test_unknown_oserror_has_japanese_prefix(self):
        e = OSError(errno.EIO, "I/O error", "/dev/x")
        self.assertTrue(humanize_error(e).startswith("入出力エラー"))

    def test_gpmf_error_passthrough(self):
        self.assertEqual(humanize_error(klv.GPMFError("壊れた要素")), "壊れた要素")
        self.assertEqual(humanize_error(mp4.MP4Error("moov 無し")), "moov 無し")


class TestArgparseJapanese(unittest.TestCase):

    def _run_expect_exit(self, argv):
        buf = io.StringIO()
        with self.assertRaises(SystemExit) as cm, redirect_stderr(buf):
            main(argv)
        return cm.exception.code, buf.getvalue()

    def test_missing_command(self):
        code, err = self._run_expect_exit([])
        self.assertEqual(code, 2)
        self.assertIn("使い方:", err)
        self.assertIn("エラー:", err)
        self.assertNotIn("usage:", err)
        self.assertNotIn("the following arguments", err)

    def test_invalid_device_choice(self):
        code, err = self._run_expect_exit(
            ["inject", "x.mp4", "-o", "y.mp4", "--device", "zzz"])
        self.assertIn("不正な選択", err)
        self.assertIn("選択肢:", err)
        self.assertNotIn("invalid choice", err)

    def test_missing_required_output(self):
        code, err = self._run_expect_exit(["inject", "x.mp4"])
        self.assertIn("必須の引数", err)
        self.assertNotIn("required", err)

    def test_translation_no_leftover_english(self):
        sample = ("the following arguments are required: -o/--output; "
                  "argument --device: invalid choice: 'z' (choose from 'a')")
        out = _translate_argparse(sample, _ARGPARSE_REPLACEMENTS)
        for eng in ("the following", "invalid choice", "choose from",
                    "argument", "required"):
            self.assertNotIn(eng, out)


if __name__ == "__main__":
    unittest.main()
