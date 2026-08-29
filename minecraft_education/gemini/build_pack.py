#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""renderer.js を正本として PROMPT.md と viewer.html を生成する。

renderer.js を直したら必ずこれを実行すること。
3者（renderer.js / PROMPT.md の埋め込みコード / viewer.html のインラインコード）が
ズレると、設計図の品質が静かに劣化するため、手書きせず必ずここから生成する。

    python3 build_pack.py
"""

import re
import sys
from pathlib import Path

HERE = Path(__file__).parent


def compact_js(src):
    """コメントと余分な空白を落とす（文字列・正規表現リテラルは壊さない）。

    JSを1文字ずつ走査し、文字列/テンプレート/正規表現の中にいるかを追跡しながら
    コメントだけを除去する。行頭インデントと空行も落とす。
    """
    out = []
    i, n = 0, len(src)
    # 直前の意味のあるトークンが値（＝次の / は除算）かどうか
    prev_significant = ""
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""

        # 行コメント
        if c == "/" and nxt == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        # ブロックコメント
        if c == "/" and nxt == "*":
            i += 2
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                i += 1
            i += 2
            continue
        # 文字列・テンプレートリテラル
        if c in "\"'`":
            quote = c
            out.append(c)
            i += 1
            while i < n:
                if src[i] == "\\":
                    out.append(src[i : i + 2])
                    i += 2
                    continue
                out.append(src[i])
                if src[i] == quote:
                    i += 1
                    break
                i += 1
            prev_significant = quote
            continue
        # 正規表現リテラル（直前が演算子・記号なら正規表現とみなす）
        if c == "/" and prev_significant not in (")", "]", "}") and not (
            prev_significant.isalnum() or prev_significant == "_"
        ):
            out.append(c)
            i += 1
            in_class = False
            while i < n:
                if src[i] == "\\":
                    out.append(src[i : i + 2])
                    i += 2
                    continue
                if src[i] == "[":
                    in_class = True
                elif src[i] == "]":
                    in_class = False
                out.append(src[i])
                if src[i] == "/" and not in_class:
                    i += 1
                    break
                i += 1
            prev_significant = "/"
            continue

        out.append(c)
        if not c.isspace():
            prev_significant = c
        i += 1

    text = "".join(out)
    # 行頭インデントを削り、空行を落とす
    lines = [ln.strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def read(name):
    return (HERE / name).read_text(encoding="utf-8")


def escape_for_html(js):
    """HTMLの<script>内に安全に埋め込めるようにする。

    JSのコメントや文字列に `</script>` が含まれていると、ブラウザがそこで
    スクリプトを終了し、以降のコードがページ本文として表示されてしまう。
    JS上は `<\\/script>` と書いても意味が同じなのでエスケープする。
    """
    return re.sub(r"</(script)", r"<\\/\1", js, flags=re.I)


def palette_table():
    """renderer.js の BLOCKS から、プロンプトに載せるパレット表を作る。

    手書きしないのは、パレットとプロンプトがズレると
    Gemini が存在しないブロックを使い、設計が壊れるため。
    """
    src = read("renderer.js")
    body = re.search(r"var BLOCKS = \{(.*?)\n  \};", src, re.S)
    if not body:
        raise SystemExit("renderer.js から BLOCKS を読み取れませんでした")
    rows = []
    for m in re.finditer(
        r'"?(\w+)"?:\s*\{(.*?)\}', body.group(1).replace("\n", " "), re.S
    ):
        key, attrs = m.group(1), m.group(2)
        name = re.search(r'name_ja:\s*"([^"]*)"', attrs)
        sym = re.search(r'symbol:\s*"([^"]*)"', attrs)
        marker = "marker: true" in attrs or "marker:true" in attrs
        if not (name and sym):
            continue
        rows.append(
            f"| `{key}` | {name.group(1)} | {sym.group(1)} | "
            + ("**置き物（向き注意）**" if marker else "")
            + " |"
        )
    if len(rows) < 10:
        raise SystemExit(f"パレット抽出に失敗しました（{len(rows)}件しか取れていません）")
    return "\n".join(rows), len(rows)


def agent_palette_table():
    """renderer.js の BLOCKS から、エージェント建築プロンプト用の定数表を作る。

    Geminiに書かせるのは MakeCode 定数（GRASS 等）なので、その一覧を載せる。
    置き物（marker）は向きが要るためエージェントでは置けず、その旨を印にする。
    """
    src = read("renderer.js")
    body = re.search(r"var BLOCKS = \{(.*?)\n  \};", src, re.S)
    if not body:
        raise SystemExit("renderer.js から BLOCKS を読み取れませんでした")
    rows = []
    for m in re.finditer(
        r'"?(\w+)"?:\s*\{(.*?)\}', body.group(1).replace("\n", " "), re.S
    ):
        attrs = m.group(2)
        name = re.search(r'name_ja:\s*"([^"]*)"', attrs)
        mc = re.search(r'makecode:\s*"([^"]*)"', attrs)
        marker = "marker: true" in attrs or "marker:true" in attrs
        if not (name and mc):
            continue
        rows.append(
            f"| `{mc.group(1)}` | {name.group(1)} | "
            + ("**置き物（LAYERS禁止・EXTRASで置く）**" if marker else "")
            + " |"
        )
    if len(rows) < 10:
        raise SystemExit(f"パレット抽出に失敗しました（{len(rows)}件しか取れていません）")
    return "\n".join(rows), len(rows)


# EXTRAS表で上下向きの行を出すブロックと、その許される向き。
# palette の updown フラグより厳しい実機準拠（例: ホッパーに「上」は無い、
# はしごは横4方向のみ）。表はGeminiが一字一句コピーする正本なので、
# ゲームに存在しない状態値を載せない。
_EXTRAS_UPDOWN = {
    "sticky_piston": ("down", "up"),
    "dispenser": ("down", "up"),
    "dropper": ("down", "up"),
    "observer": ("down", "up"),
    "hopper": ("down",),
}

_DIR_JA = {"north": "北向き", "south": "南向き", "east": "東向き",
           "west": "西向き", "down": "下向き", "up": "上向き"}


def extras_table():
    """置き物・向き付きブロック用の「EXTRASに書く文字列」表を作る。

    文字列の本体（bedrock_id + ブロック状態）は blueprint/blockstate.py の
    state_suffix() で組む。ここは commands.txt と同じ経路で、Mojang公式データと
    tools/verify_block_ids.py が突き合わせている。手書きすると必ず間違えるので、
    プロンプトに載る文字列はすべてここから生成する。
    """
    sys.path.insert(0, str(HERE.parent))
    from blueprint.blockstate import STATE_RULES, state_suffix  # noqa: E402
    from blueprint.palette import BLOCKS  # noqa: E402

    rows = []
    for key, b in BLOCKS.items():
        # 置き物・向きの決まるブロック（階段など）・液体だけが EXTRAS の対象
        if not (b.get("marker") or key in STATE_RULES or key in ("water", "lava")):
            continue
        note = "（あふれ注意・囲いの中だけ）" if key in ("water", "lava") else ""
        if key in STATE_RULES:
            facings = ["north", "south", "east", "west"]
            facings += list(_EXTRAS_UPDOWN.get(key, ()))
            for f in facings:
                suf = state_suffix(key, f)
                if not suf:
                    continue
                rows.append(f"| {b['name_ja']} | {_DIR_JA[f]} | `{b['bedrock_id']}{suf}` |")
        else:
            rows.append(f"| {b['name_ja']}{note} | ー | `{b['bedrock_id']}` |")
    if len(rows) < 20:
        raise SystemExit(f"EXTRAS表の生成に失敗しました（{len(rows)}行しかありません）")
    return "\n".join(rows), len(rows)


def main():
    renderer = read("renderer.js")
    compact = compact_js(renderer)
    table, count = palette_table()
    agent_table, agent_count = agent_palette_table()

    prompt = (
        read("templates/PROMPT.template.md")
        .replace("<<PALETTE>>", table)
        .replace("<<RENDERER>>", escape_for_html(compact))
    )
    viewer_tpl = read("templates/viewer.template.html")
    viewer = viewer_tpl.replace("<<RENDERER>>", escape_for_html(renderer))

    # 自己検査: 埋め込みで </script> が増えていたら、そこでスクリプトが途切れて
    # 以降のコードがページ本文として表示されてしまう（実際に起きた不具合）。
    want = len(re.findall(r"</script\s*>", viewer_tpl, re.I))
    got = len(re.findall(r"</script\s*>", viewer, re.I))
    if got != want:
        raise SystemExit(
            f"viewer.html の </script> が {want} 個のはずが {got} 個あります。"
            "renderer.js 内の </script> がエスケープされていません。"
        )

    ex_table, ex_count = extras_table()
    agent_prompt = (
        read("templates/AGENT_PROMPT.template.md")
        .replace("<<AGENT_PALETTE>>", agent_table)
        .replace("<<EXTRAS_TABLE>>", ex_table)
    )
    if agent_count != count:
        raise SystemExit(
            f"パレット表の件数が食い違っています（設計図用 {count} / エージェント用 {agent_count}）"
        )

    (HERE / "PROMPT.md").write_text(prompt, encoding="utf-8")
    (HERE / "viewer.html").write_text(viewer, encoding="utf-8")
    (HERE / "AGENT_PROMPT.md").write_text(agent_prompt, encoding="utf-8")

    kb = lambda s: f"{len(s.encode('utf-8')) / 1024:.1f} KB"
    print(f"パレット {count} 種類を renderer.js から取り込みました")
    print(f"PROMPT.md    {kb(prompt)}\t… Geminiに貼り付けるプロンプト")
    print(f"viewer.html  {kb(viewer)}\t… 単体で動く設計図ビューア")
    print(f"AGENT_PROMPT.md {kb(agent_prompt)}\t… エージェント建築コード用プロンプト"
          f"（EXTRAS表 {ex_count} 行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
