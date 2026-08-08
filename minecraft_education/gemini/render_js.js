#!/usr/bin/env node
/* JS版レンダラで設計図HTMLを出力する（検証用CLI）。
 *   node render_js.js house            … 検品バナー付き
 *   node render_js.js house --no-banner … Python版と同じ内容だけ（比較用）
 *   node render_js.js house --validate  … 検品結果をJSONで出力
 */
var path = require("path");
var MB = require(path.join(__dirname, "renderer.js"));

var name = process.argv[2];
var args = process.argv.slice(3);
if (!name) {
  console.error("usage: node render_js.js <design> [--no-banner|--validate]");
  process.exit(1);
}
var design = require(path.join(__dirname, "designs", name + ".js"));

if (args.indexOf("--validate") !== -1) {
  var m = MB.buildModel(design);
  m.normalize();
  process.stdout.write(JSON.stringify(MB.validate(m), null, 2) + "\n");
} else {
  var banner = args.indexOf("--no-banner") === -1;
  process.stdout.write(MB.renderHTML(design, { banner: banner }));
}
