#!/usr/bin/env node
/* validate() が「わざと壊した設計」をちゃんと捕まえるかのテスト。
 *   node test_validate.js
 */
var path = require("path");
var MB = require(path.join(__dirname, "renderer.js"));

function check(design) {
  var m = MB.buildModel(design);
  m.normalize();
  return MB.validate(m);
}

var cases = [];

// ① 過去に実際に起きた致命バグ: 生座標で設計を書き、注記も生座標で書いた。
//    表示は正規化(0起点)されるので図と注記が10マス/20マスずれる。
cases.push(["① 正規化ズレ（注記の座標が図の外）", {
  name: "ズレた罠", description: "", layer_notes: {},
  ops: [
    { op: "fill", x1: 10, y1: 5, z1: 20, x2: 14, y2: 5, z2: 24, block: "stone" },
    { op: "fill", x1: 10, y1: 6, z1: 20, x2: 14, y2: 6, z2: 24, block: "stone_bricks" },
    { op: "set", x: 12, y: 7, z: 22, block: "stone_pressure_plate" }
  ],
  notes: ["石の感圧板は (x=12, z=22) に置く。真下の x=10〜14, z=20 は石にする。"]
}]);

// ② パレット外ブロック
cases.push(["② パレットに無いブロック", {
  name: "未定義", description: "", notes: [], layer_notes: {},
  ops: [
    { op: "fill", x1: 0, y1: 0, z1: 0, x2: 3, y2: 0, z2: 3, block: "stone" },
    { op: "set", x: 1, y: 1, z: 1, block: "diamond_block" },
    { op: "sett", x: 2, y: 1, z: 2, block: "stone" }
  ]
}]);

// ③ 支えの無い浮きブロック
cases.push(["③ 空中に浮いたブロック", {
  name: "浮遊", description: "", notes: [], layer_notes: {},
  ops: [
    { op: "fill", x1: 0, y1: 0, z1: 0, x2: 4, y2: 0, z2: 4, block: "stone" },
    { op: "set", x: 2, y: 3, z: 2, block: "glowstone" }
  ]
}]);

// ④ レイヤーの飛び（2段目が空っぽ）
cases.push(["④ とちゅうの段が空", {
  name: "段とび", description: "", notes: [], layer_notes: {},
  ops: [
    { op: "fill", x1: 0, y1: 0, z1: 0, x2: 3, y2: 0, z2: 3, block: "stone" },
    { op: "fill", x1: 0, y1: 2, z1: 0, x2: 3, y2: 2, z2: 3, block: "stone" },
    { op: "set", x: 0, y: 1, z: 0, block: "oak_log" },
    { op: "clear", x: 0, y: 1, z: 0 }
  ]
}]);

// ⑤ 「N段目(y=M)」の対応ミス + markerの説明なし + 段目が範囲外
cases.push(["⑤ 段目とyの対応ミス／説明のない置き物", {
  name: "段ズレ", description: "", layer_notes: {},
  ops: [
    { op: "fill", x1: 0, y1: 0, z1: 0, x2: 3, y2: 0, z2: 3, block: "stone" },
    { op: "fill", x1: 0, y1: 1, z1: 0, x2: 3, y2: 1, z2: 3, block: "stone_bricks" },
    { op: "set", x: 1, y: 2, z: 1, block: "sticky_piston" }
  ],
  notes: ["2段目(y=2)の配線を先にすませる。9段目のレバーは最後。"]
}]);

// ⑥ 大きすぎる
// 上限を超えるのは maxDim(64マス) より大きいとき。
// 32〜64マスは「作れるが大きめ」として参考表示になるだけで、合格のまま。
cases.push(["⑥ 上限オーバー", {
  name: "巨大", description: "", notes: [], layer_notes: {},
  ops: [{ op: "fill", x1: 0, y1: 0, z1: 0, x2: 79, y2: 0, z2: 79, block: "stone" }]
}]);

cases.push(["⑥b 大きめ（上限内なので合格）", {
  name: "大きめ", description: "", notes: [], layer_notes: {},
  ops: [{ op: "fill", x1: 0, y1: 0, z1: 0, x2: 39, y2: 0, z2: 39, block: "stone" }]
}, { expectOk: true }]);

// ⑦ 正常な設計（合格するはず）
cases.push(["⑦ 問題なしの設計", {
  name: "小屋", description: "", layer_notes: {},
  ops: [
    { op: "fill", x1: 0, y1: 0, z1: 0, x2: 4, y2: 0, z2: 4, block: "oak_planks" },
    { op: "box", x1: 0, y1: 1, z1: 0, x2: 4, y2: 2, z2: 4, block: "oak_planks" },
    { op: "set", x: 2, y: 1, z: 4, block: "door" }
  ],
  notes: ["オークのドアは南面(z=4)の x=2 に、外(南)から見て正面になる向きで最後に置く。"]
}]);

var fail = 0;
cases.forEach(function (c) {
  var r = check(c[1]);
  console.log("\n=== " + c[0] + " → " + (r.ok ? "✅ 合格" : "⚠ " + r.issues.length + "件の問題"));
  r.issues.forEach(function (it) {
    var lv = it.level === "error" ? "要修正" : it.level === "warn" ? "確認" : "参考";
    console.log("  【" + lv + "】" + it.title);
    console.log("    " + it.detail);
    console.log("    直し方: " + it.fix);
  });
  // 第3要素で「合格するはず」を明示する。無ければ「不合格になるはず」。
  var expectOk = !!(c[2] && c[2].expectOk) || c[0].indexOf("⑦") === 0;
  if (expectOk !== r.ok) { fail++; console.log("  !! 期待とちがう結果"); }
});
console.log("\n" + (fail === 0 ? "すべて期待どおり ✅" : fail + "件が期待とちがう ❌"));
process.exit(fail === 0 ? 0 : 1);
