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
        approx = "makecode_approx: true" in attrs
        if not (name and mc):
            continue
        rows.append(
            f"| `{mc.group(1)}` | {name.group(1)}"
            + ("（MakeCodeに無いため近い見た目で代用）" if approx else "")
            + " | "
            + ("**置き物（LAYERS禁止・EXTRASで置く）**" if marker else "")
            + " |"
        )
    if len(rows) < 10:
        raise SystemExit(f"パレット抽出に失敗しました（{len(rows)}件しか取れていません）")
    return "\n".join(rows), len(rows)


# 許される向きは blockstate.py の AUX_RULES が正本（実機準拠: ホッパーに「上」は
# 無い、はしご・チェストは横4方向のみ）。表はGeminiが一字一句コピーするので、
# ゲームに存在しない値を載せない。
_DIR_JA = {"north": "北向き", "south": "南向き", "east": "東向き",
           "west": "西向き", "down": "下向き", "up": "上向き"}


def extras_table():
    """置き物・向き付きブロック用の「EXTRASに書く文字列」表を作る。

    向きは blueprint/blockstate.py の command_suffix()（データ値方式）で組む。
    Education のコマンドはブロック状態構文 ["~"=n] を構文エラーにするため
    （1.21.133 実機確認）、旧世代のデータ値を使う。対応表の出所は blockstate.py 参照。
    手書きすると必ず間違えるので、プロンプトに載る文字列はすべてここから生成する。
    """
    sys.path.insert(0, str(HERE.parent))
    from blueprint.blockstate import AUX_RULES, command_suffix  # noqa: E402
    from blueprint.palette import BLOCKS  # noqa: E402

    rows = []
    for key, b in BLOCKS.items():
        # 置き物・向きの決まるブロック（階段など）・液体だけが EXTRAS の対象
        if not (b.get("marker") or key in AUX_RULES or key in ("water", "lava")):
            continue
        note = "（あふれ注意・囲いの中だけ）" if key in ("water", "lava") else ""
        if key in AUX_RULES:
            for f in ("north", "south", "east", "west", "down", "up"):
                suf = command_suffix(key, f)
                if not suf:
                    continue
                rows.append(f"| {b['name_ja']} | {_DIR_JA[f]} | `{b['bedrock_id']}{suf}` |")
        else:
            rows.append(f"| {b['name_ja']}{note} | ー | `{b['bedrock_id']}` |")
        if key == "door":
            # ドアは上下2マスで1つ。データ値8が上半分（upper_block_bit）。
            rows.append(f"| {b['name_ja']}の**上半分** | ー | `{b['bedrock_id']} 8` |")
    if len(rows) < 20:
        raise SystemExit(f"EXTRAS表の生成に失敗しました（{len(rows)}行しかありません）")
    return "\n".join(rows), len(rows)


