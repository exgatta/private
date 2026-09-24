---
name: minecraft-blueprint
description: マイクラ（Minecraft Education）の建築物の設計図を作る。ユーザーが「〇〇の設計図を作って」「マイクラで〇〇を建てたい」「レゴみたいな組立説明書がほしい」等、建物・構造物の作り方やブループリントを求めたときに使う。Use when the user asks for a Minecraft build blueprint, layer-by-layer build guide, or construction plan for Minecraft Education.
---

# マイクラ設計図の作り方（ワークフロー方式）

ユーザーが指示した制作物（家・城・塔・船など）の設計図を
`minecraft_education/` のジェネレーターで作成する。

**ユーザー合意事項（2026-08-08）: 設計図づくりは Workflow ツールによる
マルチエージェント・オーケストレーションで行う。** この合意が明示的なオプトイン。
単純な質問への回答や1行の修正だけならワークフロー不要。

## ワークフローの組み立て（Workflowツールで実行）

3フェーズ構成を基本にする（エージェント数はサイズ指示に合わせて調整、目安6〜10体）:

1. **Design（設計案の競作）** — 2〜3体のエージェントに同じ要望を渡し、
   それぞれ別の切り口（例: 忠実・遊び心・建てやすさ優先）で
   `designs/house.py` を見本にした設計コード案を書かせる（schemaでコードを返させる）。
   審査エージェント1体が「指示との一致・形の破綻・ブロック数」で採点し1案を選ぶ。
2. **Build（実装と生成）** — 勝ち案を designs/<英語名>.py として保存し
   `designs/__init__.py` に登録、`python3 generate.py <名前>` を実行するエージェント1体。
3. **Verify（対抗検証）** — 2〜3体が独立に検品:
   - モデル検査: python3で座標を調べ、壁の穴・浮いた屋根・めり込みが無いか
   - 見た目検査: blueprint.html をスクリーンショットして指示どおりの形か
   - 出力検査: makecode_build.py / commands.txt のID・座標が正しいか
   不合格ならその指摘を添えて設計を修正し再生成（1〜2周まで）。

## 各フェーズ共通の前提知識（エージェントのプロンプトに含めること）

- 座標: x=西→東, z=北→南（設計図では上が北）, y=段（0が1段目）
- ブロックは `blueprint/palette.py` の `BLOCKS` のキーのみ。足りなければ
  同じ形式で追加（bedrock_id=Bedrock正式ID, makecode=MakeCode定数, symbol=漢字1文字）
- `m.fill()` / `m.hollow_box()` / `m.set()` で組む。建物の中は空洞にする
- ドア・たいまつ等の置き物は marker ブロック（door, torch）
- サイズの目安: 初心者向けは20×20×15段以内、手で建てるなら合計500個以内
- ユーザーが明示した希望（大きさ・色・素材）は最優先で守る

## 納品（ワークフロー完了後にメインループで行う）

1. `samples/<名前>/blueprint.html` を Artifact として公開しリンクを渡す
   （artifact-designスキル読み込み→Artifactツール。faviconは⛏️）
2. `makecode_build.py`（Code Builderで自動建築）と `commands.txt` の使い方を一言添える
3. 新しい設計ファイルと生成物をコミット＆プッシュ（次回の見本になる）
