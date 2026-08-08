# -*- coding: utf-8 -*-
"""サンプル設計: 小さな木の家（9×7マス・高さ7段）。

設計コードの書き方の見本。新しい設計はこのファイルをコピーして作る。
座標: x=0..8(西→東), z=0..6(北→南), 玄関は南向き(z=6側)。
"""

from blueprint import VoxelModel


def build():
    m = VoxelModel(
        "ちいさな木の家",
        "オークの板材と丸石でつくる、はじめての家。玄関は南向きで、"
        "三角屋根はトウヒの板材。9×7マス・高さ7段。",
    )

    # 1段目: 丸石の床（土台）
    m.fill(0, 0, 0, 8, 0, 6, "cobblestone")

    # 2〜4段目: 壁（オークの板材）と四隅の柱（オークの原木）
    for y in (1, 2, 3):
        m.hollow_box(0, y, 0, 8, y, 6, "oak_planks")
        for cx, cz in ((0, 0), (8, 0), (0, 6), (8, 6)):
            m.set(cx, y, cz, "oak_log")

    # 玄関（南面の中央）: 2マス分あけてドアを置く
    m.set(4, 1, 6, "door")
    m.set(4, 2, 6, None)  # ドアの上半分ぶんの空間

    # 窓（3段目の高さ）: 南面2つ・北面3つ・東西1つずつ
    for x in (2, 6):
        m.set(x, 2, 6, "glass")
    for x in (2, 4, 6):
        m.set(x, 2, 0, "glass")
    m.set(0, 2, 3, "glass")
    m.set(8, 2, 3, "glass")

    # 部屋の中の明かり: 四隅の床にたいまつ
    for tx, tz in ((1, 1), (7, 1), (1, 5), (7, 5)):
        m.set(tx, 1, tz, "torch")

    # 5〜7段目: 三角屋根（トウヒの板材）。棟は東西方向。
    # 5段目: 南北の軒 + 妻壁（東西の三角部分はオークの板材）
    m.fill(0, 4, 0, 8, 4, 1, "spruce_planks")
    m.fill(0, 4, 5, 8, 4, 6, "spruce_planks")
    for gx in (0, 8):
        m.fill(gx, 4, 2, gx, 4, 4, "oak_planks")
    # 6段目
    m.fill(0, 5, 2, 8, 5, 2, "spruce_planks")
    m.fill(0, 5, 4, 8, 5, 4, "spruce_planks")
    for gx in (0, 8):
        m.set(gx, 5, 3, "oak_planks")
    # 7段目: 屋根のてっぺん（棟）
    m.fill(0, 6, 3, 8, 6, 3, "spruce_planks")

    return m
