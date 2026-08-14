# -*- coding: utf-8 -*-
"""ボクセルモデル → レゴ式レイヤー設計図 (自己完結HTML) を生成する。

出力する設計図の構成:
  1. ヘッダー（作品名・サイズ・総ブロック数）
  2. 完成イメージ（アイソメトリック立体図 SVG）
  3. 材料リスト（ブロック別の必要数）
  4. レイヤー図（1段目から順に、上から見た格子図。前の段は薄い点で表示）
"""

from .palette import BLOCKS, block, shade

CELL = 26  # レイヤー図の1マスのピクセル数


# ---------------------------------------------------------------- utilities

def _rel_luminance(hex_color):
    """WCAG相対輝度。"""
    h = hex_color.lstrip("#")
    lin = []
    for i in (0, 2, 4):
        c = int(h[i : i + 2], 16) / 255
        lin.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _text_color_for(hex_color):
    """マスの背景色に対して読める文字色を選ぶ（WCAGコントラスト比の高い方）。"""
    bg = _rel_luminance(hex_color)
    best, best_ratio = "#20291d", 0
    for cand in ("#20291d", "#f4f7f0"):
        fg = _rel_luminance(cand)
        lo, hi = sorted((bg, fg))
        ratio = (hi + 0.05) / (lo + 0.05)
        if ratio > best_ratio:
            best, best_ratio = cand, ratio
    return best


# ---------------------------------------------------------------- iso view

def _n(v):
    """SVG座標の数値整形。

    浮動小数点の誤差でそのまま出すと -17.939999999999998 のような桁になり、
    図が変わらないのにHTMLだけ肥大する。小数2桁で丸め、末尾の0を落とす。
    """
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def _shape_scale(b):
    """立体図での (横の倍率, 高さの倍率, 下げ量) を返す。

    下げ量は「上面をどれだけ下へずらすか」。床に接する低いブロック
    （ハーフ・カーペット・花）は、上面を下げないと宙に浮いて見える。
    """
    shape = b.get("shape")
    if shape == "slab":
        return 1.0, 0.5, 0.5
    if shape == "flat":  # カーペット・花
        return 0.9, 0.15, 0.85
    if shape == "thin":  # 柵・板ガラス・鉄格子
        return 0.4, 1.0, 0.0
    if shape == "stairs":
        # 段差が分かる程度に少しだけ低くする。低くしすぎると、階段で作った
        # 勾配屋根に隙間が空いて「穴が空いている」ように見えてしまう。
        return 1.0, 0.9, 0.1
    if b.get("marker"):
        return 0.62, 0.62, 0.0  # 既存の置き物の描き方（変更しない）
    return 1.0, 1.0, 0.0


def _is_opaque(key):
    """向こう側を完全に隠すブロックか。

    ガラス・葉・水などの透けるものと、置き物（小さく描くので隙間ができる）は
    「隠さない」扱いにする。ここを間違えると、見えるはずのブロックが消える。
    """
    b = block(key)
    return not (b.get("marker") or b.get("transparent"))



# --------------------------------------------------------------- textures
#
# 立体図をMinecraftらしく見せるための「テクスチャ」。
# 単色の立方体だと積み木にしか見えないので、面ごとに模様を敷く。
#
# 仕組み: 16×16の升目の中に、明るさを変えた長方形をいくつか置いたものを
# SVGの<pattern>にし、アイソメの傾きに合わせて patternTransform で変形する。
# パターンはブロックの種類ごとに3面ぶん（上・左・右）だけ定義するので、
# ブロックが何千個あっても図形の数は増えない（＝HTMLが太らない）。
#
# 各項目は (x, y, 幅, 高さ, 明るさ倍率)。16×16の升目での位置。
TEXTURES = {
    "noise": [  # 石・丸石・土 … ざらざらした感じ
        (1, 2, 3, 3, 0.86), (9, 1, 4, 3, 1.10), (4, 7, 5, 4, 0.90),
        (11, 9, 3, 4, 1.08), (2, 12, 4, 3, 1.04),
    ],
    "planks": [  # 板材 … 横方向の板の継ぎ目
        (0, 0, 16, 1, 0.78), (0, 5, 16, 1, 0.78), (0, 10, 16, 1, 0.78),
        (0, 15, 16, 1, 0.78), (6, 1, 1, 4, 0.88), (11, 6, 1, 4, 0.88),
        (3, 11, 1, 4, 0.88),
    ],
    "bricks": [  # レンガ・石レンガ … 段違いの目地
        (0, 0, 16, 1, 0.76), (0, 8, 16, 1, 0.76), (7, 1, 1, 7, 0.80),
        (0, 9, 1, 7, 0.80), (15, 9, 1, 7, 0.80),
    ],
    "glass": [  # ガラス … 枠とハイライト
        (0, 0, 16, 1, 0.72), (0, 15, 16, 1, 0.72), (0, 0, 1, 16, 0.72),
        (15, 0, 1, 16, 0.72), (3, 3, 3, 3, 1.25), (8, 9, 2, 2, 1.15),
    ],
    "leaves": [  # 葉 … まだらな粒
        (1, 1, 3, 3, 0.84), (6, 2, 4, 3, 1.14), (11, 5, 4, 4, 0.86),
        (2, 8, 4, 4, 1.10), (8, 11, 5, 4, 0.84), (13, 12, 2, 3, 1.06),
    ],
    "log": [  # 原木 … 縦の樹皮
        (2, 0, 1, 16, 0.84), (6, 0, 2, 16, 0.92), (11, 0, 1, 16, 0.84),
        (14, 0, 1, 16, 0.94),
    ],
    "wool": [  # 羊毛・カーペット … うっすら繊維
        (2, 3, 2, 2, 0.94), (9, 6, 3, 2, 1.06), (5, 11, 3, 2, 0.95),
        (12, 12, 2, 2, 1.04),
    ],
    "liquid": [  # 溶岩・水 … 大きめのうねり
        (0, 2, 9, 3, 1.14), (7, 7, 9, 3, 0.88), (1, 11, 8, 3, 1.10),
    ],
    "smooth": [  # クォーツ等 … ごく控えめ
        (0, 0, 16, 1, 0.95), (0, 0, 1, 16, 0.95),
    ],
    "device": [  # 機械類 … 枠と中央のくぼみ
        (0, 0, 16, 1, 0.80), (0, 15, 16, 1, 0.80), (0, 0, 1, 16, 0.80),
        (15, 0, 1, 16, 0.80), (5, 5, 6, 6, 0.86), (6, 6, 4, 4, 1.10),
    ],
}