def check_files():
    """実機でしか確認できないことを一発で確かめるチェックファイル2つを作る。

    1. check_makecode.txt … MakeCode定数60種が実在するか（未検証の最大の穴）。
       貼ってエラーが出た行の定数名が間違い。実行すると全ブロックが並ぶ
    2. check_muki.txt … 向きのデータ値が実機の向きと合っているか。
       貼って muki と打つと北/南/東/西の順で並ぶので、向きを目で確かめる
    """
    sys.path.insert(0, str(HERE.parent))
    from blueprint.blockstate import AUX_RULES, command_suffix  # noqa: E402
    from blueprint.palette import BLOCKS  # noqa: E402

    mc = [
        "# パレット確認用コード（MakeCode Python） — 1回だけ実行して確かめる",
        "# 目的: このツールが使うMakeCode定数60種が、実機のCode Builderに存在するか。",
        "# 使い方:",
        "#  1. Cキー → Code Builder → MakeCode(Python) に全部貼る",
        "#  2. エラーになった行があれば、その行の定数名がこの環境に無い",
        "#     → エラー行の写真かエラー名を報告してください。パレットを直します",
        "#  3. 実行できたら広い平地でチャットに check → ブロックが東向きに並ぶ",
        "#     （i番目 = プレイヤーの iマス東・2マス南。行のコメントと見比べる）",
        "# 溶岩と水は流れるので、地面の中（1段下・8マス南）に置いて確認します。",
        "",
        "def check():",
    ]
    i = 0
    for key, b in BLOCKS.items():
        if key in ("lava", "water"):
            mc.append(f"    blocks.place({b['makecode']}, pos({i}, -1, 8))"
                      f"  # {i} {b['name_ja']}（地面の中）")
        else:
            mc.append(f"    blocks.place({b['makecode']}, pos({i}, 0, 2))"
                      f"  # {i} {b['name_ja']}")
        i += 1
    mc += ["", 'player.on_chat("check", check)', ""]

    dir_col = {"north": 0, "south": 2, "east": 4, "west": 6, "down": 8, "up": 10}
    # はしごは支えが無いと壊れるので、向きの反対側に石を先に置く
    support = {"north": (0, 1), "south": (0, -1), "east": (-1, 0), "west": (1, 0)}
    cmd = [
        "# 向き（データ値）確認用コード（MakeCode Python） — 1回だけ実行して確かめる",
        "# 目的: ブロック名の後ろの数字（データ値）が、実機で正しい向きになるか。",
        "# 使い方:",
        "#  1. Cキー → Code Builder → MakeCode(Python) に全部貼って実行",
        "#  2. 広い平地に立って、チャットに muki と打つ（動かずに待つ）",
        "#  3. 各ブロックが 北/南/東/西（/下/上）の順で東向きに並ぶ。",
        "#     設計図の矢印と同じ向きになっていればOK",
        "#     （ピストンは押す面、ホッパーは注ぎ口、階段は高い側で確認）",
        "# 列の意味: 0マス東=北向き / 2=南向き / 4=東向き / 6=西向き / 8=下向き / 10=上向き",
        "#",
        "# 【答え合わせは3問だけ】装置が自動で動くので、色を教えてください:",
        "#  - 青い羊毛の列が「北」の目印",
        "#  問1: 手前(z16あたり)の1台のピストンは、青い羊毛の方へ伸びていますか？",
        "#  問2: 奥(z36)の左の2台のうち、頭が上へ飛び出したのは",
        "#       となりの羊毛が「赤」の方？「黄色」の方？（両方/どちらも無し も有り得ます）",
        "#  問3: 奥(z36-40)の右の2列のうち、ピストンが伸びたのは",
        "#       羊毛が「赤」の列？「黄色」の列？（両方/どちらも無し も有り得ます）",
        "",
        "def muki():",
        "    # 北の目印（青い羊毛の列）",
        '    player.execute("fill ~0 ~0 ~0 ~13 ~0 ~0 blue_wool")',
        "    # 問1: 北向きピストン。正しければ北（青い羊毛side）へ伸びる",
        '    player.execute("setblock ~13 ~0 ~17 redstone_block")',
        '    player.execute("setblock ~13 ~0 ~16 sticky_piston 3")  # 北向き',
        "    # 問2: ピストンの上下の切り分け（赤=データ値0 / 黄=データ値1）",
        '    player.execute("setblock ~0 ~0 ~36 red_wool")',
        '    player.execute("setblock ~1 ~0 ~36 sticky_piston 0")',
        '    player.execute("setblock ~2 ~0 ~36 redstone_block")',
        '    player.execute("setblock ~4 ~0 ~36 yellow_wool")',
        '    player.execute("setblock ~5 ~0 ~36 sticky_piston 1")',
        '    player.execute("setblock ~6 ~0 ~36 redstone_block")',
        "    # 問3: リピーターの矢印の切り分け（赤=データ値0 / 黄=データ値2）。",
        "    # 矢印が北向きの列だけ、信号が流れて北向きピストン（問1で実証済み）が伸びる",
        '    player.execute("setblock ~9 ~0 ~40 red_wool")',
        '    player.execute("setblock ~9 ~0 ~39 redstone_block")',
        '    player.execute("setblock ~9 ~0 ~38 unpowered_repeater 0")',
        '    player.execute("setblock ~9 ~0 ~37 redstone_wire")',
        '    player.execute("setblock ~9 ~0 ~36 sticky_piston 3")',
        '    player.execute("setblock ~13 ~0 ~40 yellow_wool")',
        '    player.execute("setblock ~13 ~0 ~39 redstone_block")',
        '    player.execute("setblock ~13 ~0 ~38 unpowered_repeater 2")',
        '    player.execute("setblock ~13 ~0 ~37 redstone_wire")',
        '    player.execute("setblock ~13 ~0 ~36 sticky_piston 3")',
    ]
    z = 2
    for key, facings in AUX_RULES.items():
        b = BLOCKS[key]
        cmd.append(f"    # {b['name_ja']}（{z}マス南の列）")
        for f in ("north", "south", "east", "west", "down", "up"):
            if f not in facings:
                continue
            x = dir_col[f]
            if key == "ladder":
                sx, sz = support[f]
                cmd.append(f'    player.execute("setblock ~{x + sx} ~0 ~{z + sz} stone")')
            cmd.append(f'    player.execute("setblock ~{x} ~0 ~{z} '
                       f'{b["bedrock_id"]}{command_suffix(key, f)}")  # {_DIR_JA[f]}')
        z += 2
    cmd += [
        "    # オークのドア（上下2マスで1つ。セットで置く）",
        f'    player.execute("setblock ~0 ~0 ~{z} wooden_door")',
        f'    player.execute("setblock ~0 ~1 ~{z} wooden_door 8")  # 上半分',
        '    player.say("むき確認ブロックを置きました")',
        "",
        'player.on_chat("muki", muki)',
        "",
    ]
    return "\n".join(mc), "\n".join(cmd)


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

    check_mc, check_cmd = check_files()

    (HERE / "PROMPT.md").write_text(prompt, encoding="utf-8")
    (HERE / "viewer.html").write_text(viewer, encoding="utf-8")
    (HERE / "AGENT_PROMPT.md").write_text(agent_prompt, encoding="utf-8")
    (HERE / "check_makecode.txt").write_text(check_mc, encoding="utf-8")
    (HERE / "check_muki.txt").write_text(check_cmd, encoding="utf-8")

    kb = lambda s: f"{len(s.encode('utf-8')) / 1024:.1f} KB"
    print(f"パレット {count} 種類を renderer.js から取り込みました")
    print(f"PROMPT.md    {kb(prompt)}\t… Geminiに貼り付けるプロンプト")
    print(f"viewer.html  {kb(viewer)}\t… 単体で動く設計図ビューア")
    print(f"AGENT_PROMPT.md {kb(agent_prompt)}\t… エージェント建築コード用プロンプト"
          f"（EXTRAS表 {ex_count} 行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
