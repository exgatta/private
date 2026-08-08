---
name: minecraft-blueprint
description: マイクラ（Minecraft Education）の建築物の設計図を作る。ユーザーが「〇〇の設計図を作って」「マイクラで〇〇を建てたい」「レゴみたいな組立説明書がほしい」等、建物・構造物の作り方やブループリントを求めたときに使う。Use when the user asks for a Minecraft build blueprint, layer-by-layer build guide, or construction plan for Minecraft Education.
---

# マイクラ設計図の作り方

ユーザーが指示した制作物（家・城・塔・船など）の設計図を
`minecraft_education/` のジェネレーターで作成する。

## 手順

1. **要望を具体化する**。指示があいまいなら、常識的なデフォルトで決めて進める
   （サイズは初心者向け=20×20×15段以内、素材はそれらしい定番ブロック）。
   ユーザーが明示した希望（大きさ・色・素材）は必ず守る。

2. **パレット確認**: `minecraft_education/blueprint/palette.py` の `BLOCKS` を見る。
   必要なブロックが無ければ同じ形式で追加する
   （bedrock_id は Bedrock版の正式ID、makecode は MakeCode定数名、symbol は漢字1文字）。

3. **設計ファイルを書く**: `minecraft_education/designs/house.py` を見本に
   `designs/<英語名>.py` を作る。`build()` が `VoxelModel` を返す。
   - 座標: x=西→東, z=北→南（図の上が北）, y=段（0が1段目）
   - `m.fill()` / `m.hollow_box()` / `m.set()` で組む
   - ドア・たいまつ等の置き物は marker ブロック（door, torch）を使う
   - 中は空洞にする（`hollow_box`）。屋根は1段ずつ内側に寄せると三角になる

4. **登録して生成**: `designs/__init__.py` の `DESIGNS` に1行追加 →
   `cd minecraft_education && python3 generate.py <名前>`

5. **検品**: 生成された `samples/<名前>/blueprint.html` をスクリーンショット等で確認。
   立体図が指示どおりの形か（屋根が浮いていないか、壁に穴が無いか）を必ず見る。
   おかしければ設計を直して再生成する。

6. **納品**: blueprint.html を Artifact として公開してリンクを渡す
   （artifact-design スキル読み込み→Artifact ツール）。あわせて
   `makecode_build.py`（Code Builderで自動建築）と `commands.txt` の使い方を一言添える。

7. **コミット**: 新しい設計ファイルと生成物をコミットしておく（次回の見本になる）。

## 品質の目安

- 設計図はレゴの説明書と同じく「下の段から順に置けば完成する」構成になっているか
- 材料リストの合計が極端に多すぎないか（子供が手で建てるなら500個以内が目安）
- 左右対称の建物は座標のズレが出やすい。中心座標を決めてから書く