# ブロックの種類 -> テクスチャ名。書いていないものは "smooth"。
_TEX_OF = {
    "grass": "noise", "dirt": "noise", "stone": "noise", "cobblestone": "noise",
    "cobblestone_stairs": "noise", "cobblestone_wall": "noise", "sandstone": "noise",
    "stone_bricks": "bricks", "mossy_stone_bricks": "bricks",
    "chiseled_stone_bricks": "bricks", "brick": "bricks",
    "stone_brick_stairs": "bricks", "stone_brick_slab": "bricks",
    "oak_planks": "planks", "spruce_planks": "planks", "oak_stairs": "planks",
    "oak_slab": "planks", "oak_fence": "planks", "oak_fence_gate": "planks",
    "oak_trapdoor": "planks", "bookshelf": "planks", "crafting_table": "planks",
    "sign": "planks", "ladder": "planks", "chest": "planks",
    "oak_log": "log",
    "glass": "glass", "glass_pane": "glass", "iron_bars": "glass",
    "oak_leaves": "leaves",
    "wool_white": "wool", "wool_red": "wool", "wool_blue": "wool",
    "wool_yellow": "wool", "wool_green": "wool", "wool_black": "wool",
    "carpet_red": "wool",
    "lava": "liquid", "water": "liquid",
    "hopper": "device", "dispenser": "device", "dropper": "device",
    "observer": "device", "sticky_piston": "device", "comparator": "device",
    "repeater": "device", "tnt": "device", "redstone_block": "noise",
    "glowstone": "noise", "sea_lantern": "smooth", "quartz": "smooth",
}


def _tex_name(key):
    return _TEX_OF.get(key, "smooth")


# 面ごとのパターン変形。16×16の升目をアイソメの面にぴったり載せる。
#   上面 : +x方向が(13, 6.5)、+z方向が(-13, 6.5)
#   左面 : +z方向が(-13, 6.5)、下方向が(0, 13)
#   右面 : +x方向が(13, 6.5)、下方向が(0, 13)
_FACE_MATRIX = {
    "t": (13 / 16, 6.5 / 16, -13 / 16, 6.5 / 16),
    "l": (-13 / 16, 6.5 / 16, 0, 13 / 16),
    "r": (13 / 16, 6.5 / 16, 0, 13 / 16),
}
_FACE_SHADE = {"t": 1.14, "l": 0.68, "r": 0.88}


def _tex_defs(keys):
    """使われているブロックのぶんだけ<pattern>を作る。"""
    out = []
    for key in keys:
        color = block(key)["color"]
        spec = TEXTURES[_tex_name(key)]
        for face, mat in _FACE_MATRIX.items():
            base = shade(color, _FACE_SHADE[face])
            rects = "".join(
                f'<rect x="{rx}" y="{ry}" width="{rw}" height="{rh}" '
                f'fill="{shade(base, f)}"/>'
                for rx, ry, rw, rh, f in spec
            )
            out.append(
                f'<pattern id="t{face}_{key}" width="16" height="16" '
                f'patternUnits="userSpaceOnUse" '
                f'patternTransform="matrix({_n(mat[0])},{_n(mat[1])},'
                f'{_n(mat[2])},{_n(mat[3])},0,0)">'
                f'<rect width="16" height="16" fill="{base}"/>{rects}</pattern>'
            )
    return "<defs>" + "".join(out) + "</defs>"





# レッドストーンダストが「つながる」相手。Minecraftと同じ考え方で、
# となりのダストや回路部品に向かって線が伸びる。
# これが無いと、ダストがただの赤い板になって配線が追えない。
_RS_CONNECT = (
    "redstone_wire", "redstone_torch", "repeater", "comparator", "lever",
    "sticky_piston", "dispenser", "dropper", "observer", "redstone_block",
    "stone_pressure_plate",
)


def _dust_links(cells, pos):
    """そのダストがどの向きにつながっているかを返す。

    戻り値: {"north": "flat"/"up"/"down", ...}
    ・となりが同じ高さのダストや回路部品 → まっすぐつながる(flat)
    ・となりの1段上にダストがあり、自分の真上がふさがっていない → 登る(up)
    ・となりの1段下にダストがあり、となりのマスがふさがっていない → 下る(down)
    """
    x, y, z = pos
    links = {}
    above_open = not (
        (x, y + 1, z) in cells and _is_opaque(cells[(x, y + 1, z)])
    )
    for name, (dx, dy, dz) in DIR_VEC.items():
        if name in ("up", "down"):
            continue
        n = (x + dx, y, z + dz)
        nk = cells.get(n)
        if nk in _RS_CONNECT:
            links[name] = "flat"
            continue
        up = (x + dx, y + 1, z + dz)
        if above_open and cells.get(up) == "redstone_wire":
            links[name] = "up"
            continue
        dn = (x + dx, y - 1, z + dz)
        if cells.get(dn) == "redstone_wire" and not (
            nk is not None and _is_opaque(nk)
        ):
            links[name] = "down"
    return links


def _dust_parts(links):
    """ダストの形。中心の点＋つながっている向きへの腕。"""
    if not links:
        # どこにもつながっていない＝ぽつんと1つ。Minecraftでは十字に見える
        return [(0, 0, 0.22, 0.22, 0.0625, 0.0625)]
    parts = [(0, 0, 0.16, 0.16, 0.0625, 0.0625)]
    for name in ("north", "south", "east", "west"):
        if name not in links:
            continue
        dx, _dy, dz = DIR_VEC[name]
        if dx:
            parts.append((dx * 0.33, 0, 0.17, 0.11, 0.0625, 0.0625))
        else:
            parts.append((0, dz * 0.33, 0.11, 0.17, 0.0625, 0.0625))
        if links[name] != "flat":
            # 段差でつながるときは、坂の途中に短い板を立てて上下を示す
            h = 0.5 if links[name] == "up" else 0.0625
            if dx:
                parts.append((dx * 0.47, 0, 0.05, 0.11, h + 0.0625, 0.0625))
            else:
                parts.append((0, dz * 0.47, 0.11, 0.05, h + 0.0625, 0.0625))
    return parts


