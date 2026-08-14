#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Python版 render_html() と JS版 renderer.js の出力が「同じ図」かを機械的に検証する。

やっていること:
  1. Python: designs/<name>.py → blueprint.render_html()
  2. JS    : gemini/designs/<name>.js → node render_js.js <name> --no-banner
  3. どちらのHTMLからも「図としての中身」を抜き出して正規化JSONにし、突き合わせる
       - 作品名 / サイズ(横×奥行き) / 段数 / ブロック総数
       - 材料リスト（並び順・色・記号・日本語名・個数）
       - 完成イメージ（アイソメ図）の全ポリゴン（座標と3面の色）
       - 段ごとのレイヤー図（各マスの位置・色・記号、下段目印の点、座標ラベル、注記）
       - つくるときのポイント（notes）
  4. おまけ: HTML文字列そのものの完全一致も確認する

使い方: python3 gemini/compare.py
"""

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from blueprint import render_html          # noqa: E402
from designs import DESIGNS                # noqa: E402

CELL = 26
MARGIN = 22


# ------------------------------------------------------------------ 抽出

def _text(s):
    """タグを落として素のテキストにする。"""
    return re.sub(r"<[^>]+>", "", s).strip()


def extract(html):
    doc = {}
    doc["title"] = re.search(r"<title>(.*?)</title>", html, re.S).group(1)
    doc["h1"] = re.search(r"<h1>(.*?)</h1>", html, re.S).group(1)
    m = re.search(r'<p class="desc">(.*?)</p>', html, re.S)
    doc["desc"] = m.group(1) if m else None

    stats = re.findall(r"<div><b>(.*?)</b> <span>(.*?)</span></div>", html, re.S)
    doc["stats"] = stats

    # --- 材料リスト ---
    doc["bom"] = re.findall(
        r'<tr><td><span class="swatch" style="background:(#[0-9A-Fa-f]{6})"></span>'
        r"(.*?)"
        r'<span style="color:var\(--muted\)">（記号: (.*?)）</span></td>'
        r'<td class="n">(\d+) 個</td></tr>',
        html,
    )

    # --- つくるときのポイント ---
    m = re.search(r'<ol class="notes">(.*?)</ol>', html, re.S)
    doc["notes"] = re.findall(r"<li>(.*?)</li>", m.group(1), re.S) if m else []

    # --- 完成イメージ（アイソメ図） ---
    iso = re.search(r'<div class="panel iso-panel">(.*?)</div>', html, re.S).group(1)
    m = re.search(r'viewBox="([^"]+)"', iso)
    doc["iso_viewbox"] = m.group(1) if m else None
    m = re.search(r'style="max-width:(\d+)px"', iso)
    doc["iso_maxwidth"] = m.group(1) if m else None
    polys = re.findall(
        r'<polygon points="([^"]+)" fill="(#[0-9a-f]{6})"(?:\s*stroke="(#[0-9a-f]{6})")?',
        iso,
    )
    # 座標は float 表記ゆれを吸収して数値で比較する
    doc["iso_polys"] = [
        ([[float(v) for v in pt.split(",")] for pt in pts.split(" ")], fill, stroke)
        for pts, fill, stroke in polys
    ]

    # --- 段ごとのレイヤー図 ---
    layers = []
    for card in html.split('<div class="layer-card">')[1:]:
        card = card.split('<div class="layer-card">')[0]
        no = re.search(r'<span class="layer-no">(\d+)段目</span>', card).group(1)
        cnt = re.search(r'<span class="layer-count">(.*?)</span>', card, re.S).group(1)
        svg = re.search(r'<div class="grid-wrap">(.*?)</div>', card, re.S).group(1)
        vb = re.search(r'viewBox="([^"]+)"', svg).group(1)
        width = re.search(r'style="width:(\d+)px', svg).group(1)
        aria = re.search(r'aria-label="([^"]+)"', svg).group(1)

        # 置かれたブロックのマス
        cells = {}
        for px, py, fill, sym in re.findall(
            r'<rect x="(\d+)" y="(\d+)" width="26" height="26" '
            r'fill="(#[0-9A-Fa-f]{6})" stroke="#[0-9a-f]{6}"/>'
            r'<text x="[\d.]+" y="[\d.]+" class="sym" fill="(?:#[0-9a-f]{6})">(.*?)</text>',
            svg,
        ):
            col = (int(px) - MARGIN) // CELL
            row = (int(py) - MARGIN) // CELL
            cells[f"{col},{row}"] = [fill, sym]

        # 下の段の目印（ゴースト点）
        ghosts = sorted(
            f"{(float(cx) - MARGIN - CELL / 2) / CELL:.0f},"
            f"{(float(cy) - MARGIN - CELL / 2) / CELL:.0f}"
            for cx, cy in re.findall(
                r'<circle cx="([\d.]+)" cy="([\d.]+)" r="2\.2" class="ghost"/>', svg
            )
        )

        # 座標の目盛りラベル
        axes = re.findall(r'class="ax">(-?\d+)</text>', svg)

        cm = re.search(r'<div class="compass">(.*?)</div>', card, re.S)
        compass = _text(cm.group(1)) if cm else ""
        m = re.search(r'<div class="layer-note">(.*?)</div>', card, re.S)
        note = _text(m.group(1)) if m else None

        layers.append({
            "no": no, "aria": aria, "count_text": cnt, "viewbox": vb, "width": width,
            "cells": cells, "ghosts": ghosts, "axes": axes,
            "compass": compass, "note": note,
        })
    doc["layers"] = layers
    return doc


# ------------------------------------------------------------------ 比較

def deep_diff(a, b, path="", out=None):
    if out is None:
        out = []
    if type(a) is not type(b):
        out.append(f"{path}: 型ちがい {type(a).__name__} vs {type(b).__name__}")
    elif isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{path}.{k}: Python版に無い")
            elif k not in b:
                out.append(f"{path}.{k}: JS版に無い")
            else:
                deep_diff(a[k], b[k], f"{path}.{k}", out)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(f"{path}: 個数ちがい {len(a)} vs {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            deep_diff(x, y, f"{path}[{i}]", out)
    elif a != b:
        out.append(f"{path}: {a!r} vs {b!r}")
    return out


def strip_banner(js_html):
    """検品バナー（JS版だけの追加要素）を取り除く。"""
    js_html = re.sub(r"<style>\n\.qc .*?</style>\n", "", js_html, flags=re.S)
    js_html = re.sub(r'<div class="qc.*?</div>\n(?=<header)', "", js_html, flags=re.S)
    return js_html


def run(name):
    print(f"\n{'=' * 72}\n■ {name}\n{'=' * 72}")
    py_html = render_html(DESIGNS[name]())
    js_html = subprocess.run(
        ["node", str(HERE / "render_js.js"), name, "--no-banner"],
        capture_output=True, text=True, check=True,
    ).stdout

    out = HERE / "_out"
    out.mkdir(exist_ok=True)
    (out / f"{name}.py.html").write_text(py_html, encoding="utf-8")
    (out / f"{name}.js.html").write_text(js_html, encoding="utf-8")

    def circuit(h):
        i = h.find("<h2>レッドストーン回路のくわしい図</h2>")
        if i < 0:
            return None
        return h[i:h.find("<h2>作り方（1段ずつ）</h2>", i)]

    cpy, cjs = circuit(py_html), circuit(js_html)
    if cpy is None and cjs is None:
        print("  ―  レッドストーン回路なし（詳細図は出さない）")
    elif cpy == cjs:
        print(f"  ✅ レッドストーン回路のくわしい図 {len(cpy)}文字・完全一致")
    else:
        print("  ✗ レッドストーン回路のくわしい図が Python版とJS版で違う")
        return False

    a, b = extract(py_html), extract(js_html)

    checks = []
    checks.append(("作品名・説明・見出し",
                   [a["title"], a["h1"], a["desc"]] == [b["title"], b["h1"], b["desc"]]))
    checks.append((f"サイズ/段数/ブロック総数  {'・'.join(x[0] for x in a['stats'])}",
                   a["stats"] == b["stats"]))
    checks.append((f"材料リスト {len(a['bom'])}種類・"
                   f"合計{sum(int(r[3]) for r in a['bom'])}個",
                   a["bom"] == b["bom"]))
    checks.append((f"完成イメージ ポリゴン{len(a['iso_polys'])}枚・viewBox",
                   a["iso_polys"] == b["iso_polys"]
                   and a["iso_viewbox"] == b["iso_viewbox"]
                   and a["iso_maxwidth"] == b["iso_maxwidth"]))
    checks.append((f"つくるときのポイント {len(a['notes'])}項目",
                   a["notes"] == b["notes"]))
    n_cells = sum(len(l["cells"]) for l in a["layers"])
    checks.append((f"レイヤー図 {len(a['layers'])}段・マス配置 合計{n_cells}マス",
                   a["layers"] == b["layers"]))

    for label, ok in checks:
        print(f"  {'✅' if ok else '❌'} {label}")

    diffs = deep_diff(a, b, "doc")
    if diffs:
        print(f"\n  --- ちがい {len(diffs)}件（先頭20件） ---")
        for d in diffs[:20]:
            print("   ", d)
    else:
        print("  ── 図の内容は完全一致 ──")

    same_text = py_html == strip_banner(js_html)
    print(f"  {'✅' if same_text else '△'} HTML文字列そのものの完全一致: "
          f"{'一致' if same_text else '不一致（図の内容は上の判定を参照）'}")
    if not same_text:
        pl, jl = py_html.splitlines(), strip_banner(js_html).splitlines()
        for i, (x, y) in enumerate(zip(pl, jl)):
            if x != y:
                print(f"    最初のちがい {i + 1}行目:\n      py: {x[:160]}\n      js: {y[:160]}")
                break
        else:
            print(f"    行数のちがい: py={len(pl)} js={len(jl)}")

    # 検品結果も出しておく（JS版のみの機能）
    v = json.loads(subprocess.run(
        ["node", str(HERE / "render_js.js"), name, "--validate"],
        capture_output=True, text=True, check=True,
    ).stdout)
    print(f"\n  [自動検品] {'✅ 合格' if v['ok'] else '⚠ ' + str(len(v['issues'])) + '件の問題'}")
    for it in v["issues"]:
        print(f"    - 【{'要修正' if it['level'] == 'error' else '確認'}】{it['title']}")
        print(f"      {it['detail']}")
        print(f"      直し方: {it['fix']}")

    return not diffs


def main():
    names = sys.argv[1:] or ["house", "trap_pit"]
    ok = all([run(n) for n in names])
    print(f"\n{'=' * 72}")
    print("結果:", "全設計で Python版とJS版の図が完全一致 ✅" if ok else "ちがいあり ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
