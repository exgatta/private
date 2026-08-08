# Minecraft Education 学習メモ

設計図ジェネレーターを作るために調べた、Minecraft Education（マインクラフト エデュケーション版）の基礎知識のまとめ。

## Minecraft Educationとは

教育向けに作られたMinecraftの特別版（Bedrock系）。通常のMinecraftの遊び方に加えて、
プログラミング学習（Code Builder）、化学実験、授業用ワールドなどの教育機能が入っている。

## 座標系（設計図の土台になる知識）

Minecraftの世界は3つの座標で位置を表す:

- **X** … 東西方向（東がプラス）
- **Y** … 高さ（上がプラス）→ 設計図の「段」に対応
- **Z** … 南北方向（南がプラス）

座標の書き方は2種類:

- **絶対座標** `100 64 -20` … ワールドの原点(0,0,0)からの位置
- **相対座標** `~1 ~0 ~2` … プレイヤーがいる場所からの相対位置（`~`チルダ付き）

このリポジトリの設計図は「建てたい場所に立つ→そこを基準に相対座標で組む」方式。

## Code Builder（ゲーム内プログラミング）

- ゲーム内で **Cキー** を押すと起動（タッチ端末はエージェントのアイコン）
- **MakeCode**（ブロック式 / Python / JavaScript）、Tynker、Azure Notebooks が選べる
- ブロック式は10〜12歳向け、Pythonは12歳以上向けが目安とされる
- **エージェント**という小さなロボットに命令して、代わりにブロックを置かせたり
  掘らせたりできる（`agent.place`, `agent.move` など）
- ワールドに直接ブロックを置くAPIもある:
  - `blocks.place(ブロック, pos(x, y, z))` … 1個置く
  - `blocks.fill(ブロック, pos(x1,y1,z1), pos(x2,y2,z2))` … 直方体に敷き詰める
  - `pos(0, 0, 0)` はプレイヤー相対座標
  - `player.on_chat("build", 関数)` … チャットで合図したら実行

→ このAPIを使えば、設計図どおりの建物を**自動で建てるコード**も出力できる
（`blueprint/makecode.py` が担当）。

## Education限定の特別ブロック

授業・共同作業向けのブロックがある（通常版には無い）:

- **許可(Allow)ブロック** … この上では建築OKになる
- **拒否(Deny)ブロック** … この上では建築禁止になる
- **境界(Border)ブロック** … 上下無限の見えない壁。行動範囲を区切る
- **ストラクチャーブロック** … 建造物の保存・書き出し(3Dエクスポート)ができる
- **化学機能** … 元素構成器・化合物作成器など。118元素、30以上の化合物

## 建築の設計図（この世界での定番スタイル）

Minecraft界隈では「レイヤー式（layer-by-layer）」が設計図の定番。
レゴの組立説明書と同じ考え方:

1. 完成イメージ（立体図）を見る
2. 材料リスト（どのブロックが何個いるか）をそろえる
3. **1段目から順に、上から見た格子図**のとおりにブロックを置いていく

BuildGuides / Bloxelizer / Mineprints などのサイトもこの形式を採用している。
このリポジトリのジェネレーターも同じ形式でHTML設計図を出力する。

## 情報源

- [Code Builder in Minecraft Education（公式サポート）](https://edusupport.minecraft.net/hc/en-us/articles/360047116992-Code-Builder-in-Minecraft-Education)
- [MakeCode for Minecraft — Positions チュートリアル](https://minecraft.makecode.com/tutorials/positions)
- [MakeCode for Minecraft — Blocks リファレンス](https://minecraft.makecode.com/reference/blocks)
- [Python Content for Minecraft Education（公式ブログ）](https://education.minecraft.net/en-us/blog/new-ways-to-code-introducing-python-content-for-minecraft-education-edition)
- [Specialty Blocks (Allow, Deny, Border, Structure)（公式サポート）](https://edusupport.minecraft.net/hc/en-us/articles/360047116852-Specialty-Blocks-Allow-Deny-Border-Structure)
- [Minecraft Education exclusive features（Minecraft Wiki）](https://minecraft.wiki/w/Minecraft_Education_exclusive_features)
- [BuildGuides — レイヤー式設計図サイトの例](https://buildguides.net/)
- [Mineprints — レイヤー表示ビューア](https://www.mineprints.net/)