def _iso_parts(key, b, facing, links=None):
    """立体図での「そのブロックの形」を、箱のリストで返す。

    各要素は (中心のずれx, 中心のずれz, 半分の幅x, 半分の幅z, 上面の高さ, 箱の高さ)。
    すべてマス単位（0.5でマスいっぱい、1.0が天井の高さ）。

    レッドストーン部品を小さな立方体で描いていたときは、Minecraftの見た目と
    まるで別物になっていた。実物は
      ダスト＝床に貼りついた線 / トーチ＝細い棒＋先端 /
      リピーター・コンパレーター＝薄い板＋小さな灯 / ホッパー＝漏斗 /
      感圧板＝薄い板 / ピストン・ディスペンサー＝ふつうの立方体
    なので、それぞれの形で描く。
    """
    d = DIR_VEC.get(facing or "", (0, 0, 0))
    shape = b.get("shape")

    if key == "redstone_wire":
        # 床に貼りついた線。つながっている向きへ腕が伸びる（配線が追えるように）
        return _dust_parts(links or {})
    if key == "stone_pressure_plate":
        return [(0, 0, 0.44, 0.44, 0.0625, 0.0625)]
    if key in ("redstone_torch", "torch"):
        # 細い棒＋先端の火
        return [(0, 0, 0.09, 0.09, 0.62, 0.62), (0, 0, 0.15, 0.15, 0.78, 0.16)]
    if key == "lever":
        return [(0, 0, 0.19, 0.19, 0.19, 0.19), (0, 0, 0.07, 0.07, 0.56, 0.37)]
    if key in ("comparator", "repeater"):
        # 薄い板の上に小さな灯が2つ（向きの軸に沿って前後に並ぶ）
        ox, oz = d[0] * 0.26, d[2] * 0.26
        return [
            (0, 0, 0.5, 0.5, 0.125, 0.125),
            (-ox, -oz, 0.06, 0.06, 0.34, 0.21),
            (ox * 0.6, oz * 0.6, 0.06, 0.06, 0.34, 0.21),
        ]
    if key == "hopper":
        # 上の受け口＋下の細い出口
        return [(0, 0, 0.5, 0.5, 1.0, 0.375), (0, 0, 0.19, 0.19, 0.625, 0.3125)]
    if key == "lantern":
        return [(0, 0, 0.19, 0.19, 0.94, 0.38)]
    if key in ("flower_poppy", "flower_dandelion"):
        return [(0, 0, 0.05, 0.05, 0.55, 0.55), (0, 0, 0.17, 0.17, 0.68, 0.16)]
    if key == "chest":
        return [(0, 0, 0.44, 0.44, 0.875, 0.875)]
    if key == "ladder":
        # 壁に貼りつく薄い板。向いている面の側に寄せる
        if d[0]:
            return [(d[0] * 0.44, 0, 0.06, 0.5, 1.0, 1.0)]
        return [(0, d[2] * 0.44, 0.5, 0.06, 1.0, 1.0)]
    if key == "door":
        if d[0]:
            return [(d[0] * 0.42, 0, 0.08, 0.5, 1.0, 1.0)]
        return [(0, d[2] * 0.42, 0.5, 0.08, 1.0, 1.0)]
    if key == "oak_trapdoor":
        return [(0, 0, 0.5, 0.5, 0.19, 0.19)]
    if key == "oak_fence_gate":
        if d[0]:
            return [(0, 0, 0.09, 0.5, 1.0, 0.75)]
        return [(0, 0, 0.5, 0.09, 1.0, 0.75)]
    if key == "sign":
        return [(0, 0, 0.06, 0.06, 0.5, 0.5), (0, 0, 0.44, 0.06, 1.0, 0.44)]

    if shape == "stairs" and facing:
        # 下半分の箱＋矢印側の背の高い箱（矢印の方が高い＝屋根なら棟へ向ける）
        if d[0]:
            return [(0, 0, 0.5, 0.5, 0.5, 0.5),
                    (d[0] * 0.25, 0, 0.25, 0.5, 1.0, 0.5)]
        return [(0, 0, 0.5, 0.5, 0.5, 0.5),
                (0, d[2] * 0.25, 0.5, 0.25, 1.0, 0.5)]
    if shape == "slab":
        return [(0, 0, 0.5, 0.5, 0.5, 0.5)]
    if shape == "flat":  # カーペット
        return [(0, 0, 0.5, 0.5, 0.0625, 0.0625)]
    if shape == "thin":  # 柵・板ガラス・鉄格子・塀
        return [(0, 0, 0.12, 0.12, 1.0, 1.0)]
    if shape == "stairs":
        return [(0, 0, 0.5, 0.5, 0.9, 0.9)]  # 向き未指定のとき
    return [(0, 0, 0.5, 0.5, 1.0, 1.0)]


def _iso_box(cx, cy, offx, offz, ax, az, top_frac, hgt, key, faint_ok=True):
    """立方体の一部を描く（階段のように「箱を2つ重ねた形」を作るため）。

    cx, cy    … そのマスの上面の手前かどの位置（従来の基準点）
    offx,offz … マスの中心からのずれ（マス単位。0.25なら4分の1マス）
    ax, az    … 半分の大きさ（0.5でマスいっぱい、0.25で半分の幅）
    top_frac  … 上面の高さ（1.0でマスの天井、0.5で半分の高さ）
    hgt       … 箱の高さ（マス単位）
    """
    hw, hh, hz = 13, 6.5, 13
    b = block(key)
    c = b["color"]
    # 箱の上面の中心
    ccx = cx + (offx - offz) * hw
    ccy = cy + (1 - top_frac) * hz - hh + (offx + offz) * hh
    uxx, uxy = ax * hw, ax * hh
    uzx, uzy = -az * hw, az * hh
    bot = (ccx + uxx + uzx, ccy + uxy + uzy)
    lft = (ccx - uxx + uzx, ccy - uxy + uzy)
    top = (ccx - uxx - uzx, ccy - uxy - uzy)
    rgt = (ccx + uxx - uzx, ccy + uxy - uzy)
    h = hgt * hz

    def poly(pts, fill):
        d = " ".join(f"{_n(a)},{_n(b2)}" for a, b2 in pts)
        return (f'<polygon points="{d}" fill="{fill}" '
                f'stroke="{shade(c, 0.5)}" stroke-width="0.5"/>')

    full = ax == 0.5 and az == 0.5 and hgt == 1.0
    fl = f"url(#tl_{key})" if full else shade(c, 0.68)
    fr = f"url(#tr_{key})" if full else shade(c, 0.88)
    ft = f"url(#tt_{key})" if full else shade(c, 1.14)
    return (
        poly([lft, bot, (bot[0], bot[1] + h), (lft[0], lft[1] + h)], fl)
        + poly([rgt, bot, (bot[0], bot[1] + h), (rgt[0], rgt[1] + h)], fr)
        + poly([bot, lft, top, rgt], ft)
    )


