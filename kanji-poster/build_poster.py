# -*- coding: utf-8 -*-
"""小学2年生配当漢字160字 A1ポスター生成スクリプト。

data/final.json  … [{kanji, strokes, on:[[読み,段階]], kun:[[読み,段階]]}, ...] 配当表順
data/strokes.json … {kanji: {paths:[d..], nums:[[x,y,"n"]..]}}  KanjiVG由来
出力: poster.html (594mm x 841mm, A1縦)
"""
import json, html

BASE = "/tmp/claude-0/-home-user-gmail-manager/eb1b9397-4683-592b-9396-426fb1eb64d7/scratchpad"
rows = json.load(open(f"{BASE}/data/final.json"))
strokes = json.load(open(f"{BASE}/data/strokes.json"))

INK = "#3a3a3a"
RED = "#e8535e"

def guide(size):
    """原稿用紙風マス目（点線の十字ガイド）"""
    return (f'<line x1="{size/2}" y1="3" x2="{size/2}" y2="{size-3}" class="gl"/>'
            f'<line x1="3" y1="{size/2}" x2="{size-3}" y2="{size/2}" class="gl"/>')

def stroke_svg(k, cls="sod"):
    """番号付き書き順図SVG"""
    d = strokes[k]
    parts = [f'<svg class="{cls}" viewBox="0 0 109 109">']
    parts.append('<rect x="1" y="1" width="107" height="107" rx="8" class="sqbg"/>')
    parts.append(guide(109))
    for p in d["paths"]:
        parts.append(f'<path d="{p}" class="st"/>')
    for x, y, n in d["nums"]:
        parts.append(f'<text x="{x}" y="{y}" class="sn">{n}</text>')
    parts.append("</svg>")
    return "".join(parts)

def fmt_reading(r, level, kind):
    """読み1件を整形。送り仮名(.)は細字、｢中/高｣は（）で淡色。"""
    if "." in r:
        stem, okuri = r.split(".", 1)
        body = f'{html.escape(stem)}<span class="ok">{html.escape(okuri)}</span>'
    else:
        body = html.escape(r)
    if level in ("中", "高"):
        return f'<span class="rd jhs">（{body}）</span>'
    return f'<span class="rd">{body}</span>'

def reading_line(items, kind):
    if not items:
        return '<span class="none">―</span>'
    return '<span class="rsep">・</span>'.join(fmt_reading(r, lv, kind) for r, lv in items)

import os
_OVR = {}
if os.path.exists(f"{BASE}/data/size_overrides.json"):
    _OVR = json.load(open(f"{BASE}/data/size_overrides.json"))

def size_class(row):
    """読みの分量に応じて縮小クラスを付ける（実測オーバーライド優先）"""
    if row["kanji"] in _OVR:
        return " " + _OVR[row["kanji"]]
    n = sum(len(r) + 1 for r, _ in row["on"]) + sum(len(r) + 1 for r, _ in row["kun"])
    if n >= 34: return " xs"
    if n >= 24: return " sm"
    return ""

cells = []
for i, r in enumerate(rows, 1):
    k = r["kanji"]
    cells.append(f'''<div class="cell{size_class(r)}">
  <div class="idx">{i}</div>
  <div class="chead">
    <svg class="big" viewBox="0 0 100 100"><rect x="1" y="1" width="98" height="98" rx="7" class="sqbg"/>{guide(100)}<text x="50" y="50" class="bigk">{k}</text></svg>
    <div class="sowrap">{stroke_svg(k)}<div class="scount">{r["strokes"]}かく</div></div>
  </div>
  <div class="reads">
    <div class="rline"><span class="chip con">オン</span><span class="rtx on">{reading_line(r["on"], "on")}</span></div>
    <div class="rline"><span class="chip ckun">くん</span><span class="rtx kun">{reading_line(r["kun"], "kun")}</span></div>
  </div>
</div>''')

# 凡例用ミニセル（強: 音2つ・訓に送り仮名・中学読みあり）
sample = next(r for r in rows if r["kanji"] == "強")
legend_cell = f'''<div class="cell lg">
  <div class="chead">
    <svg class="big" viewBox="0 0 100 100"><rect x="1" y="1" width="98" height="98" rx="7" class="sqbg"/>{guide(100)}<text x="50" y="50" class="bigk">強</text></svg>
    <div class="sowrap">{stroke_svg("強")}<div class="scount">{sample["strokes"]}かく</div></div>
  </div>
  <div class="reads">
    <div class="rline"><span class="chip con">オン</span><span class="rtx on">{reading_line(sample["on"], "on")}</span></div>
    <div class="rline"><span class="chip ckun">くん</span><span class="rtx kun">{reading_line(sample["kun"], "kun")}</span></div>
  </div>
</div>'''

