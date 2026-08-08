/* designs/house.py と同じ設計を「設計データオブジェクト」で書いたもの（検証用）。
 * 座標: x=0..8(西→東), z=0..6(北→南), 玄関は南向き(z=6側)。
 */
var ops = [];
var F = function (x1, y1, z1, x2, y2, z2, b) { ops.push({ op: "fill", x1: x1, y1: y1, z1: z1, x2: x2, y2: y2, z2: z2, block: b }); };
var B = function (x1, y1, z1, x2, y2, z2, b) { ops.push({ op: "box", x1: x1, y1: y1, z1: z1, x2: x2, y2: y2, z2: z2, block: b }); };
var S = function (x, y, z, b) { ops.push({ op: "set", x: x, y: y, z: z, block: b }); };
var C = function (x, y, z) { ops.push({ op: "clear", x: x, y: y, z: z }); };

// 1段目: 丸石の床（土台）
F(0, 0, 0, 8, 0, 6, "cobblestone");

// 2〜4段目: 壁（オークの板材）と四隅の柱（オークの原木）
[1, 2, 3].forEach(function (y) {
  B(0, y, 0, 8, y, 6, "oak_planks");
  [[0, 0], [8, 0], [0, 6], [8, 6]].forEach(function (c) { S(c[0], y, c[1], "oak_log"); });
});

// 玄関（南面の中央）: 2マス分あけてドアを置く
S(4, 1, 6, "door");
C(4, 2, 6);   // ドアの上半分ぶんの空間

// 窓（3段目の高さ）: 南面2つ・北面3つ・東西1つずつ
[2, 6].forEach(function (x) { S(x, 2, 6, "glass"); });
[2, 4, 6].forEach(function (x) { S(x, 2, 0, "glass"); });
S(0, 2, 3, "glass");
S(8, 2, 3, "glass");

// 部屋の中の明かり: 四隅の床にたいまつ
[[1, 1], [7, 1], [1, 5], [7, 5]].forEach(function (t) { S(t[0], 1, t[1], "torch"); });

// 5〜7段目: 三角屋根（トウヒの板材）。棟は東西方向。
F(0, 4, 0, 8, 4, 1, "spruce_planks");
F(0, 4, 5, 8, 4, 6, "spruce_planks");
[0, 8].forEach(function (gx) { F(gx, 4, 2, gx, 4, 4, "oak_planks"); });
F(0, 5, 2, 8, 5, 2, "spruce_planks");
F(0, 5, 4, 8, 5, 4, "spruce_planks");
[0, 8].forEach(function (gx) { S(gx, 5, 3, "oak_planks"); });
F(0, 6, 3, 8, 6, 3, "spruce_planks");

var DESIGN = {
  name: "ちいさな木の家",
  description: "オークの板材と丸石でつくる、はじめての家。玄関は南向きで、" +
    "三角屋根はトウヒの板材。9×7マス・高さ7段。",
  ops: ops,
  notes: [],
  layer_notes: {}
};

if (typeof module === "object" && module.exports) module.exports = DESIGN;