def _iso_cells_svg(cells, highlight, label, max_w=640, scale=1, facings=None):
    """ブロックの集まりを立体図(アイソメトリック)で描く。

    cells     … {(x,y,z): ブロックキー}
    highlight … 全色で描く座標の集合。None なら全部そのまま描く。
                指定した場合、それ以外は薄く描いて主役を目立たせる。
    """
    hw, hh, hz = 13, 6.5, 13  # 半幅 / 上面の半高 / ブロックの高さ
    facings = facings or {}
    pts = []
    cubes = []
    for (x, y, z), key in cells.items():
        # 6面すべてを不透明ブロックに囲まれていれば、どこからも見えないので描かない
        if all(
            n in cells and _is_opaque(cells[n])
            for n in (
                (x - 1, y, z), (x + 1, y, z),
                (x, y - 1, z), (x, y + 1, z),
                (x, y, z - 1), (x, y, z + 1),
            )
        ):
            continue
        cx = (x - z) * hw
        cy = (x + z) * hh - y * hz
        cubes.append((x + z, y, cx, cy, key,
                      highlight is None or (x, y, z) in highlight, (x, y, z)))
        pts += [(cx - hw, cy - 2 * hh), (cx + hw, cy + hz)]
    if not cubes:
        return ""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    pad = 16
    vb = (min(xs) - pad, min(ys) - pad,
          (max(xs) - min(xs)) + pad * 2, (max(ys) - min(ys)) + pad * 2)

    faces = []
    for depth, y, cx, cy, key, main, key_pos in sorted(cubes, key=lambda c: (c[0], c[1])):
        b = block(key)
        c = b["color"]
        # 形ごとに描き分ける。立方体でないブロック（階段・ハーフ・柵など）を
        # 立方体として描くと、立体図がのっぺりして細部が伝わらない。
        links = _dust_links(cells, key_pos) if key == "redstone_wire" else None
        body = "".join(
            _iso_box(cx, cy, *part, key)
            for part in _iso_parts(key, b, facings.get(key_pos), links)
        )
        faces.append(body if main else f'<g class="faint">{body}</g>')
    used = sorted({c[4] for c in cubes})
    return (
        f'<svg viewBox="{vb[0]:.0f} {vb[1]:.0f} {vb[2]:.0f} {vb[3]:.0f}" '
        f'role="img" aria-label="{label}" '
        f'style="max-width:{min(max_w, vb[2] * scale):.0f}px">'
        + _tex_defs(used) + "".join(faces) + "</svg>"
    )


def _iso_svg(model):
    """完成イメージのアイソメトリック図。"""
    return _iso_cells_svg(model.blocks, None, "完成イメージ", facings=model.facing)



def _dust_wire_svg(px, py, cell, links):
    """上から見た図に、ダストのつながり方を線で描く。

    マスを赤く塗るだけだと「どこからどこへつながっているか」が読めない。
    中心の点と、つながっている向きへの線を重ねて描く。
    段差でつながるときは向きの先に小さな「上」「下」を添える。
    """
    cx, cy = px + cell / 2, py + cell / 2
    w = cell * 0.17          # 線の太さ
    out = [
        f'<rect x="{_n(cx - w * 0.9)}" y="{_n(cy - w * 0.9)}" '
        f'width="{_n(w * 1.8)}" height="{_n(w * 1.8)}" class="wire"/>'
    ]
    if not links:
        return "".join(out)
    for name, kind in links.items():
        dx, _dy, dz = DIR_VEC[name]
        if dx:
            x0 = cx if dx > 0 else px
            out.append(
                f'<rect x="{_n(x0)}" y="{_n(cy - w / 2)}" '
                f'width="{_n(cell / 2)}" height="{_n(w)}" class="wire"/>'
            )
        else:
            y0 = cy if dz > 0 else py
            out.append(
                f'<rect x="{_n(cx - w / 2)}" y="{_n(y0)}" '
                f'width="{_n(w)}" height="{_n(cell / 2)}" class="wire"/>'
            )
        if kind != "flat":
            g = "上" if kind == "up" else "下"
            tx = cx + dx * cell * 0.34
            ty = cy + dz * cell * 0.34 + cell * 0.1
            out.append(
                f'<text x="{_n(tx)}" y="{_n(ty)}" class="wireup">{g}</text>'
            )
    return "".join(out)


def _facing_arrow(px, py, facing, color):
    return _facing_arrow_at(px, py, CELL, facing, color)


def _facing_arrow_at(px, py, cell, facing, color):
    """マスの中に向きの三角形を描く。

    階段などは向きが分からないと作れないので、記号だけでなく
    「どちらを向いているか」を図の上で必ず読めるようにする。
    図は上が北なので、north=上・south=下・east=右・west=左。
    """
    cx, cy = px + cell / 2, py + cell / 2
    r = cell * 0.146      # 三角形の大きさ（記号と重ならない大きさに抑える）
    d = cell / 2 - 1.6    # マスのふちからの距離
    if facing in ("down", "up"):
        # 上下向きを矢印で描くと南北と見分けがつかないので、隅に文字で出す。
        # ホッパーやディスペンサーは下向きが基本なので、これが読めないと作れない。
        g = "下" if facing == "down" else "上"
        return (f'<text x="{_n(px + cell * 0.2)}" y="{_n(py + cell * 0.33)}" '
                f'class="updown" fill="{color}">{g}</text>')
    tri = {
        "north": ((cx, cy - d), (cx - r, cy - d + r), (cx + r, cy - d + r)),
        "south": ((cx, cy + d), (cx - r, cy + d - r), (cx + r, cy + d - r)),
        "west": ((cx - d, cy), (cx - d + r, cy - r), (cx - d + r, cy + r)),
        "east": ((cx + d, cy), (cx + d - r, cy - r), (cx + d - r, cy + r)),
    }[facing]
    pts = " ".join(f"{_n(a)},{_n(b)}" for a, b in tri)
    return f'<polygon points="{pts}" class="dir" fill="{color}"/>'


