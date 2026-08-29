# -*- coding: utf-8 -*-
"""ブロックパレット定義。

設計図で使えるブロックの一覧。キーは設計コードで使う短い名前。
- name_ja   : 設計図に表示する日本語名
- bedrock_id: /fill・/setblock コマンドで使うBedrock版ブロックID
- makecode  : Code Builder (MakeCode Python) のブロック定数名
- color     : 設計図・立体図で使う代表色 (hex)
- symbol    : レイヤー図のマスに表示する1文字記号
- marker    : True なら「置き物」(たいまつ・ドア等)。自動建築コードでは手動設置扱い
- flammable : True なら溶岩・火で燃え移る素材（木材・羊毛・葉・TNT等）。
              検品が「溶岩のそば」を警告するのに使う。ドア・トラップドア・看板・
              はしご・作業台は木でも延焼しないため付けない

bedrock_id は Mojang 公式の Bedrock ブロック定義（Mojang/bedrock-samples の
mojang-blocks.json）と照合して確定させている。
Bedrock は「新しい名前」に統一されておらず、オーク系や回路部品は昔の名前のまま
（例: オークのトラップドアは trapdoor、コンパレーターは unpowered_comparator）。
推測で書くと必ず外れるので、ブロックを足したら
    python3 tools/verify_block_ids.py --update   （参照データを取り直す）
    python3 tools/verify_block_ids.py            （照合する）
を実行して確かめること。test_pack.py でも自動で照合している。
"""

