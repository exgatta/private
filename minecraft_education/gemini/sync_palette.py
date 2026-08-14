#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""blueprint/palette.py の BLOCKS を renderer.js へ書き写す。

パレットは Python版とJS版の両方に必要だが、手で二重管理するとズレる。
ズレると「Geminiが提案したブロックが設計図で未定義になる」「色が食い違う」等の
静かな品質劣化になるため、Python版を正本として機械的に転記する。

    python3 sync_palette.py        # renderer.js を書き換える
    python3 sync_palette.py --check # ズレていないか確認するだけ（CI用）
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

from blueprint.palette import BLOCKS  # noqa: E402

# JSに書き出す属性と順序（Python版の属性名をそのまま使う）
FIELDS = ("name_ja", "bedrock_id", "makecode", "color", "symbol",
          "transparent", "orientable", "shape", "marker", "piston", "redstone", "updown", "side_color")


def js_literal():
    lines = ["  var BLOCKS = {"]
    for key, b in BLOCKS.items():
        parts = []
        for f in FIELDS:
            if f not in b:
                continue
            v = b[f]
            parts.append(f"{f}: " + ("true" if v is True else json.dumps(v, ensure_ascii=False)))
        lines.append(f"    {key}: {{ " + ", ".join(parts) + " },")
    lines[-1] = lines[-1].rstrip(",")
    lines.append("  };")
    return "\n".join(lines)


def main():
    check = "--check" in sys.argv
    path = HERE / "renderer.js"
    src = path.read_text(encoding="utf-8")
    pat = re.compile(r"  var BLOCKS = \{.*?\n  \};", re.S)
    if not pat.search(src):
        raise SystemExit("renderer.js の BLOCKS が見つかりませんでした")
    new = pat.sub(lambda _: js_literal(), src, count=1)

    if check:
        if new != src:
            print("❌ renderer.js のパレットが palette.py とズレています。"
                  "python3 sync_palette.py を実行してください。")
            return 1
        print(f"✅ パレット一致（{len(BLOCKS)}種類）")
        return 0

    if new == src:
        print(f"変更なし（{len(BLOCKS)}種類）")
    else:
        path.write_text(new, encoding="utf-8")
        print(f"✅ renderer.js のパレットを更新しました（{len(BLOCKS)}種類）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