# ---------------------------------------------------------------- layers

def _layer_svg(model, y, layer, prev_layer, x_range, z_range):
    """1レイヤー分の上面図。上が北。"""
    x1, x2 = x_range
    z1, z2 = z_range
    cols = x2 - x1 + 1
    rows = z2 - z1 + 1
    m = 22  # 座標ラベル用マージン
    w = cols * CELL + m + 2
    h = rows * CELL + m + 2
    # 空きマスを1マスずつ<rect>で描くと、大きな設計図でHTMLが肥大する
    # （32×32×24段で空マスだけ2万個以上の図形になっていた）。
    # 背景1枚＋罫線1本のパスにまとめる。見た目は1マスずつ描いたときと同じ。
    grid = "".join(
        f"M{m + i * CELL} {m}V{m + rows * CELL}" for i in range(cols + 1)
    ) + "".join(
        f"M{m} {m + j * CELL}H{m + cols * CELL}" for j in range(rows + 1)
    )
    out = [
        f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{y + 1}段目" '
        f'style="width:{w}px;max-width:100%">'
        f'<rect x="{m}" y="{m}" width="{cols * CELL}" height="{rows * CELL}" '
        f'class="empty-bg"/><path class="grid" d="{grid}"/>'
    ]
    # 座標ラベル
    for i in range(cols):
        out.append(
            f'<text x="{m + i * CELL + CELL / 2}" y="{m - 8}" class="ax">{x1 + i}</text>'
        )
    for j in range(rows):
        out.append(
            f'<text x="{m - 8}" y="{m + j * CELL + CELL / 2 + 4}" class="ax">{z1 + j}</text>'
        )
    # マス
    for j in range(rows):
        for i in range(cols):
            x, z = x1 + i, z1 + j
            px, py = m + i * CELL, m + j * CELL
            key = layer.get((x, z))
            if key:
                b = block(key)
                if key == "redstone_wire":
                    # ダストは記号ではなく配線の形で描く（つながりが読めるように）
                    out.append(
                        f'<rect x="{px}" y="{py}" width="{CELL}" height="{CELL}" '
                        f'class="wire-bg"/>'
                        + _dust_wire_svg(px, py, CELL,
                                         _dust_links(model.blocks, (x, y, z)))
                    )
                else:
                    out.append(
                        f'<rect x="{px}" y="{py}" width="{CELL}" height="{CELL}" '
                        f'fill="{b["color"]}" stroke="{shade(b["color"], 0.6)}"/>'
                        f'<text x="{px + CELL / 2}" y="{py + CELL / 2 + 5}" '
                        f'class="sym" fill="{_text_color_for(b["color"])}">{b["symbol"]}</text>'
                    )
                f = model.facing.get((x, y, z))
                if f:
                    out.append(
                        _facing_arrow(px, py, f, _text_color_for(b["color"]))
                    )
            elif prev_layer and (x, z) in prev_layer:
                # 下の段にブロックがある目印（位置合わせ用）。空きマス自体は
                # 上で敷いたパターンが担当するので、ここでは描かない
                out.append(
                    f'<circle cx="{px + CELL / 2}" cy="{py + CELL / 2}" '
                    f'r="2.2" class="ghost"/>'
                )
    out.append("</svg>")
    return "".join(out)



# ------------------------------------------------- redstone circuit detail

CELL_RS = 34   # 回路詳細図の1マス（読み違いが命取りなので大きめ）
RS_MARGIN = 2  # 回路のまわり何マスまで一緒に描くか（支えの床や壁が要るため）

DIR_VEC = {
    "north": (0, 0, -1), "south": (0, 0, 1),
    "east": (1, 0, 0), "west": (-1, 0, 0),
    "down": (0, -1, 0), "up": (0, 1, 0),
}
DIR_JA = {"north": "北", "south": "南", "east": "東", "west": "西",
          "down": "下", "up": "上"}


def _rs_cells(model):
    """レッドストーン部品のある座標。"""
    return {p: k for p, k in model.blocks.items() if block(k).get("redstone")}


def _rs_bounds(model, cells):
    """部品のまわりに余白を足した範囲。支えの床や壁も見えるようにする。"""
    xs = [p[0] for p in cells]
    ys = [p[1] for p in cells]
    zs = [p[2] for p in cells]
    bx1, by1, bz1, bx2, by2, bz2 = model.bounds()
    return (
        max(bx1, min(xs) - RS_MARGIN), max(by1, min(ys) - 1), max(bz1, min(zs) - RS_MARGIN),
        min(bx2, max(xs) + RS_MARGIN), min(by2, max(ys) + 1), min(bz2, max(zs) + RS_MARGIN),
    )


