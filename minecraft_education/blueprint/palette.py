# -*- coding: utf-8 -*-
"""ブロックパレット定義。

設計図で使えるブロックの一覧。キーは設計コードで使う短い名前。
- name_ja   : 設計図に表示する日本語名
- bedrock_id: /fill・/setblock コマンドで使うBedrock版ブロックID
- makecode  : Code Builder (MakeCode Python) のブロック定数名
- color     : 設計図・立体図で使う代表色 (hex)
- symbol    : レイヤー図のマスに表示する1文字記号
- marker    : True なら「置き物」(たいまつ・ドア等)。自動建築コードでは手動設置扱い
"""

BLOCKS = {
    "grass": {
        "name_ja": "草ブロック", "bedrock_id": "grass_block",
        "makecode": "GRASS", "color": "#6FA83C", "symbol": "草",
    },
    "dirt": {
        "name_ja": "土", "bedrock_id": "dirt",
        "makecode": "DIRT", "color": "#8A5A33", "symbol": "土",
    },
    "stone": {
        "name_ja": "石", "bedrock_id": "stone",
        "makecode": "STONE", "color": "#8F8F8F", "symbol": "石",
    },
    "cobblestone": {
        "name_ja": "丸石", "bedrock_id": "cobblestone",
        "makecode": "COBBLESTONE", "color": "#767B76", "symbol": "丸",
    },
    "stone_bricks": {
        "name_ja": "石レンガ", "bedrock_id": "stone_bricks",
        "makecode": "STONE_BRICKS", "color": "#A2A6A2", "symbol": "煉",
    },
    "oak_planks": {
        "name_ja": "オークの板材", "bedrock_id": "oak_planks",
        "makecode": "PLANKS_OAK", "color": "#BC9458", "symbol": "板",
    },
    "spruce_planks": {
        "name_ja": "トウヒの板材", "bedrock_id": "spruce_planks",
        "makecode": "PLANKS_SPRUCE", "color": "#7A5732", "symbol": "ト",
    },
    "oak_log": {
        "name_ja": "オークの原木", "bedrock_id": "oak_log",
        "makecode": "LOG_OAK", "color": "#66492A", "symbol": "原",
    },
    "glass": {
        "name_ja": "ガラス", "bedrock_id": "glass",
        "makecode": "GLASS", "color": "#C4E4EA", "symbol": "ガ",
    },
    "brick": {
        "name_ja": "レンガ", "bedrock_id": "brick_block",
        "makecode": "BRICK_BLOCK", "color": "#9E4F3B", "symbol": "赤",
    },
    "sandstone": {
        "name_ja": "砂岩", "bedrock_id": "sandstone",
        "makecode": "SANDSTONE", "color": "#DECFA0", "symbol": "砂",
    },
    "quartz": {
        "name_ja": "クォーツブロック", "bedrock_id": "quartz_block",
        "makecode": "QUARTZ_BLOCK", "color": "#EDE8E0", "symbol": "白",
    },
    "wool_white": {
        "name_ja": "白の羊毛", "bedrock_id": "white_wool",
        "makecode": "WHITE_WOOL", "color": "#F2F2F2", "symbol": "毛",
    },
    "wool_red": {
        "name_ja": "赤の羊毛", "bedrock_id": "red_wool",
        "makecode": "RED_WOOL", "color": "#C43B3B", "symbol": "紅",
    },
    "wool_blue": {
        "name_ja": "青の羊毛", "bedrock_id": "blue_wool",
        "makecode": "BLUE_WOOL", "color": "#3B58C4", "symbol": "青",
    },
    "glowstone": {
        "name_ja": "グロウストーン", "bedrock_id": "glowstone",
        "makecode": "GLOWSTONE", "color": "#F2D06B", "symbol": "光",
    },
    "mossy_stone_bricks": {
        "name_ja": "苔むした石レンガ", "bedrock_id": "mossy_stone_bricks",
        "makecode": "MOSSY_STONE_BRICKS", "color": "#7B8F6B", "symbol": "苔",
    },
    "chiseled_stone_bricks": {
        "name_ja": "模様入りの石レンガ", "bedrock_id": "chiseled_stone_bricks",
        "makecode": "CHISELED_STONE_BRICKS", "color": "#ABAFAB", "symbol": "彫",
    },
    "lava": {
        "name_ja": "溶岩", "bedrock_id": "lava",
        "makecode": "LAVA", "color": "#F26B1D", "symbol": "溶",
    },
    "tnt": {
        "name_ja": "TNT", "bedrock_id": "tnt",
        "makecode": "TNT", "color": "#D9472B", "symbol": "爆",
    },
    "redstone_block": {
        "name_ja": "レッドストーンブロック", "bedrock_id": "redstone_block",
        "makecode": "REDSTONE_BLOCK", "color": "#8E1616", "symbol": "動",
    },
    # ▼ レッドストーン部品は向き・取り付け面が重要なので marker（手動設置）扱い。
    #   設計側で m.notes に配置の向きと配線手順を必ず書くこと。
    "sticky_piston": {
        "name_ja": "粘着ピストン", "bedrock_id": "sticky_piston",
        "makecode": "STICKY_PISTON", "color": "#8AA05A", "symbol": "押", "marker": True,
    },
    "redstone_wire": {
        "name_ja": "レッドストーンダスト", "bedrock_id": "redstone_wire",
        "makecode": "REDSTONE_WIRE", "color": "#E03A2A", "symbol": "線", "marker": True,
    },
    "redstone_torch": {
        "name_ja": "レッドストーントーチ", "bedrock_id": "redstone_torch",
        "makecode": "REDSTONE_TORCH", "color": "#C22F1E", "symbol": "信", "marker": True,
    },
    "stone_pressure_plate": {
        "name_ja": "石の感圧板", "bedrock_id": "stone_pressure_plate",
        "makecode": "STONE_PRESSURE_PLATE", "color": "#B8B8B8", "symbol": "踏", "marker": True,
    },
    "lever": {
        "name_ja": "レバー", "bedrock_id": "lever",
        "makecode": "LEVER", "color": "#8B7355", "symbol": "柄", "marker": True,
    },
    "torch": {
        "name_ja": "たいまつ", "bedrock_id": "torch",
        "makecode": "TORCH", "color": "#F5A623", "symbol": "灯", "marker": True,
    },
    "door": {
        "name_ja": "オークのドア", "bedrock_id": "wooden_door",
        "makecode": "OAK_DOOR", "color": "#C98A3F", "symbol": "戸", "marker": True,
    },
}


def block(key):
    if key not in BLOCKS:
        raise KeyError(
            f"未定義のブロック '{key}'。palette.py の BLOCKS に追加してください。"
        )
    return BLOCKS[key]


def _clamp(v):
    return max(0, min(255, int(v)))


def shade(hex_color, factor):
    """立体図の面の陰影用。factor >1 で明るく、<1 で暗く。"""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % (_clamp(r * factor), _clamp(g * factor), _clamp(b * factor))
