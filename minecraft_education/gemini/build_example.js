#!/usr/bin/env node
/* 「Geminiが出力するHTML」と同じ形の自己完結HTMLを組み立てる（動作確認用）。
 *   node build_example.js house  →  _out/example_house.html
 * 中身は  <script>renderer.js</script> + <script>DESIGN と mount()</script>  だけ。
 * 外部ファイル・CDN・APIを一切使わないので、Gemini Canvas でそのまま表示できる。
 */
var fs = require("fs");
var path = require("path");

var name = process.argv[2] || "house";
var renderer = fs.readFileSync(path.join(__dirname, "renderer.js"), "utf8");
var design = require(path.join(__dirname, "designs", name + ".js"));

var html =
  '<!doctype html>\n<html lang="ja">\n<head>\n<meta charset="utf-8">\n' +
  '<meta name="viewport" content="width=device-width, initial-scale=1">\n' +
  "<title>マイクラ設計図</title>\n</head>\n<body>\n" +
  "<script>\n" + renderer + "</script>\n" +
  "<script>\nconst DESIGN = " + JSON.stringify(designToPlain(design), null, 2) + ";\n" +
  "MinecraftBlueprint.mount(DESIGN);\n</script>\n</body>\n</html>\n";

function designToPlain(d) {
  return {
    name: d.name, description: d.description,
    ops: d.ops, notes: d.notes, layer_notes: d.layer_notes
  };
}

var out = path.join(__dirname, "_out");
fs.mkdirSync(out, { recursive: true });
var file = path.join(out, "example_" + name + ".html");
fs.writeFileSync(file, html);
console.log(file + "  (" + (html.length / 1024).toFixed(1) + " KB)");
