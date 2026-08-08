#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""設計図ジェネレーター CLI。

使い方:
    python3 generate.py <設計名>       # 例: python3 generate.py house
    python3 generate.py --list         # 設計の一覧

出力先: samples/<設計名>/
    blueprint.html    … レゴ式レイヤー設計図（ブラウザで開く）
    makecode_build.py … Code Builder(MakeCode Python) 自動建築コード
    commands.txt      … /fill コマンド版
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from blueprint import render_html, export_makecode_python, export_commands
from designs import DESIGNS


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if args[0] == "--list":
        for name in DESIGNS:
            print(name)
        return 0

    name = args[0]
    if name not in DESIGNS:
        print(f"設計 '{name}' が見つかりません。--list で一覧を確認してください。")
        return 1

    model = DESIGNS[name]()
    out = Path(__file__).parent / "samples" / name
    out.mkdir(parents=True, exist_ok=True)

    (out / "blueprint.html").write_text(render_html(model), encoding="utf-8")
    (out / "makecode_build.py").write_text(
        export_makecode_python(model), encoding="utf-8"
    )
    (out / "commands.txt").write_text(export_commands(model), encoding="utf-8")

    sx, sy, sz = model.size()
    total = sum(n for _, n in model.counts())
    print(f"『{model.name}』の設計図を出力しました → {out}/")
    print(f"  サイズ: {sx}×{sz}マス・高さ{sy}段 / ブロック合計 {total} 個")
    return 0


if __name__ == "__main__":
    sys.exit(main())
