#!/usr/bin/env python3
"""単体実行ファイル用エントリポイント。

PyInstaller はパッケージの `__main__.py` を直接ターゲットにできないため、
ここから CLI を呼び出す。GUI 版が必要な場合は ``--gui`` または引数なしで
起動するとファイル選択ダイアログ (Tkinter) を開く。
"""

import sys


def _run_gui() -> int:
    try:
        from gpmf_tool.gui import run
    except Exception as e:  # Tkinter 不在など
        print(f"GUI を起動できません: {e}", file=sys.stderr)
        print("CLI として使うには引数を付けて実行してください "
              "(例: gpmf inject in.mp4 -o out.mp4 --gpx ride.gpx)",
              file=sys.stderr)
        return 1
    return run()


def main() -> None:
    from gpmf_tool.__main__ import ensure_utf8_output
    ensure_utf8_output()
    args = sys.argv[1:]
    # 引数なし、または --gui のときは GUI を開く
    if not args or args == ["--gui"]:
        sys.exit(_run_gui())
    if args and args[0] == "gui":
        sys.exit(_run_gui())
    from gpmf_tool.__main__ import main as cli_main
    cli_main(args)


if __name__ == "__main__":
    main()