BLOCKS = {
    "grass": {
        "name_ja": "草ブロック", "bedrock_id": "grass_block",
        "makecode": "GRASS", "color": "#6FA83C", "symbol": "草",
        "side_color": "#8A5A33",
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
        "flammable": True,
    },
    "spruce_planks": {
        "name_ja": "トウヒの板材", "bedrock_id": "spruce_planks",
        "makecode": "PLANKS_SPRUCE", "color": "#7A5732", "symbol": "ト",
        "flammable": True,
    },
    "oak_log": {
        "name_ja": "オークの原木", "bedrock_id": "oak_log",
        "makecode": "LOG_OAK", "color": "#B0895A", "symbol": "原",
        "side_color": "#66492A",
        "flammable": True,
    },
    "glass": {
        "name_ja": "ガラス", "bedrock_id": "glass",
        "makecode": "GLASS", "color": "#C4E4EA", "symbol": "ガ",
        "transparent": True,
    },
    "brick": {
        "name_ja": "レンガ", "bedrock_id": "brick_block",
        "makecode": "BRICKS", "color": "#9E4F3B", "symbol": "赤",
    },
    "sandstone": {
        "name_ja": "砂岩", "bedrock_id": "sandstone",
        "makecode": "SANDSTONE", "color": "#DECFA0", "symbol": "砂",
    },
    "quartz": {
        "name_ja": "クォーツブロック", "bedrock_id": "quartz_block",
        "makecode": "BLOCK_OF_QUARTZ", "color": "#EDE8E0", "symbol": "白",
    },
    "wool_white": {
        "name_ja": "白の羊毛", "bedrock_id": "white_wool",
        "makecode": "WOOL", "color": "#F2F2F2", "symbol": "毛",
        "flammable": True,
    },
    "wool_red": {
        "name_ja": "赤の羊毛", "bedrock_id": "red_wool",
        "makecode": "RED_WOOL", "color": "#C43B3B", "symbol": "紅",
        "flammable": True,
    },
    "wool_blue": {
        "name_ja": "青の羊毛", "bedrock_id": "blue_wool",
        "makecode": "BLUE_WOOL", "color": "#3B58C4", "symbol": "青",
        "flammable": True,
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
        "transparent": True,
    },
    "water": {
        "name_ja": "水", "bedrock_id": "water",
        "makecode": "WATER", "color": "#3E68C4", "symbol": "水",
        "transparent": True,
    },
    # ------------------------------------------------------------------
    # 装飾ブロック。マイクラの「細かさ」はここから生まれる。
    # 階段・ハーフ・フェンス等は立方体ではないので transparent 扱いにし、
    # 奥のブロックを隠さない（立体図で不自然に消えるのを防ぐ）。
    # ------------------------------------------------------------------
    "oak_stairs": {
        "name_ja": "オークの階段", "bedrock_id": "oak_stairs",
        "makecode": "OAK_STAIRS", "color": "#B08A50", "symbol": "階",
        "transparent": True, "orientable": True, "shape": "stairs",
        "flammable": True,
    },
    "stone_brick_stairs": {
        "name_ja": "石レンガの階段", "bedrock_id": "stone_brick_stairs",
        "makecode": "STONE_BRICK_STAIRS", "color": "#9A9E9A", "symbol": "段",
        "transparent": True, "orientable": True, "shape": "stairs",
    },
    "cobblestone_stairs": {
        "name_ja": "丸石の階段", "bedrock_id": "stone_stairs",
        "makecode": "COBBLESTONE_STAIRS", "color": "#6E736E", "symbol": "坂",
        "transparent": True, "orientable": True, "shape": "stairs",
    },
    "oak_slab": {
        "name_ja": "オークのハーフブロック", "bedrock_id": "oak_slab",
        "makecode": "OAK_SLAB", "color": "#C69C60", "symbol": "半",
        "transparent": True, "shape": "slab",
        "flammable": True,
    },
    "stone_brick_slab": {
        "name_ja": "石レンガのハーフブロック", "bedrock_id": "stone_brick_slab",
        "makecode": "STONE_BRICK_SLAB", "color": "#ACB0AC", "symbol": "平",
        "transparent": True, "shape": "slab",
    },
    "oak_fence": {
        "name_ja": "オークのフェンス", "bedrock_id": "oak_fence",
        "makecode": "OAK_FENCE", "color": "#A17C46", "symbol": "柵",
        "transparent": True, "shape": "thin",
        "flammable": True,
    },
    "oak_fence_gate": {
        "name_ja": "オークのフェンスゲート", "bedrock_id": "fence_gate",
        "makecode": "OAK_FENCE_GATE", "color": "#B98E4F", "symbol": "門",
        "transparent": True, "orientable": True, "shape": "thin", "marker": True,
        "flammable": True,
    },
    "oak_trapdoor": {
        "name_ja": "オークのトラップドア", "bedrock_id": "trapdoor",
        "makecode": "OAK_TRAPDOOR", "color": "#A8813F", "symbol": "蓋",
        "transparent": True, "orientable": True, "shape": "thin", "marker": True,
    },
    "iron_bars": {
        "name_ja": "鉄格子", "bedrock_id": "iron_bars",
        "makecode": "IRON_BARS", "color": "#8E9296", "symbol": "格",
        "transparent": True, "shape": "thin",
    },
    "glass_pane": {
        "name_ja": "板ガラス", "bedrock_id": "glass_pane",
        "makecode": "GLASS_PANE", "color": "#D4EAEF", "symbol": "窓",
        "transparent": True, "shape": "thin",
    },
    "cobblestone_wall": {
        "name_ja": "丸石の塀", "bedrock_id": "cobblestone_wall",
        "makecode": "COBBLESTONE_WALL", "color": "#6A6F6A", "symbol": "塀",
        "transparent": True, "shape": "thin",
    },
    "ladder": {
        "name_ja": "はしご", "bedrock_id": "ladder",
        "makecode": "LADDER", "color": "#9C7A45", "symbol": "梯",
        "transparent": True, "orientable": True, "shape": "thin", "marker": True,
            "updown": True,
    },
    "carpet_red": {
        "name_ja": "赤いカーペット", "bedrock_id": "red_carpet",
        "makecode": "RED_CARPET", "color": "#B03A3A", "symbol": "絨",
        "transparent": True, "shape": "flat",
        "flammable": True,
    },
    "lantern": {
        "name_ja": "ランタン", "bedrock_id": "lantern",
        "makecode": "LANTERN", "color": "#E8A93C", "symbol": "提",
        "transparent": True, "shape": "thin", "marker": True,
    },
    "sea_lantern": {
        "name_ja": "シーランタン", "bedrock_id": "sea_lantern",
        "makecode": "SEA_LANTERN", "color": "#B8D6CE", "symbol": "海",
    },
    "bookshelf": {
        "name_ja": "本棚", "bedrock_id": "bookshelf",
        "makecode": "BOOKSHELF", "color": "#8A6A3E", "symbol": "本",
        "flammable": True,
    },
    "crafting_table": {
        "name_ja": "作業台", "bedrock_id": "crafting_table",
        "makecode": "CRAFTING_TABLE", "color": "#8B6239", "symbol": "作",
    },
    "chest": {
        "name_ja": "チェスト", "bedrock_id": "chest",
        "makecode": "CHEST", "color": "#A57C3C", "symbol": "箱",
        "transparent": True, "orientable": True, "marker": True,
    },
    "oak_leaves": {
        "name_ja": "オークの葉", "bedrock_id": "oak_leaves",
        "makecode": "LEAVES_OAK", "color": "#4E8B3A", "symbol": "葉",
        "transparent": True,
        "flammable": True,
    },
    "flower_poppy": {
        "name_ja": "ポピー（赤い花）", "bedrock_id": "poppy",
        "makecode": "POPPY", "color": "#CE4040", "symbol": "花",
        "transparent": True, "shape": "flat", "marker": True,
        "flammable": True,
    },
    "flower_dandelion": {
        "name_ja": "タンポポ（黄色い花）", "bedrock_id": "dandelion",
        "makecode": "DANDELION", "color": "#E3C93F", "symbol": "菊",
        "transparent": True, "shape": "flat", "marker": True,
        "flammable": True,
    },
    "wool_yellow": {
        "name_ja": "黄色の羊毛", "bedrock_id": "yellow_wool",
        "makecode": "YELLOW_WOOL", "color": "#D8C13A", "symbol": "黄",
        "flammable": True,
    },
    "wool_green": {
        "name_ja": "緑の羊毛", "bedrock_id": "green_wool",
        "makecode": "GREEN_WOOL", "color": "#4E7A32", "symbol": "緑",
        "flammable": True,
    },
    "wool_black": {
        "name_ja": "黒の羊毛", "bedrock_id": "black_wool",
        "makecode": "BLACK_WOOL", "color": "#2B2B2E", "symbol": "黒",
        "flammable": True,
    },
    "tnt": {
        "name_ja": "TNT", "bedrock_id": "tnt",
        "makecode": "TNT", "color": "#D9472B", "symbol": "爆",
        "flammable": True,
    },
    "redstone_block": {
        "name_ja": "レッドストーンブロック", "bedrock_id": "redstone_block",
        "makecode": "REDSTONE_BLOCK", "color": "#8E1616", "symbol": "動",
            "redstone": True,
    },
    # ▼ レッドストーン部品は向き・取り付け面が重要なので marker（手動設置）扱い。
    #   設計側で m.notes に配置の向きと配線手順を必ず書くこと。
    "sticky_piston": {
        "name_ja": "粘着ピストン", "bedrock_id": "sticky_piston",
        "makecode": "STICKY_PISTON", "color": "#8AA05A", "symbol": "押",
        "marker": True, "orientable": True, "piston": True,
            "redstone": True,
            "updown": True,
    },
    "redstone_wire": {
        "name_ja": "レッドストーンダスト", "bedrock_id": "redstone_wire",
        "makecode": "REDSTONE_WIRE", "color": "#E03A2A", "symbol": "線", "marker": True,
            "redstone": True,
    },
    "redstone_torch": {
        "name_ja": "レッドストーントーチ", "bedrock_id": "redstone_torch",
        "makecode": "REDSTONE_TORCH", "color": "#C22F1E", "symbol": "信", "marker": True,
            "redstone": True,
    },
    "stone_pressure_plate": {
        "name_ja": "石の感圧板", "bedrock_id": "stone_pressure_plate",
        "makecode": "STONE_PRESSURE_PLATE", "color": "#B8B8B8", "symbol": "踏", "marker": True,
            "redstone": True,
    },
    "lever": {
        "name_ja": "レバー", "bedrock_id": "lever",
        "makecode": "LEVER", "color": "#8B7355", "symbol": "柄", "marker": True,
            "redstone": True,
    },
    # ------------------------------------------------------------------
    # 自動装置用。ホッパー・ディスペンサー等が無いと「全自動◯◯装置」が
    # まったく設計できず、羊毛で代用するしかなくなる（実際にそうなった）。
    # どれも向きと接続先が命なので marker（手で設置）扱いにする。
    # ------------------------------------------------------------------
    "hopper": {
        "name_ja": "ホッパー", "bedrock_id": "hopper",
        "makecode": "HOPPER", "color": "#4A4E52", "symbol": "漏",
        "transparent": True, "orientable": True, "marker": True, "redstone": True,
            "updown": True,
    },
    "dispenser": {
        "name_ja": "ディスペンサー（発射装置）", "bedrock_id": "dispenser",
        "makecode": "DISPENSER", "color": "#6E6E6E", "symbol": "発",
        "orientable": True, "marker": True, "redstone": True,
            "updown": True,
    },
    "dropper": {
        "name_ja": "ドロッパー", "bedrock_id": "dropper",
        "makecode": "DROPPER", "color": "#767676", "symbol": "落",
        "orientable": True, "marker": True, "redstone": True,
            "updown": True,
    },
    "comparator": {
        "name_ja": "レッドストーンコンパレーター", "bedrock_id": "unpowered_comparator",
        "makecode": "COMPARATOR", "color": "#C9C4BE", "symbol": "比",
        "transparent": True, "orientable": True, "marker": True, "redstone": True,
    },
    "repeater": {
        "name_ja": "レッドストーンリピーター（反復装置）", "bedrock_id": "unpowered_repeater",
        "makecode": "REPEATER", "color": "#B9B4AE", "symbol": "反",
        "transparent": True, "orientable": True, "marker": True, "redstone": True,
    },
    "observer": {
        "name_ja": "オブザーバー（観察者）", "bedrock_id": "observer",
        "makecode": "OBSERVER", "color": "#5A5A5A", "symbol": "観",
        "orientable": True, "marker": True, "redstone": True,
            "updown": True,
    },
    "sign": {
        "name_ja": "看板", "bedrock_id": "standing_sign",
        "makecode": "OAK_SIGN", "color": "#B08D55", "symbol": "札",
        "transparent": True, "orientable": True, "shape": "thin", "marker": True,
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