def _rs_role(model, key, facing):
    """その部品が回路で何をしているかの説明（部品の種類ごとに1つ）。"""
    b = block(key)
    if key == "redstone_torch":
        return ("真下のブロックの上に立てる（壁に横付けしない）。"
                "その真下のブロックが動力を受けると消える＝スイッチが逆になる。"
                "ふだんは真上のブロックを強く動力化している。")
    if key == "stone_pressure_plate":
        return ("踏むと真下のブロックを強く動力化する。"
                "そのブロックにとなり合うレッドストーンダストへ動力が伝わる。")
    if b.get("piston"):
        if not facing:
            return "向きが決まっていない。どちらへ押すか決めないと作れない。"
        return (f"{DIR_JA[facing]}向き（図の矢印のとおり）。"
                "前の1マスにあるブロックを、前の2マス目へ押し出す。"
                "前の2マス目がふさがっていると伸びられないので必ず空けておく。"
                "動力を受けているあいだ伸びたままになる。")
    if key == "hopper":
        return ("アイテムを吸い取り、向いている先（チェスト・ホッパー・ディスペンサー等）へ"
                "流し込む。真上に落ちたアイテムも拾う。向きを間違えると流れが止まって"
                "装置全体が動かなくなる。")
    if key == "dispenser":
        return ("動力を受けると中身を1つ発射する。向いている方向へ飛んでいく。"
                "卵や矢を撃ち出すのに使う。")
    if key == "dropper":
        return ("動力を受けると中身を1つ、向いている先へ押し出す（飛ばさずに置く）。")
    if key == "comparator":
        return ("うしろにあるチェストやディスペンサーの「中身の量」を信号の強さにして出す。"
                "中身が少ないと信号も弱い。真横にレッドストーンダストを置くと"
                "止まってしまうので、横は必ず空けるか固いブロックにする。")
    if key == "repeater":
        return ("弱った信号を15の強さに戻して先へ送る。うしろから入れて前へ出す。"
                "コンパレーターの弱い信号を遠くまで届かせるのに必要。")
    if key == "observer":
        return ("前のブロックが変化したときに、うしろ側から短い信号を出す。")
    if key == "redstone_wire":
        return ("となり合うダストへ信号を運ぶ（動力源から15マスまで）。"
                "かならず下に支えのブロックが要る。位置は下の図で確かめる。")
    if key == "lever":
        return "手で入れ切りするスイッチ。取り付けた面のブロックを動力化する。"
    if key == "redstone_block":
        return "置くだけで常にONの動力源。となりの部品をずっと動かし続ける。"
    return b["name_ja"]



def _rs_visual_cells(model, rs):
    """回路だけの立体図に描くブロックを選ぶ。

    範囲をまるごと切り出すと、床や壁にさえぎられて肝心の配線が見えない。
    そこで「部品」＋「その働きに直接かかわるブロック」だけを取り出す:
      - 部品の真下（支え。トーチや感圧板はここが動力を受ける）
      - ピストンが押す先の1マスと2マス目
      - トーチの真上（動力化されるブロック）
    """
    cells = {}
    for pos in rs:
        cells[pos] = model.blocks[pos]
    # 集合ではなくリストで順番を保つ。集合だと並び順が実行ごとに変わり、
    # 図の描画順（＝重なり順）がぶれて Python版とJS版で出力が食い違う。
    extra = []
    for pos, key in rs.items():
        x, y, z = pos
        extra.append((x, y - 1, z))  # 支え
        if key == "redstone_torch":
            extra.append((x, y + 1, z))  # トーチが動力化する先
        if block(key).get("piston"):
            f = model.facing.get(pos)
            if f:
                dx, dy, dz = DIR_VEC[f]
                extra.append((x + dx, y + dy, z + dz))
                extra.append((x + dx * 2, y + dy * 2, z + dz * 2))
    for pos in extra:
        if pos not in cells and pos in model.blocks:
            cells[pos] = model.blocks[pos]
    return cells


def _rs_layer_svg(model, y, rs, box):
    """回路詳細図の1段分。回路は色つき、まわりのブロックは薄く描く。"""
    x1, _, z1, x2, _, z2 = box
    cols, rows = x2 - x1 + 1, z2 - z1 + 1
    m = 26
    w, h = cols * CELL_RS + m + 2, rows * CELL_RS + m + 2
    grid = "".join(
        f"M{m + i * CELL_RS} {m}V{m + rows * CELL_RS}" for i in range(cols + 1)
    ) + "".join(
        f"M{m} {m + j * CELL_RS}H{m + cols * CELL_RS}" for j in range(rows + 1)
    )
    out = [
        f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="回路 {y + 1}段目" '
        f'style="width:{w}px;max-width:100%">'
        f'<rect x="{m}" y="{m}" width="{cols * CELL_RS}" height="{rows * CELL_RS}" '
        f'class="empty-bg"/><path class="grid" d="{grid}"/>'
    ]
    for i in range(cols):
        out.append(
            f'<text x="{m + i * CELL_RS + CELL_RS / 2}" y="{m - 9}" class="ax">{x1 + i}</text>'
        )
    for j in range(rows):
        out.append(
            f'<text x="{m - 9}" y="{m + j * CELL_RS + CELL_RS / 2 + 4}" class="ax">{z1 + j}</text>'
        )
    for j in range(rows):
        for i in range(cols):
            x, z = x1 + i, z1 + j
            key = model.get(x, y, z)
            if not key:
                continue
            px, py = m + i * CELL_RS, m + j * CELL_RS
            b = block(key)
            is_rs = (x, y, z) in rs
            cls = "" if is_rs else ' class="faint"'
            if key == "redstone_wire":
                out.append(
                    f'<g{cls}><rect x="{px}" y="{py}" width="{CELL_RS}" '
                    f'height="{CELL_RS}" class="wire-bg"/>'
                    + _dust_wire_svg(px, py, CELL_RS,
                                     _dust_links(model.blocks, (x, y, z)))
                    + "</g>"
                )
            else:
                out.append(
                    f'<g{cls}><rect x="{px}" y="{py}" width="{CELL_RS}" height="{CELL_RS}" '
                    f'fill="{b["color"]}" stroke="{shade(b["color"], 0.6)}"/>'
                    f'<text x="{px + CELL_RS / 2}" y="{py + CELL_RS / 2 + 6}" '
                    f'class="sym rs" fill="{_text_color_for(b["color"])}">{b["symbol"]}</text></g>'
                )
            if is_rs:
                out.append(
                    f'<rect x="{px + 1.5}" y="{py + 1.5}" width="{CELL_RS - 3}" '
                    f'height="{CELL_RS - 3}" class="rs-ring"/>'
                )
            f = model.facing.get((x, y, z))
            if f:
                out.append(_facing_arrow_at(px, py, CELL_RS, f, _text_color_for(b["color"])))
    out.append("</svg>")
    return "".join(out)


