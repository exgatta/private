# -*- coding: utf-8 -*-
"""ボクセルモデル → Minecraft Education の Code Builder / コマンド用コード出力。

2種類を出力する:
  1. MakeCode Python  … Code Builder (ゲーム内で C キー) に貼り付けて
     チャットで「build」と打つと、プレイヤーの位置を基準に自動で建つ
  2. /fill・/setblock コマンド集 … チャットに1行ずつ貼っても建てられる

どちらもプレイヤー相対座標 (~) を使う。x=東, y=上, z=南 方向に伸びる。
"""

_DIR_JA = {"north": "北", "south": "南", "east": "東", "west": "西",
           "down": "下", "up": "上"}

from .blockstate import command_suffix
from .palette import block


def _runs(model):
    """同じ (y, z) の列で x 方向に連続する同種ブロックをまとめる。

    戻り値: (key, x1, y, z, x2, facing) のリスト。marker(置き物)は別で返す。
    向きが違うものはまとめない。まとめてしまうと1つのコマンドに
    なってしまい、向きがそろわなくなる。
    """
    runs, markers = [], []
    by_row = {}
    for (x, y, z), key in model.blocks.items():
        facing = model.facing.get((x, y, z))
        if block(key).get("marker"):
            markers.append((key, x, y, z, facing))
        else:
            by_row.setdefault((y, z), []).append((x, key, facing))
    for (y, z), cells in sorted(by_row.items()):
        cells.sort(key=lambda c: c[0])
        start_x = prev_x = prev_key = prev_f = None
        for x, key, facing in cells:
            if prev_key == key and prev_f == facing and x == prev_x + 1:
                prev_x = x
                continue
            if prev_key is not None:
                runs.append((prev_key, start_x, y, z, prev_x, prev_f))
            start_x, prev_x, prev_key, prev_f = x, x, key, facing
        if prev_key is not None:
            runs.append((prev_key, start_x, y, z, prev_x, prev_f))
    return runs, sorted(markers, key=lambda m: (m[3], m[2], m[1]))


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
        "# ブロック定数は実機のCode Builder（Education 1.21.133）で検証済み。",
        "# ランタンと石レンガのハーフはMakeCodeに無いため近い見た目で代用される。",
        "#       正確に建てたい場合は commands.txt を使う（正しいIDで置かれる）。",
        "",
        "def build():",
    ]
    for key, x1, y, z, x2, facing in runs:
        mc = block(key)["makecode"]
        if x1 == x2:
            lines.append(f"    blocks.place({mc}, pos({x1}, {y}, {z}))")
        else:
            lines.append(
                f"    blocks.fill({mc}, pos({x1}, {y}, {z}), pos({x2}, {y}, {z}))"
            )
    if markers:
        lines.append("    # ▼ 置き物（たいまつ・ドア・ホッパー等）は向きが命なので手で置く")
        for key, x, y, z, facing in markers:
            d = f"（{_DIR_JA[facing]}向き）" if facing else ""
            lines.append(
                f"    #   {block(key)['name_ja']}{d} → 図の位置 x={x}, {y + 1}段目, z={z}"
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
        "# ブロック名は Mojang 公式のブロック定義と照合済み。",
        "# 向きはデータ値方式（ブロック名の後ろの数字）。Minecraft Education の",
        "# コマンドはブロック状態構文 [\"~\"=n] を受け付けないため（実機確認）。",
        "# 建てたい場所に立って、動かずに順番に実行する（~はプレイヤー相対座標）",
        "",
    ]
    for key, x1, y, z, x2, facing in runs:
        bid = block(key)["bedrock_id"]
        st = command_suffix(key, facing)
        if x1 == x2:
            lines.append(f"/setblock ~{x1} ~{y} ~{z} {bid}{st}")
        else:
            lines.append(f"/fill ~{x1} ~{y} ~{z} ~{x2} ~{y} ~{z} {bid}{st}")
    if markers:
        lines.append("")
        lines.append("# ▼ 置き物は最後に。向きはデータ値で入れてある")
        for key, x, y, z, facing in markers:
            st = command_suffix(key, facing)
            d = f"   # {_DIR_JA[facing]}向き" if facing else ""
            lines.append(
                f"/setblock ~{x} ~{y} ~{z} {block(key)['bedrock_id']}{st}{d}"
            )
            if key == "door":
                # ドアは上下2マスで1つ。下半分だけ setblock すると壊れたドアになる。
                # データ値8 = 上半分（upper_block_bit）。
                lines.append(
                    f"/setblock ~{x} ~{y + 1} ~{z} {block(key)['bedrock_id']} 8"
                    "   # ドアの上半分（セットで置く）"
                )
    return "\n".join(lines) + "\n"
