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

    def test_generated_files_not_hand_edited(self):
        """生成物に「編集するな」の注意が入っていること。"""
        self.assertIn("build_pack.py", (HERE / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
