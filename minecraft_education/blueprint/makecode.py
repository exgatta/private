# -*- coding: utf-8 -*-
"""ボクセルモデル → Minecraft Education の Code Builder / コマンド用コード出力。

2種類を出力する:
  1. MakeCode Python  … Code Builder (ゲーム内で C キー) に貼り付けて
     チャットで「build」と打つと、プレイヤーの位置を基準に自動で建つ
  2. /fill・/setblock コマンド集 … チャットに1行ずつ貼っても建てられる

どちらもプレイヤー相対座標 (~) を使う。x=東, y=上, z=南 方向に伸びる。
"""

from .palette import block


def _runs(model):
    """同じ (y, z) の列で x 方向に連続する同種ブロックをまとめる。
    戻り値: (key, x1, y, z, x2) のリスト。marker(置き物)は除外して別で返す。
    """
    runs, markers = [], []
    by_row = {}
    for (x, y, z), key in model.blocks.items():
        if block(key).get("marker"):
            markers.append((key, x, y, z))
        else:
            by_row.setdefault((y, z), []).append((x, key))
    for (y, z), cells in sorted(by_row.items()):
        cells.sort()
        start_x, prev_x, prev_key = None, None, None
        for x, key in cells:
            if prev_key == key and x == prev_x + 1:
                prev_x = x
                continue
            if prev_key is not None:
                runs.append((prev_key, start_x, y, z, prev_x))
            start_x, prev_x, prev_key = x, x, key
        if prev_key is not None:
            runs.append((prev_key, start_x, y, z, prev_x))
    return runs, sorted(markers)


def export_makecode_python(model):
    model.normalize()
    runs, markers = _runs(model)
    lines = [
        "# " + model.name + " — 自動建築コード (MakeCode Python)",
        "# 使い方:",
        "#  1. Minecraft Education で C キー → Code Builder → MakeCode (Python)",
        "#  2. このコードを貼り付けて実行ボタンを押す",
        "#  3. 建てたい場所に立って、チャットで build と入力（建築中は動かない！）",
        "# 建物はプレイヤーの足元を基準に、東(x+)・南(z+)方向に建ちます。",
        "",
        "def build():",
    ]
    for key, x1, y, z, x2 in runs:
        mc = block(key)["makecode"]
        if x1 == x2:
            lines.append(f"    blocks.place({mc}, pos({x1}, {y}, {z}))")
        else:
            lines.append(
                f"    blocks.fill({mc}, pos({x1}, {y}, {z}), pos({x2}, {y}, {z}))"
            )
    if markers:
        lines.append("    # ▼ 置き物（たいまつ・ドア等）は自動設置が不安定なので手で置くのがおすすめ")
        for key, x, y, z in markers:
            lines.append(
                f"    #   {block(key)['name_ja']} → 図の位置 x={x}, {y + 1}段目, z={z}"
            )
    lines += [
        "",
        'player.on_chat("build", build)',
        "",
    ]
    return "\n".join(lines)


def export_commands(model):
    model.normalize()
    runs, markers = _runs(model)
    lines = [
        f"# {model.name} — チャットコマンド版（1行ずつチャットに貼り付け）",
        "# 建てたい場所に立って、動かずに順番に実行する（~はプレイヤー相対座標）",
        "",
    ]
    for key, x1, y, z, x2 in runs:
        bid = block(key)["bedrock_id"]
        if x1 == x2:
            lines.append(f"/setblock ~{x1} ~{y} ~{z} {bid}")
        else:
            lines.append(f"/fill ~{x1} ~{y} ~{z} ~{x2} ~{y} ~{z} {bid}")
    if markers:
        lines.append("")
        lines.append("# ▼ 置き物は最後に（向きの調整は手動が確実）")
        for key, x, y, z in markers:
            lines.append(f"/setblock ~{x} ~{y} ~{z} {block(key)['bedrock_id']}")
    return "\n".join(lines) + "\n"
