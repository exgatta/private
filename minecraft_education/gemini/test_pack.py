#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成物（PROMPT.md / viewer.html）の回帰テスト。

    python3 test_pack.py

過去に実際に起きた不具合を二度と再発させないための検査を並べている。
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from build_pack import compact_js, escape_for_html, palette_table  # noqa: E402


class TestPack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 生成物が最新であることを前提にするため、まず作り直す
        subprocess.run(
            [sys.executable, "build_pack.py"], cwd=HERE, check=True,
            capture_output=True,
        )
        cls.renderer = (HERE / "renderer.js").read_text(encoding="utf-8")
        cls.prompt = (HERE / "PROMPT.md").read_text(encoding="utf-8")
        cls.viewer = (HERE / "viewer.html").read_text(encoding="utf-8")
        cls.agent = (HERE / "AGENT_PROMPT.md").read_text(encoding="utf-8")

    def test_viewer_script_tags_intact(self):
        """renderer.js のコメント内の </script> でスクリプトが途切れないこと。

        （実際に起きた不具合: ページに JS のソースが本文として表示された）
        """
        tpl = (HERE / "templates" / "viewer.template.html").read_text(encoding="utf-8")
        want = len(re.findall(r"</script\s*>", tpl, re.I))
        got = len(re.findall(r"</script\s*>", self.viewer, re.I))
        self.assertEqual(got, want, "埋め込みで </script> が増減している")

    def test_viewer_is_self_contained(self):
        """外部のURLを一切参照しないこと（ネットが無い学校PCでも動くため）。"""
        for pat in (r"src\s*=\s*[\"']https?:", r"href\s*=\s*[\"']https?:",
                    r"@import", r"fetch\s*\(", r"XMLHttpRequest"):
            self.assertIsNone(
                re.search(pat, self.viewer, re.I), f"外部参照が含まれている: {pat}"
            )

    def test_palette_matches_renderer(self):
        """プロンプトのパレット表が renderer.js と一致すること。

        ズレると Gemini が存在しないブロックを使い、設計が壊れる。
        """
        table, count = palette_table()
        keys = re.findall(r"^\| `(\w+)` \|", table, re.M)
        self.assertEqual(len(keys), count)
        for key in keys:
            self.assertIn(f"| `{key}` |", self.prompt, f"{key} がプロンプトに無い")
            self.assertRegex(self.renderer, rf"\b{key}:\s*\{{", f"{key} が renderer に無い")

    def test_palette_matches_python(self):
        """Python版パレットと JS版パレットのキーが完全一致すること。"""
        sys.path.insert(0, str(HERE.parent))
        from blueprint.palette import BLOCKS  # noqa: E402

        js_keys = set(re.findall(r"^\| `(\w+)` \|", palette_table()[0], re.M))
        self.assertEqual(
            js_keys, set(BLOCKS), "renderer.js と palette.py のブロックが食い違っている"
        )

    def test_compact_js_preserves_behaviour(self):
        """圧縮しても renderer が読み込めること（構文を壊していない）。"""
        out = HERE / "_out"
        out.mkdir(exist_ok=True)
        tmp = out / "_compact_check.js"
        tmp.write_text(compact_js(self.renderer), encoding="utf-8")
        r = subprocess.run(
            ["node", "-e",
             f"var M=require({str(tmp)!r}); if(!M.renderHTML) process.exit(1)"],
            capture_output=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr.decode()[:300])

    def test_escape_is_reversible_in_js(self):
        """エスケープが JS の意味を変えないこと。"""
        self.assertEqual(escape_for_html("a = '</script>';"), "a = '<\\/script>';")
        r = subprocess.run(
            ["node", "-e", "var a = '<\\/script>'; if (a !== '</scr'+'ipt>') process.exit(1)"],
            capture_output=True,
        )
        self.assertEqual(r.returncode, 0)

    def test_prompt_has_essential_rules(self):
        """品質を守る指示がプロンプトから消えていないこと。"""
        for must in ("0起点", "notes", "layer_notes", "fill", "box", "set", "clear",
                     "自己点検", "実際のブロックの座標と一致"):
            self.assertIn(must, self.prompt, f"プロンプトから「{must}」が消えている")

    def test_palette_in_sync_with_python(self):
        """renderer.js のパレットが palette.py と一致していること。

        手で二重管理するとズレ、Geminiが提案したブロックが未定義になる。
        """
        r = subprocess.run(
            [sys.executable, "sync_palette.py", "--check"], cwd=HERE,
            capture_output=True,
        )
        self.assertEqual(r.returncode, 0, r.stdout.decode() + r.stderr.decode())

    def test_stepped_roof_is_not_flagged_as_floating(self):
        """階段を1段ずつずらした勾配屋根が「浮いている」と誤判定されないこと。

        面の接触だけで判定していたとき、いちばん使いたい表現である
        階段の勾配屋根が全部エラーになっていた。
        """
        design = {
            "name": "屋根", "description": "", "notes": [], "layer_notes": {},
            "ops": [
                {"op": "fill", "x1": 0, "y1": 0, "z1": 0, "x2": 4, "y2": 0, "z2": 4,
                 "block": "stone_bricks"},
                {"op": "fill", "x1": 0, "y1": 1, "z1": 0, "x2": 4, "y2": 1, "z2": 0,
                 "block": "oak_stairs", "facing": "south"},
                {"op": "fill", "x1": 0, "y1": 2, "z1": 1, "x2": 4, "y2": 2, "z2": 1,
                 "block": "oak_stairs", "facing": "south"},
                {"op": "fill", "x1": 0, "y1": 3, "z1": 2, "x2": 4, "y2": 3, "z2": 2,
                 "block": "oak_stairs", "facing": "south"},
            ],
        }
        r = subprocess.run(
            ["node", "-e",
             "var M=require('./renderer.js');"
             "var d=JSON.parse(process.argv[1]);"
             "var m=M.buildModel(d); m.normalize();"
             "var v=M.validate(m);"
             "process.stdout.write(JSON.stringify(v.issues.map(function(i){return i.title})));",
             __import__("json").dumps(design)],
            cwd=HERE, capture_output=True,
        )
        titles = __import__("json").loads(r.stdout.decode() or "[]")
        self.assertFalse(
            [t for t in titles if "浮いている" in t],
            f"勾配屋根が浮きブロック扱いされた: {titles}",
        )

    def test_blocked_piston_is_detected(self):
        """伸びる先がふさがったピストンをエラーとして捕まえること。

        （実際に起きた不具合: 2マス幅の自動ドアで、向かい合うピストンの
        あいだにガラスを2枚入れてしまい、どちらも永久に動かなかった。
        図の上では正しく見えるので人の目では気づけない。）
        """
        import json as _json
        design = {
            "name": "詰まったドア", "description": "", "layer_notes": {},
            "notes": ["粘着ピストンは東向きと西向き。ガラスが扉。"],
            "ops": [
                {"op": "fill", "x1": 0, "y1": 0, "z1": 0, "x2": 5, "y2": 0, "z2": 2,
                 "block": "stone"},
                {"op": "set", "x": 1, "y": 1, "z": 1, "block": "sticky_piston",
                 "facing": "east"},
                {"op": "set", "x": 2, "y": 1, "z": 1, "block": "glass"},
                {"op": "set", "x": 3, "y": 1, "z": 1, "block": "glass"},
                {"op": "set", "x": 4, "y": 1, "z": 1, "block": "sticky_piston",
                 "facing": "west"},
            ],
        }
        r = subprocess.run(
            ["node", "-e",
             "var M=require('./renderer.js');"
             "var d=JSON.parse(process.argv[1]);"
             "var m=M.buildModel(d); m.normalize();"
             "process.stdout.write(JSON.stringify(M.validate(m).issues));",
             _json.dumps(design)],
            cwd=HERE, capture_output=True,
        )
        issues = _json.loads(r.stdout.decode() or "[]")
        blocked = [i for i in issues if "伸びられない" in i["title"]]
        self.assertTrue(blocked, f"詰まったピストンを見逃した: {issues}")
        self.assertEqual(blocked[0]["level"], "error")

    def test_circuit_detail_section(self):
        """レッドストーンがある設計にだけ回路詳細図が付き、無い設計には付かないこと。"""
        import json as _json
        H = "<h2>レッドストーン回路のくわしい図</h2>"

        def render(design):
            r = subprocess.run(
                ["node", "-e",
                 "var M=require('./renderer.js');"
                 "process.stdout.write(M.renderHTML(JSON.parse(process.argv[1]),"
                 "{banner:false}));",
                 _json.dumps(design)],
                cwd=HERE, capture_output=True,
            )
            return r.stdout.decode()

        plain = {"name": "小屋", "description": "", "notes": [], "layer_notes": {},
                 "ops": [{"op": "fill", "x1": 0, "y1": 0, "z1": 0, "x2": 3, "y2": 0,
                          "z2": 3, "block": "oak_planks"}]}
        self.assertNotIn(H, render(plain), "回路が無いのに詳細図が出た")

        wired = {"name": "スイッチ", "description": "",
                 "notes": ["レバーとレッドストーンダストを置く。"], "layer_notes": {},
                 "ops": [
                     {"op": "fill", "x1": 0, "y1": 0, "z1": 0, "x2": 3, "y2": 0,
                      "z2": 3, "block": "stone"},
                     {"op": "set", "x": 1, "y": 1, "z": 1, "block": "redstone_wire"},
                     {"op": "set", "x": 2, "y": 1, "z": 1, "block": "lever"},
                 ]}
        html = render(wired)
        self.assertIn(H, html, "回路があるのに詳細図が出ない")
        self.assertIn("レバー", html)
        self.assertIn("15マスまで", html, "ダストの役割説明が出ていない")

    def test_circuit_iso_is_deterministic(self):
        """回路の立体図が毎回まったく同じ順序で描かれること。

        （実際に起きた不具合: 描くブロックを集合で集めていたため並び順が
        実行ごとに変わり、Python版とJS版で図の重なり順が食い違った。）
        """
        sys.path.insert(0, str(HERE.parent))
        from designs import DESIGNS  # noqa: E402
        from blueprint.render import render_html  # noqa: E402

        def circuit(h):
            i = h.find("<h2>レッドストーン回路のくわしい図</h2>")
            return h[i:h.find("<h2>作り方（1段ずつ）</h2>", i)] if i >= 0 else ""

        first = circuit(render_html(DESIGNS["trap_pit"]()))
        self.assertTrue(first, "trap_pit に回路詳細図が出ていない")
        for _ in range(3):
            self.assertEqual(circuit(render_html(DESIGNS["trap_pit"]())), first,
                             "実行するたびに回路の立体図が変わっている")
        self.assertIn("回路だけの立体図", first)

    def test_updown_facing_is_shown(self):
        """ホッパー等の上下向きが図に出ること。

        ホッパーは真下を向くのが基本で、それが読めないと自動装置が作れない。
        上下を三角矢印にすると南北と見分けがつかないため、文字で出している。
        """
        import json as _json
        design = {
            "name": "ホッパー", "description": "",
            "notes": ["ホッパーは下向きと東向き。"], "layer_notes": {},
            "ops": [
                {"op": "fill", "x1": 0, "y1": 0, "z1": 0, "x2": 2, "y2": 0, "z2": 2,
                 "block": "stone"},
                {"op": "set", "x": 1, "y": 1, "z": 1, "block": "hopper", "facing": "down"},
                {"op": "set", "x": 0, "y": 1, "z": 1, "block": "hopper", "facing": "east"},
            ],
        }
        r = subprocess.run(
            ["node", "-e",
             "var M=require('./renderer.js');"
             "process.stdout.write(M.renderHTML(JSON.parse(process.argv[1]),{banner:false}));",
             _json.dumps(design)],
            cwd=HERE, capture_output=True,
        )
        html = r.stdout.decode()
        self.assertIn('class="updown"', html, "上下向きの表示が出ていない")
        self.assertIn('class="dir"', html, "横向きの矢印が出ていない")

    def test_automation_blocks_have_roles(self):
        """ホッパー等の自動装置ブロックに役割の説明が付くこと。

        名前が出るだけでは、どう置けば動くのか分からない。
        """
        import json as _json
        design = {
            "name": "自動装置", "description": "",
            "notes": ["ホッパーとディスペンサーとコンパレーターとリピーター。"],
            "layer_notes": {},
            "ops": [
                {"op": "fill", "x1": 0, "y1": 0, "z1": 0, "x2": 4, "y2": 0, "z2": 4,
                 "block": "stone"},
                {"op": "set", "x": 1, "y": 1, "z": 1, "block": "hopper", "facing": "down"},
                {"op": "set", "x": 2, "y": 1, "z": 1, "block": "dispenser", "facing": "north"},
                {"op": "set", "x": 2, "y": 1, "z": 2, "block": "comparator", "facing": "south"},
                {"op": "set", "x": 2, "y": 1, "z": 3, "block": "repeater", "facing": "south"},
            ],
        }
        r = subprocess.run(
            ["node", "-e",
             "var M=require('./renderer.js');"
             "process.stdout.write(M.renderHTML(JSON.parse(process.argv[1]),{banner:false}));",
             _json.dumps(design)],
            cwd=HERE, capture_output=True,
        )
        html = r.stdout.decode()
        for must in ("向きを間違えると流れが止まって", "動力を受けると中身を1つ発射",
                     "中身の量", "15の強さに戻して"):
            self.assertIn(must, html, f"役割の説明に「{must}」が無い")

    def test_block_ids_exist_in_official_data(self):
        """全ブロックIDが Mojang 公式の定義に実在すること。

        Bedrock の名前は新旧が混在していて、それらしい名前を推測すると外れる。
        （実際に6件外していた: オークのトラップドアは oak_trapdoor ではなく
        trapdoor、コンパレーターは unpowered_comparator など）
        設計図の見た目は正常なので、ゲームでコマンドを打つまで誰も気づけない。
        """
        r = subprocess.run(
            [sys.executable, "tools/verify_block_ids.py"],
            cwd=HERE.parent, capture_output=True,
        )
        self.assertEqual(r.returncode, 0,
                         r.stdout.decode() + r.stderr.decode())

    def test_commands_include_facing(self):
        """コマンド出力に向きが入ること。

        以前は facing を完全に無視していたため、階段もホッパーも
        すべて既定の向きで置かれ、仕掛けが動かなかった。
        """
        sys.path.insert(0, str(HERE.parent))
        from blueprint.model import VoxelModel  # noqa: E402
        from blueprint.makecode import export_commands  # noqa: E402

        m = VoxelModel("t", "")
        m.fill(0, 0, 0, 3, 0, 3, "stone")
        m.set(0, 1, 0, "oak_stairs", "north")
        m.set(1, 1, 0, "hopper", "down")
        m.set(2, 1, 0, "comparator", "south")
        out = export_commands(m)
        self.assertIn('oak_stairs ["weirdo_direction"=3]', out)
        self.assertIn('hopper ["facing_direction"=0]', out)
        self.assertIn('unpowered_comparator ["minecraft:cardinal_direction"="south"]', out)

    def test_runs_do_not_merge_different_facings(self):
        """向きの違うブロックが1つのコマンドにまとめられないこと。

        まとめると片方の向きが失われる。
        """
        sys.path.insert(0, str(HERE.parent))
        from blueprint.model import VoxelModel  # noqa: E402
        from blueprint.makecode import export_commands  # noqa: E402

        m = VoxelModel("t", "")
        m.fill(0, 0, 0, 3, 0, 0, "stone")
        m.set(0, 1, 0, "oak_stairs", "north")
        m.set(1, 1, 0, "oak_stairs", "north")
        m.set(2, 1, 0, "oak_stairs", "south")
        out = export_commands(m)
        self.assertIn('/fill ~0 ~1 ~0 ~1 ~1 ~0 oak_stairs ["weirdo_direction"=3]', out)
        self.assertIn('/setblock ~2 ~1 ~0 oak_stairs ["weirdo_direction"=2]', out)

    def test_impossible_facing_is_detected(self):
        """そのブロックに指定できない向きをエラーにすること。

        階段は上下を向けない。指定しても無視されて既定の向きで置かれるため、
        図のとおりに見えるのに現物だけ違う、という気づきにくい事故になる。
        """
        import json as _json

        def issues(design):
            r = subprocess.run(
                ["node", "-e",
                 "var M=require('./renderer.js');"
                 "var d=JSON.parse(process.argv[1]);"
                 "var m=M.buildModel(d); m.normalize();"
                 "process.stdout.write(JSON.stringify("
                 "M.validate(m).issues.map(function(i){return i.title})));",
                 _json.dumps(design)],
                cwd=HERE, capture_output=True,
            )
            return _json.loads(r.stdout.decode() or "[]")

        base = {"op": "fill", "x1": 0, "y1": 0, "z1": 0, "x2": 3, "y2": 0,
                "z2": 3, "block": "stone"}
        bad = {"name": "t", "description": "", "notes": [], "layer_notes": {},
               "ops": [base, {"op": "set", "x": 1, "y": 1, "z": 1,
                              "block": "oak_stairs", "facing": "down"}]}
        self.assertTrue([t for t in issues(bad) if "向きの指定" in t],
                        "階段の上下向きを見逃した")

        ok = {"name": "t", "description": "", "notes": ["ホッパーは下向き。"],
              "layer_notes": {},
              "ops": [base, {"op": "set", "x": 1, "y": 1, "z": 1,
                             "block": "hopper", "facing": "down"}]}
        self.assertFalse([t for t in issues(ok) if "向きの指定" in t],
                         "ホッパーの下向きは正しいのにエラーになった")

    def test_redstone_parts_are_not_plain_cubes(self):
        """レッドストーン部品が小さな立方体で描かれていないこと。

        （実際に起きた不具合: ダストもトーチもリピーターも一律に
        0.62倍の小さな立方体で描いていて、Minecraftの見た目と別物だった。
        実物は ダスト=床の線 / トーチ=棒 / リピーター=薄い板 / ホッパー=漏斗。）
        """
        sys.path.insert(0, str(HERE.parent))
        from blueprint.render import _iso_parts  # noqa: E402
        from blueprint.palette import BLOCKS  # noqa: E402

        def parts(key, facing=None):
            return _iso_parts(key, BLOCKS[key], facing)

        # ダストと感圧板はぺったんこ（高さが0.1未満）
        for key in ("redstone_wire", "stone_pressure_plate"):
            self.assertLess(parts(key)[0][5], 0.1, f"{key} が平たくない")
        # トーチは細い（幅が0.2未満）棒＋先端の2つ
        t = parts("redstone_torch")
        self.assertEqual(len(t), 2, "トーチが棒＋先端になっていない")
        self.assertLess(t[0][2], 0.2, "トーチの棒が太い")
        # リピーターは薄い板＋灯
        r = parts("repeater", "south")
        self.assertLess(r[0][5], 0.2, "リピーターが薄い板でない")
        self.assertGreaterEqual(len(r), 2, "リピーターに灯が無い")
        # ホッパーは上の受け口＋下の細い出口
        h = parts("hopper", "down")
        self.assertEqual(len(h), 2, "ホッパーが漏斗の形でない")
        self.assertEqual(h[0][2], 0.5, "ホッパーの受け口がマス幅でない")
        self.assertLess(h[1][2], 0.3, "ホッパーの出口が細くない")
        # ピストン・ディスペンサーはふつうの立方体
        for key in ("sticky_piston", "dispenser"):
            q = parts(key, "north")
            self.assertEqual(q, [(0, 0, 0.5, 0.5, 1.0, 1.0)],
                             f"{key} が立方体で描かれていない")

    def test_dust_shows_connections(self):
        """レッドストーンダストが「どこへつながっているか」を描くこと。

        （実際に起きた不具合: ダストを床の赤い板で描いたら、Minecraftらしくは
        なったが配線がどこへ続いているのか読めなくなった。
        Minecraftと同じく、つながる向きへ腕が伸びる形にする。）
        """
        sys.path.insert(0, str(HERE.parent))
        from blueprint.render import _dust_links, _dust_parts  # noqa: E402

        # 東西に3個つながったダスト。真ん中は東西の2方向につながる
        cells = {(0, 1, 0): "redstone_wire", (1, 1, 0): "redstone_wire",
                 (2, 1, 0): "redstone_wire"}
        mid = _dust_links(cells, (1, 1, 0))
        self.assertEqual(set(mid), {"east", "west"}, f"つながりが違う: {mid}")
        end = _dust_links(cells, (0, 1, 0))
        self.assertEqual(set(end), {"east"}, f"端のつながりが違う: {end}")

        # つながる向きの数だけ腕が増える
        self.assertGreater(len(_dust_parts(mid)), len(_dust_parts(end)))
        self.assertEqual(len(_dust_parts({})), 1, "孤立したダストは点1つ")

        # 回路部品にもつながる（ディスペンサーへ届いていることが読める）
        cells2 = {(0, 1, 0): "redstone_wire", (1, 1, 0): "dispenser"}
        self.assertEqual(set(_dust_links(cells2, (0, 1, 0))), {"east"})

        # 段差でつながるときは up / down を返す
        cells3 = {(0, 1, 0): "redstone_wire", (1, 2, 0): "redstone_wire"}
        self.assertEqual(_dust_links(cells3, (0, 1, 0)).get("east"), "up")

    def test_dust_wire_drawn_in_layer_grid(self):
        """段ごとの図でもダストが配線の形で描かれること。"""
        import json as _json
        design = {
            "name": "配線", "description": "", "notes": ["ダストを一直線に置く。"],
            "layer_notes": {},
            "ops": [
                {"op": "fill", "x1": 0, "y1": 0, "z1": 0, "x2": 4, "y2": 0, "z2": 2,
                 "block": "stone"},
                {"op": "fill", "x1": 0, "y1": 1, "z1": 1, "x2": 3, "y2": 1, "z2": 1,
                 "block": "redstone_wire"},
            ],
        }
        r = subprocess.run(
            ["node", "-e",
             "var M=require('./renderer.js');"
             "process.stdout.write(M.renderHTML(JSON.parse(process.argv[1]),{banner:false}));",
             _json.dumps(design)],
            cwd=HERE, capture_output=True,
        )
        html = r.stdout.decode()
        self.assertIn('class="wire"', html, "配線の線が描かれていない")
        self.assertIn('class="wire-bg"', html, "ダストのマスの下地が無い")

    def test_textures_match_python(self):
        """JS版のテクスチャ定義が Python版と一致すること。

        手で写すとズレて、PythonとJSで見た目が変わってしまう。
        """
        sys.path.insert(0, str(HERE.parent))
        from blueprint.render import TEXTURES, _TEX_OF  # noqa: E402

        for name in TEXTURES:
            self.assertIn(f'"{name}":', self.renderer, f"模様 {name} が JS に無い")
        for key, name in _TEX_OF.items():
            self.assertIn(f'"{key}": "{name}"', self.renderer,
                          f"{key} の模様の割り当てが JS に無い")

    def test_partial_shapes_are_textured(self):
        """ハーフ・トラップドア・階段にもテクスチャが乗ること。

        （実際に起きた不具合: マスいっぱいの箱にしか模様を敷いていなかったため、
        トラップドアも階段もハーフも単色の板きれに見えていた。）
        """
        sys.path.insert(0, str(HERE.parent))
        from blueprint.model import VoxelModel  # noqa: E402
        from blueprint.render import render_html  # noqa: E402

        m = VoxelModel("t", "")
        m.fill(0, 0, 0, 2, 0, 0, "stone")
        m.set(0, 1, 0, "oak_trapdoor", "south")
        m.set(1, 1, 0, "oak_slab")
        m.set(2, 1, 0, "oak_stairs", "east")
        html = render_html(m)
        for key in ("oak_trapdoor", "oak_slab", "oak_stairs"):
            self.assertIn(f"url(#tt_{key})", html, f"{key} が単色のまま")

    def test_grass_has_dirt_sides(self):
        """草ブロックの側面が土色になること（Minecraftの見た目）。"""
        sys.path.insert(0, str(HERE.parent))
        from blueprint.render import _tex_base  # noqa: E402

        self.assertNotEqual(_tex_base("grass", "t"), _tex_base("grass", "l"))
        self.assertEqual(_tex_base("dirt", "l"), _tex_base("grass", "l"),
                         "草の側面が土と同じ色になっていない")

    def test_agent_prompt_covers_palette(self):
        """エージェント用プロンプトの定数表が palette.py と一致すること。

        ズレると Gemini が存在しない MakeCode 定数を使い、コードが動かない。
        置き物は向きが要りエージェントでは置けないので、禁止の印が必要。
        """
        sys.path.insert(0, str(HERE.parent))
        from blueprint.palette import BLOCKS  # noqa: E402

        for key, b in BLOCKS.items():
            mc = b["makecode"]
            self.assertIn(f"`{mc}`", self.agent, f"{key} の定数 {mc} が表に無い")
            if b.get("marker"):
                self.assertRegex(
                    self.agent, rf"`{mc}` \|[^|]*\| \*\*置き物",
                    f"置き物 {key} に LAYERS 禁止の印が無い",
                )

    def test_agent_prompt_engine_is_valid_python(self):
        """エージェント用プロンプトの建築エンジンが構文的に正しいこと。

        Gemini はエンジンを「そのまま写す」だけなので、ここが壊れていると
        全員のコードが動かない。文法だけでも機械検査しておく。
        """
        m = re.search(r"```python\n(.*?)```", self.agent, re.S)
        self.assertIsNotNone(m, "Pythonコードブロックが無い")
        code = m.group(1)
        compile(code, "AGENT_PROMPT", "exec")  # 構文エラーならここで落ちる

        # エンジンの根幹（これが消えたら建たない）
        for must in ("agent.teleport_to_player()", "agent.set_item(",
                     "agent.set_slot(", "agent.place(DOWN)",
                     "player.execute(", "place_extras()",
                     'player.on_chat("build", build)', "変更禁止"):
            self.assertIn(must, code + self.agent, f"エンジンに {must} が無い")

        # 例の設計データが表にある定数だけを使っていること
        sys.path.insert(0, str(HERE.parent))
        from blueprint.palette import BLOCKS  # noqa: E402

        legal = {b["makecode"] for b in BLOCKS.values()}
        legend = re.search(r"LEGEND_BLOCKS = \[(.*?)\]", code)
        for const in re.findall(r"[A-Z][A-Z_]+", legend.group(1)):
            self.assertIn(const, legal, f"例の {const} がパレットに無い")

    def test_agent_prompt_forbids_liquids_and_markers(self):
        """置き物・液体は LAYERS でなく EXTRAS で置く指示があること。

        エージェントは向きを付けて置けないので、向き物はコマンド（EXTRAS）で置く。
        """
        # 冒頭の使い方説明にも【ここから】の文字があるため、行として立っている方を使う
        body = self.agent[self.agent.index("\n【ここから】\n"):self.agent.index("\n【ここまで】")]
        self.assertIn("`WATER` と `LAVA` も `LAYERS` に入れない", body)
        self.assertIn("「置き物」印のブロックは `LAYERS` に入れない", body)
        self.assertIn("一字一句そのままコピー", body)
        self.assertIn("ピストンは EXTRAS のいちばん最後", body)
        self.assertIn("前2マスは空けて", body)
        self.assertIn("1文字も変えないで", body)
        self.assertIn("全角の記号・空白", body)

    def test_agent_extras_table_matches_blockstate(self):
        """EXTRAS表の文字列が blockstate.py の出力と一致すること。

        表はGeminiが一字一句コピーする正本。commands.txt と同じ経路
        （bedrock_id + state_suffix、公式データと照合済み）とズレたら、
        エージェント版だけ向きの壊れたブロックが置かれてしまう。
        """
        sys.path.insert(0, str(HERE.parent))
        from blueprint.blockstate import STATE_RULES, state_suffix  # noqa: E402
        from blueprint.palette import BLOCKS  # noqa: E402

        for key, b in BLOCKS.items():
            if key in STATE_RULES:
                for f in ("north", "south", "east", "west"):
                    suf = state_suffix(key, f)
                    if suf:
                        self.assertIn(f"`{b['bedrock_id']}{suf}`", self.agent,
                                      f"{key} の {f} 向きが表に無い")
            elif b.get("marker") or key in ("water", "lava"):
                self.assertIn(f"`{b['bedrock_id']}`", self.agent,
                              f"{key} の行が表に無い")
        # 実機に無い状態値を教えないこと（ホッパー上向き・はしご上下）
        self.assertNotIn('`hopper ["facing_direction"=1]`', self.agent)
        self.assertNotIn('`ladder ["facing_direction"=0]`', self.agent)
        self.assertNotIn('`ladder ["facing_direction"=1]`', self.agent)

    def test_build_prompt_documents_all_ops(self):
        """BUILD_PROMPT.md の ops 仕様が PROMPT.md とズレないこと。

        再構築プロンプトに ops の仕様が欠けていると、作り直したツールが
        利用者向けプロンプトと違う形の JSON を期待して噛み合わなくなる。
        """
        doc = (HERE.parent / "BUILD_PROMPT.md").read_text(encoding="utf-8")
        start = doc.index("## 【ここから】")
        end = doc.index("## 【ここまで】")
        body = doc[start:end]

        for op in ("fill", "box", "set", "clear"):
            self.assertIn(f"`{op}`", body, f"命令 {op} の説明が無い")
        for key in ('"op": "fill"', '"op": "box"', '"op": "set"', '"op": "clear"',
                    '"ops"', '"notes"', '"layer_notes"', '"facing"'):
            self.assertIn(key, body, f"JSON例に {key} が無い")
        for facing in ("north", "south", "east", "west"):
            self.assertIn(f"`{facing}`", body, f"向き {facing} の説明が無い")

        # layer_notes のキーの数え方（PROMPT.md と同じ説明であること）
        self.assertIn('`"0"` が1段目', body)
        self.assertIn('`"0"` が1段目', self.prompt)

    def test_generated_files_not_hand_edited(self):
        """生成物に「編集するな」の注意が入っていること。"""
        self.assertIn("build_pack.py", (HERE / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