def _circuit_section(model):
    """レッドストーン回路だけを抜き出した詳細ページ。回路が無ければ空。"""
    rs = _rs_cells(model)
    if not rs:
        return ""
    box = _rs_bounds(model, rs)
    x1, y1, z1, x2, y2, z2 = box

    # 段ごとの図（回路部品がある段だけ。支えを見せるため上下1段も出す）
    ys = sorted({p[1] for p in rs})
    show = sorted(set(range(max(y1, min(ys) - 1), min(y2, max(ys) + 1) + 1)))
    cards = []
    for y in show:
        n = sum(1 for p in rs if p[1] == y)
        head = f"{n}個の部品" if n else "部品なし（支えの段）"
        cards.append(
            f'<div class="layer-card rs-card"><div class="layer-head">'
            f'<span class="layer-no">{y + 1}段目</span>'
            f'<span class="layer-count">{head}</span></div>'
            f'<div class="grid-wrap">{_rs_layer_svg(model, y, rs, box)}</div></div>'
        )

    # 部品ごとの一覧。同じ種類・同じ向きはまとめて1行にする
    # （ダストを1個ずつ並べると同じ文が何十行も続いて読めなくなる）
    groups = {}
    for pos in sorted(rs, key=lambda p: (p[1], p[2], p[0])):
        g = (rs[pos], model.facing.get(pos))
        groups.setdefault(g, []).append(pos)

    rows = []
    for (key, facing), poss in groups.items():
        b = block(key)
        if len(poss) <= 6:
            where = "<br>".join(f"{p[1] + 1}段目 x={p[0]}, z={p[2]}" for p in poss)
        else:
            ys = sorted({p[1] for p in poss})
            where = ("<br>".join(f"{y + 1}段目" for y in ys)
                     + f"<br>ぜんぶで{len(poss)}個")
        rows.append(
            f'<tr><td class="n">{where}</td>'
            f'<td><span class="swatch" style="background:{b["color"]}"></span>'
            f'<b>{b["name_ja"]}</b>'
            + (f'<b>（{DIR_JA[facing]}向き）</b>' if facing else "")
            + f' ×{len(poss)}'
            + f'<div class="role">{_rs_role(model, key, facing)}</div></td></tr>'
        )

    return (
        '<h2>レッドストーン回路のくわしい図</h2>'
        '<p class="hint">仕掛けの部分だけを切り出した図。全体の設計図とは別に、'
        'ここで位置と向きを確かめてから作る。</p>'
        '<div class="panel iso-panel rs-iso">'
        + _iso_cells_svg(_rs_visual_cells(model, rs), set(rs), "回路だけの立体図", 560, 2,
                         model.facing)
        + '<p class="cap">回路だけを立体で見たところ。色のついたものがレッドストーン部品、'
          '薄いものは支えのブロックとピストンが押す先。</p></div>'
        '<h3 class="rs-h3">部品と役割</h3>'
        f'<div class="panel"><table class="bom rs-list">'
        f'<tr><th>位置</th><th>部品と役割</th></tr>{"".join(rows)}</table></div>'
        '<h3 class="rs-h3">段ごとの位置（上から見た図）</h3>'
        f'<p class="hint">まわり{RS_MARGIN}マスの支えのブロックも薄い色で描いてある。'
        '回路は1マスのズレでも動かなくなるので、この図で1つずつ確かめる。</p>'
        f'<div class="layers rs-layers">{"".join(cards)}</div>'
    )


# ---------------------------------------------------------------- html

CSS = """
:root {
  --ground: #f2f4ee; --panel: #fbfcf8; --ink: #22301f; --muted: #5d6b56;
  --line: #d3dbc9; --accent: #3e9b4f; --accent-ink: #2c6d38;
  --cell-empty: #eef1e8; --cell-line: #dde3d4; --ghost: #b9c3ad;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ground: #141811; --panel: #1c2317; --ink: #e7ede0; --muted: #9cab92;
    --line: #37422e; --accent: #59b368; --accent-ink: #8ed49a;
    --cell-empty: #222a1c; --cell-line: #333e29; --ghost: #55654a;
  }
}
:root[data-theme="dark"] {
  --ground: #141811; --panel: #1c2317; --ink: #e7ede0; --muted: #9cab92;
  --line: #37422e; --accent: #59b368; --accent-ink: #8ed49a;
  --cell-empty: #222a1c; --cell-line: #333e29; --ghost: #55654a;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--ground); color: var(--ink);
  font-family: "Hiragino Kaku Gothic ProN", "Hiragino Sans", "Noto Sans JP",
    "Yu Gothic UI", "Meiryo", sans-serif;
  line-height: 1.7;
}
main { max-width: 980px; margin: 0 auto; padding: 32px 20px 72px; }
header.hero { border-bottom: 3px solid var(--accent); padding-bottom: 20px; margin-bottom: 28px; }
.eyebrow {
  font-size: 12px; letter-spacing: 0.18em; color: var(--accent-ink);
  font-weight: 700; margin: 0 0 6px;
}
h1 { font-size: 30px; margin: 0 0 10px; letter-spacing: 0.02em; text-wrap: balance; }
.desc { color: var(--muted); margin: 0 0 14px; max-width: 40em; }
.stats { display: flex; flex-wrap: wrap; gap: 10px 26px; font-size: 14px; }
.stats b { font-variant-numeric: tabular-nums; font-size: 18px; }
.stats span { color: var(--muted); }
h2 {
  font-size: 20px; margin: 44px 0 4px; padding-left: 12px;
  border-left: 5px solid var(--accent);
}
.hint { color: var(--muted); font-size: 13.5px; margin: 0 0 16px; }
.panel {
  background: var(--panel); border: 1px solid var(--line); border-radius: 6px;
  padding: 18px; overflow-x: auto;
}
.iso-panel { text-align: center; }
table.bom { border-collapse: collapse; width: 100%; font-size: 14.5px; }
table.bom th {
  text-align: left; color: var(--muted); font-weight: 600; font-size: 12.5px;
  letter-spacing: 0.08em; border-bottom: 2px solid var(--line); padding: 6px 10px;
}
table.bom td { border-bottom: 1px solid var(--line); padding: 7px 10px; }
table.bom td.n { text-align: right; font-variant-numeric: tabular-nums; font-weight: 700; }
.swatch {
  display: inline-block; width: 18px; height: 18px; border-radius: 3px;
  vertical-align: -4px; margin-right: 8px; border: 1px solid rgb(0 0 0 / 25%);
}
.layers { display: flex; flex-direction: column; gap: 26px; }
.layer-card { background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 16px 18px; }
.layer-head { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; margin-bottom: 10px; }
.layer-no {
  background: var(--accent); color: #fff; font-weight: 800; font-size: 15px;
  border-radius: 4px; padding: 2px 12px; letter-spacing: 0.05em;
}
.layer-count { color: var(--muted); font-size: 13.5px; }
.grid-wrap { overflow-x: auto; }
svg text.ax {
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  font-size: 9px; fill: var(--muted); text-anchor: middle;
}
svg text.sym { font-size: 12px; font-weight: 700; text-anchor: middle; }
svg rect.empty { fill: var(--cell-empty); stroke: var(--cell-line); }
svg rect.empty-bg { fill: var(--cell-empty); }
svg path.grid { fill: none; stroke: var(--cell-line); stroke-width: 1; }
svg polygon.dir { opacity: 0.85; }
svg rect.wire-bg { fill: var(--cell-empty); stroke: var(--cell-line); }
svg rect.wire { fill: #e03a2a; }
svg text.wireup { font-size: 8.5px; font-weight: 800; fill: #7b1f17;
  text-anchor: middle; }
svg text.updown { font-size: 9.5px; font-weight: 800; text-anchor: middle;
  opacity: 0.9; }
svg g.faint { opacity: 0.28; }
h3.rs-h3 { font-size: 15.5px; margin: 26px 0 6px; color: var(--accent-ink);
  letter-spacing: 0.04em; }
.rs-iso .cap { color: var(--muted); font-size: 13px; margin: 10px 0 0; }
svg rect.rs-ring { fill: none; stroke: var(--accent-ink); stroke-width: 2; rx: 2; }
svg text.sym.rs { font-size: 15px; }
table.bom.rs-list td.n { text-align: left; font-size: 12px; line-height: 1.45; white-space: nowrap; }
table.bom.rs-list .role { color: var(--muted); font-size: 13px; margin-top: 3px; }
.rs-layers { margin-top: 18px; }
svg circle.ghost { fill: var(--ghost); }
.compass { font-size: 12.5px; color: var(--muted); margin-top: 8px; }
.layer-note {
  margin-top: 10px; padding: 10px 12px; border-radius: 5px; font-size: 13.5px;
  background: color-mix(in srgb, var(--accent) 12%, var(--panel));
  border: 1px solid var(--accent); color: var(--ink);
}
.layer-note b { color: var(--accent-ink); }
ol.notes { margin: 0; padding-left: 1.4em; }
ol.notes li { margin: 6px 0; }
footer { margin-top: 56px; color: var(--muted); font-size: 12.5px; border-top: 1px solid var(--line); padding-top: 14px; }
"""


