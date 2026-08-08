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


def _is_opaque(key):
    """向こう側を完全に隠すブロックか。

    ガラス・葉・水などの透けるものと、置き物（小さく描くので隙間ができる）は
    「隠さない」扱いにする。ここを間違えると、見えるはずのブロックが消える。
    """
    b = block(key)
    return not (b.get("marker") or b.get("transparent"))


def _iso_svg(model):
    """完成イメージのアイソメトリック図。"""
    hw, hh, hz = 13, 6.5, 13  # 半幅 / 上面の半高 / ブロックの高さ
    pts = []
    cubes = []
    blocks = model.blocks
    for (x, y, z), key in blocks.items():
        # 6面すべてを不透明ブロックに囲まれていれば、どこからも見えないので描かない
        if all(
            n in blocks and _is_opaque(blocks[n])
            for n in (
                (x - 1, y, z), (x + 1, y, z),
                (x, y - 1, z), (x, y + 1, z),
                (x, y, z - 1), (x, y, z + 1),
            )
        ):
            continue
        cx = (x - z) * hw
        cy = (x + z) * hh - y * hz
        cubes.append((x + z, y, cx, cy, key))
        pts += [(cx - hw, cy - 2 * hh), (cx + hw, cy + hz)]
    if not cubes:
        return ""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    pad = 16
    vb = (min(xs) - pad, min(ys) - pad,
          (max(xs) - min(xs)) + pad * 2, (max(ys) - min(ys)) + pad * 2)

    faces = []
    for depth, y, cx, cy, key in sorted(cubes, key=lambda c: (c[0], c[1])):
        b = block(key)
        c = b["color"]
        s = 0.62 if b.get("marker") else 1.0  # 置き物は小さめに描く
        w, h2, z2 = hw * s, hh * s, hz * s
        top = (f"{_n(cx)},{_n(cy)} {_n(cx - w)},{_n(cy - h2)} "
               f"{_n(cx)},{_n(cy - 2 * h2)} {_n(cx + w)},{_n(cy - h2)}")
        left = (f"{_n(cx - w)},{_n(cy - h2)} {_n(cx)},{_n(cy)} "
                f"{_n(cx)},{_n(cy + z2)} {_n(cx - w)},{_n(cy - h2 + z2)}")
        right = (f"{_n(cx + w)},{_n(cy - h2)} {_n(cx)},{_n(cy)} "
                 f"{_n(cx)},{_n(cy + z2)} {_n(cx + w)},{_n(cy - h2 + z2)}")
        faces.append(
            f'<polygon points="{left}" fill="{shade(c, 0.68)}"/>'
            f'<polygon points="{right}" fill="{shade(c, 0.88)}"/>'
            f'<polygon points="{top}" fill="{shade(c, 1.14)}" '
            f'stroke="{shade(c, 0.55)}" stroke-width="0.6"/>'
        )
    return (
        f'<svg viewBox="{vb[0]:.0f} {vb[1]:.0f} {vb[2]:.0f} {vb[3]:.0f}" '
        f'role="img" aria-label="完成イメージ" '
        f'style="max-width:{min(640, vb[2]):.0f}px">' + "".join(faces) + "</svg>"
    )


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
                out.append(
                    f'<rect x="{px}" y="{py}" width="{CELL}" height="{CELL}" '
                    f'fill="{b["color"]}" stroke="{shade(b["color"], 0.6)}"/>'
                    f'<text x="{px + CELL / 2}" y="{py + CELL / 2 + 5}" '
                    f'class="sym" fill="{_text_color_for(b["color"])}">{b["symbol"]}</text>'
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
<h2>作り方（1段ずつ）</h2>
<p class="hint">レゴの説明書と同じで、下の段から順番に置いていく。数字はマスの座標。</p>
<div class="layers">{"".join(layer_cards)}</div>

<footer>Minecraft Education 用レイヤー設計図 ・ 上から見た図（上=北） ・
たいまつ・ドアなどの置き物は最後に設置するときれいに作れます。</footer>
</main>
"""