html_doc = f'''<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<style>
@font-face {{ font-family:"Klee One"; src:url("fonts/KleeOne-Regular.ttf"); font-weight:400; }}
@font-face {{ font-family:"Klee One"; src:url("fonts/KleeOne-SemiBold.ttf"); font-weight:600; }}
@font-face {{ font-family:"Zen Maru"; src:url("fonts/ZenMaruGothic-Medium.ttf"); font-weight:500; }}
@font-face {{ font-family:"Zen Maru"; src:url("fonts/ZenMaruGothic-Bold.ttf"); font-weight:700; }}
@font-face {{ font-family:"Zen Maru"; src:url("fonts/ZenMaruGothic-Black.ttf"); font-weight:900; }}
@page {{ size:594mm 841mm; margin:0; }}
* {{ margin:0; padding:0; box-sizing:border-box; }}
html,body {{ width:594mm; height:841mm; overflow:hidden; }}
body {{ background:#fdf6e6; font-family:"Zen Maru","Klee One",sans-serif; color:#3a3a3a;
       -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
.page {{ width:594mm; height:840.2mm; padding:10mm 12mm 8mm; display:flex; flex-direction:column;
         page-break-after:avoid; page-break-inside:avoid; }}

/* ---------- ヘッダー ---------- */
.header {{ display:flex; align-items:stretch; gap:8mm; margin-bottom:5.5mm; }}
.titlebox {{ flex:1; }}
.title {{ font-weight:900; font-size:19mm; letter-spacing:0.8mm; line-height:1.08; color:#2f4358; }}
.title .num {{ color:{RED}; font-size:23mm; }}
.title .ji {{ font-size:14mm; }}
.subtitle {{ margin-top:2.6mm; font-weight:700; font-size:6.2mm; color:#5b7186; letter-spacing:0.5mm; }}
.subtitle .tag {{ display:inline-block; background:#fff; border:0.5mm solid #d8c9a8; border-radius:10mm;
                  padding:0.8mm 4mm; margin-right:2.5mm; }}
.legend {{ width:150mm; background:#fff; border:0.6mm solid #e5d7b4; border-radius:4mm;
           padding:3.5mm 4mm 3mm; display:flex; gap:4mm; }}
.legend .cell.lg {{ width:56mm; flex:none; box-shadow:none; border:0.45mm solid #e8dcc0; }}
.lgtitle {{ font-weight:900; font-size:5.2mm; color:#2f4358; margin-bottom:1.6mm; }}
.lgtitle span {{ background:#ffe9a8; border-radius:2mm; padding:0 1.6mm; }}
.lgnotes {{ flex:1; font-size:3.55mm; font-weight:500; line-height:1.62; color:#4a4a4a; }}
.lgnotes b {{ font-weight:700; }}
.lgnotes .r {{ color:{RED}; font-weight:700; }}
.lgnotes .b {{ color:#3b76c0; font-weight:700; }}
.lgnotes .g {{ color:#3e9b57; font-weight:700; }}
.lgnotes .gy {{ color:#8a8a8a; }}

/* ---------- グリッド ---------- */
.grid {{ flex:1; min-height:0; display:grid; grid-template-columns:repeat(10,1fr);
         grid-template-rows:repeat(16,minmax(0,1fr)); gap:2.2mm; }}
.cell {{ position:relative; background:#fff; border:0.45mm solid #e8dcc0; border-radius:2.6mm;
         padding:1.6mm 1.8mm 1.4mm; display:flex; flex-direction:column; overflow:hidden; }}
.idx {{ position:absolute; top:1mm; left:1.6mm; font-size:2.5mm; font-weight:700; color:#c9b98f; }}
.chead {{ display:flex; justify-content:center; align-items:flex-start; gap:1.8mm; }}
.big {{ width:24.5mm; height:24.5mm; margin-top:0.4mm; }}
.bigk {{ font-family:"Klee One"; font-weight:600; font-size:76px; fill:#222;
         text-anchor:middle; dominant-baseline:central; }}
.sqbg {{ fill:#fbf8ef; stroke:#e3d5b2; stroke-width:1.5; }}
.gl {{ stroke:#dccf9f; stroke-width:1.1; stroke-dasharray:4 4; }}
.sowrap {{ display:flex; flex-direction:column; align-items:center; }}
.sod {{ width:21mm; height:21mm; }}
.st {{ fill:none; stroke:{INK}; stroke-width:3.4; stroke-linecap:round; stroke-linejoin:round; }}
.sn {{ font-family:"Zen Maru"; font-weight:900; font-size:10.5px; fill:{RED};
       stroke:#ffffff; stroke-width:2.6px; paint-order:stroke fill; }}
.scount {{ margin-top:0.5mm; font-size:2.9mm; font-weight:700; color:#7a6b47;
           background:#f5edd8; border-radius:2mm; padding:0 1.8mm; line-height:1.5; }}

/* ---------- 読み ---------- */
.reads {{ margin-top:auto; padding-top:1.1mm; display:flex; flex-direction:column; gap:0.9mm; }}
.rline {{ display:flex; align-items:baseline; gap:1.4mm; }}
.chip {{ flex:none; font-size:2.7mm; font-weight:900; color:#fff; border-radius:1.6mm;
         padding:0.35mm 1.3mm 0.25mm; line-height:1.35; align-self:flex-start; margin-top:0.45mm; }}
.con {{ background:#3b76c0; }}
.ckun {{ background:#3e9b57; }}
.rtx {{ font-family:"Klee One"; font-weight:600; font-size:3.7mm; line-height:1.38; letter-spacing:0.1mm; }}
.rtx.on {{ color:#2c5d9e; }}
.rtx.kun {{ color:#2e7a44; }}
.ok {{ font-weight:400; color:#999; font-size:88%; }}
.jhs {{ color:#a0a0a0; }}
.jhs .ok {{ color:#b8b8b8; }}
.rd {{ white-space:nowrap; }}
.rsep {{ color:#c8c8c8; font-weight:400; margin:0 0.1mm; }}
.none {{ color:#c8c8c8; }}
.cell.sm .rtx {{ font-size:3.2mm; }}
.cell.xs .rtx {{ font-size:2.75mm; letter-spacing:0; }}
.cell.xxs .rtx {{ font-size:2.45mm; letter-spacing:0; line-height:1.24; }}
.cell.xxs .reads {{ gap:0.5mm; padding-top:0.7mm; }}
.cell.sm .big, .cell.xs .big, .cell.xxs .big {{ width:23.4mm; height:23.4mm; }}
.cell.sm .sod, .cell.xs .sod, .cell.xxs .sod {{ width:20mm; height:20mm; }}
.cell.lg .rtx {{ font-size:3.4mm; }}

/* ---------- フッター ---------- */
.footer {{ margin-top:4mm; display:flex; justify-content:space-between; align-items:flex-end;
           font-size:3.1mm; font-weight:500; color:#8a7c5c; }}
.footer .left b {{ font-weight:700; }}
</style></head>
<body><div class="page">
  <div class="header">
    <div class="titlebox">
      <div class="title">小学<span class="num">2</span>年生でならう<br>かん字 <span class="num">160</span><span class="ji">字</span></div>
      <div class="subtitle"><span class="tag">かきじゅん</span><span class="tag">おんよみ</span><span class="tag">くんよみ</span>ぜんぶ のってるよ！</div>
    </div>
    <div class="legend">
      {legend_cell}
      <div class="lgn">
        <div class="lgtitle"><span>この ひょうの みかた</span></div>
        <div class="lgnotes">
          <span class="r">あかい すうじ</span>は かく じゅんばん（かきじゅん）だよ。<br>
          <b class="b">オン</b>＝おんよみ（カタカナ）、<b class="g">くん</b>＝くんよみ（ひらがな）。<br>
          <span class="gy">ほそい じ</span>は おくりがな。<span class="gy">（　）の よみかた</span>は 中学校や 高校で ならうよ。<br>
          「◯かく」は その かん字を かく かいすう（<b>画すう</b>）だよ。
        </div>
      </div>
    </div>
  </div>
  <div class="grid">
{"".join(cells)}
  </div>
  <div class="footer">
    <div class="left"><b>じゅんばん</b>：おんよみの「あいうえお」じゅん（文部科学省 学年別漢字配当表による）</div>
    <div class="right">字形・書き順データ：KanjiVG（© Ulrich Apel／CC BY-SA 3.0）｜読み：常用漢字表（平成22年内閣告示第2号）準拠</div>
  </div>
</div></body></html>'''

open(f"{BASE}/poster.html", "w").write(html_doc)
print("poster.html written,", len(html_doc)//1024, "KB")