def render_html(model):
    model.normalize()
    x1, y1, z1, x2, y2, z2 = model.bounds()
    sx, sy, sz = model.size()
    counts = model.counts()
    total = sum(n for _, n in counts)

    # 材料リスト
    bom_rows = "".join(
        f'<tr><td><span class="swatch" style="background:{block(k)["color"]}"></span>'
        f'{block(k)["name_ja"]}'
        f'<span style="color:var(--muted)">（記号: {block(k)["symbol"]}）</span></td>'
        f'<td class="n">{n} 個</td></tr>'
        for k, n in counts
    )

    # レイヤー図
    layer_cards = []
    prev = None
    for y, layer in model.layers():
        if not layer:
            prev = layer
            continue
        used = {}
        for k in layer.values():
            used[k] = used.get(k, 0) + 1
        count_txt = " ／ ".join(
            f"{block(k)['name_ja']}×{n}"
            for k, n in sorted(used.items(), key=lambda kv: -kv[1])
        )
        note_txt = getattr(model, "layer_notes", {}).get(y)
        note_html = (
            f'<div class="layer-note"><b>この段の注意:</b> {note_txt}</div>'
            if note_txt
            else ""
        )
        layer_cards.append(
            f'<div class="layer-card">'
            f'<div class="layer-head"><span class="layer-no">{y + 1}段目</span>'
            f'<span class="layer-count">この段で使うブロック: {count_txt}</span></div>'
            f'<div class="grid-wrap">'
            + _layer_svg(model, y, layer, prev, (x1, x2), (z1, z2))
            + "</div>"
            f'<div class="compass">図の上が北（z={z1}）・左が西（x={x1}）。'
            f"小さな点は下の段のブロックの位置（位置合わせの目印）。</div>"
            + note_html
            + "</div>"
        )
        prev = layer

    desc = f'<p class="desc">{model.description}</p>' if model.description else ""
    circuit_section = _circuit_section(model)
    notes_section = ""
    if model.notes:
        items = "".join(f"<li>{n}</li>" for n in model.notes)
        notes_section = (
            '<h2>つくるときのポイント</h2>'
            '<p class="hint">向きが大事な部品（ピストン・レッドストーン等）の置き方。'
            "ブロックを積み終わってから、この順番で仕上げる。</p>"
            f'<div class="panel"><ol class="notes">{items}</ol></div>'
        )
    return f"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{model.name} — マイクラ設計図</title>
<style>{CSS}</style>
<main>
<header class="hero">
  <p class="eyebrow">MINECRAFT EDUCATION 設計図</p>
  <h1>{model.name}</h1>
  {desc}
  <div class="stats">
    <div><b>{sx} × {sz}</b> <span>マス（横×奥行き）</span></div>
    <div><b>{sy}</b> <span>段</span></div>
    <div><b>{total}</b> <span>ブロック合計</span></div>
  </div>
</header>

<h2>完成イメージ</h2>
<p class="hint">ななめ上から見たところ。手前が南東の角（南の面が左手前）。</p>
<div class="panel iso-panel">{_iso_svg(model)}</div>

<h2>材料リスト</h2>
<p class="hint">はじめに集めておくブロック。インベントリにそろえてからスタート！</p>
<div class="panel"><table class="bom">
<tr><th>ブロック</th><th style="text-align:right">必要数</th></tr>
{bom_rows}
</table></div>

{notes_section}
{circuit_section}
<h2>作り方（1段ずつ）</h2>
<p class="hint">レゴの説明書と同じで、下の段から順番に置いていく。数字はマスの座標。</p>
<div class="layers">{"".join(layer_cards)}</div>

<footer>Minecraft Education 用レイヤー設計図 ・ 上から見た図（上=北） ・
たいまつ・ドアなどの置き物は最後に設置するときれいに作れます。</footer>
</main>
"""
