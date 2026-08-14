#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""パレットの bedrock_id が実在するブロックかを Mojang 公式データで照合する。

    python3 tools/verify_block_ids.py            … 照合する
    python3 tools/verify_block_ids.py --update   … 参照データを取り直してから照合

なぜ必要か:
  Bedrock のブロック名は「新しい名前」に統一されていない。オーク系や回路部品は
  昔の名前のまま（オークのトラップドアは trapdoor、コンパレーターは
  unpowered_comparator など）。それらしい名前を推測して書くと必ず外れ、
  ゲーム内でコマンドが失敗する。しかも設計図の見た目は正常なので、
  実際にコマンドを打つまで誰も気づけない。
  そこで公式のブロック定義と機械的に突き合わせる。

参照データ: reference/bedrock_blocks.json
  出所 Mojang/bedrock-samples の metadata/vanilladata_modules/mojang-blocks.json
"""

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REF = ROOT / "reference" / "bedrock_blocks.json"
STATES = ROOT / "reference" / "bedrock_block_states.json"
URL = ("https://raw.githubusercontent.com/Mojang/bedrock-samples/main/"
       "metadata/vanilladata_modules/mojang-blocks.json")


def update():
    print(f"取得中: {URL}")
    with urllib.request.urlopen(URL, timeout=60) as r:
        data = json.loads(r.read().decode("utf-8"))
    names = sorted(it["name"].split(":", 1)[1] for it in data["data_items"])
    REF.parent.mkdir(exist_ok=True)
    REF.write_text(
        json.dumps({"source": URL, "count": len(names), "blocks": names},
                   ensure_ascii=False, indent=0),
        encoding="utf-8",
    )
    st = {it["name"].split(":", 1)[1]: sorted(p["name"] for p in it.get("properties", []))
          for it in data["data_items"]}
    STATES.write_text(
        json.dumps({"source": URL, "states": st}, ensure_ascii=False, indent=0),
        encoding="utf-8",
    )
    print(f"保存しました: {REF}（{len(names)}件）と {STATES}")


def verify():
    from blueprint.palette import BLOCKS

    ref = json.loads(REF.read_text(encoding="utf-8"))
    valid = set(ref["blocks"])
    bad = []
    for key, b in BLOCKS.items():
        if b["bedrock_id"] not in valid:
            near = sorted(
                v for v in valid
                if b["bedrock_id"].split("_")[-1] in v
            )[:5]
            bad.append((key, b["bedrock_id"], near))

    # 向きの状態プロパティも照合する。名前が違うと /setblock がエラーになり、
    # しかも設計図は正常に見えるので、実際に打つまで気づけない。
    from blueprint.blockstate import STATE_RULES

    states = json.loads(STATES.read_text(encoding="utf-8"))["states"]
    for key, (prop, _fn) in STATE_RULES.items():
        if key not in BLOCKS:
            bad.append((key, f"(STATE_RULES にあるが palette に無い)", []))
            continue
        bid = BLOCKS[key]["bedrock_id"]
        have = states.get(bid, [])
        if prop not in have:
            bad.append((key, f"状態 '{prop}' は {bid} に存在しない", have))

    # 向き指定できることになっているのに、変換ルートが無いものも見つける
    for key, b in BLOCKS.items():
        if b.get("orientable") and key not in STATE_RULES:
            bad.append((key, "orientable なのに状態の書き方が未定義", []))

    if not bad:
        print(f"✅ パレット {len(BLOCKS)} 件すべて実在するブロックです"
              f"（参照 {ref['count']} 件）")
        print(f"✅ 向きの状態プロパティ {len(STATE_RULES)} 件も公式定義と一致")
        return 0

    print(f"❌ 実在しないブロックIDが {len(bad)} 件あります\n")
    for key, bid, near in bad:
        print(f"  {key}: '{bid}' は存在しません")
        print(f"    近い名前: {near}")
    print("\nreference/bedrock_blocks.json を見て正しい名前に直してください。")
    return 1


if __name__ == "__main__":
    if "--update" in sys.argv:
        update()
    sys.exit(verify())
