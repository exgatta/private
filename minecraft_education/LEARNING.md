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

## ブロックIDの落とし穴（実際に6件間違えた）

Bedrock版のブロック名は「新しい名前」に統一されていない。見た目から推測すると外れる。

| 日本語 | 正しいID | 間違えやすい名前 |
|---|---|---|
| オークのトラップドア | `trapdoor` | ~~oak_trapdoor~~ |
| オークのフェンスゲート | `fence_gate` | ~~oak_fence_gate~~ |
| 丸石の階段 | `stone_stairs` | ~~cobblestone_stairs~~ |
| コンパレーター | `unpowered_comparator` | ~~comparator~~ |
| リピーター | `unpowered_repeater` | ~~repeater~~ |
| 看板 | `standing_sign` | ~~oak_sign~~ |
| オークのドア | `wooden_door` | ~~oak_door~~ |

一方で `oak_stairs` `oak_slab` `oak_fence` `oak_leaves` は新しい名前が正しい。
**規則性が無いので、必ず公式データと照合する。**

- 参照データ: `reference/bedrock_blocks.json`（1415ブロック）
  出所は [Mojang/bedrock-samples](https://github.com/Mojang/bedrock-samples) の
  `metadata/vanilladata_modules/mojang-blocks.json`
- 照合: `python3 tools/verify_block_ids.py`（`--update` で取り直し）
- 回帰テストにも入っているので、間違ったIDを足すとテストが落ちる

## ブロックの「状態」＝向きの指定

`/setblock` はブロック名だけだと**既定の向き**で置く。向きは状態で指定する。

```
/setblock ~1 ~1 ~0 oak_stairs ["weirdo_direction"=3]
/setblock ~1 ~1 ~1 hopper ["facing_direction"=0]
/setblock ~2 ~1 ~2 unpowered_comparator ["minecraft:cardinal_direction"="south"]
```

状態プロパティはブロックごとに違う（同じ「向き」でも書き方が4種類ある）。

| 状態プロパティ | 値 | 使うブロック |
|---|---|---|
| `weirdo_direction` | 0=東 1=西 2=南 3=北 | 階段 |
| `direction` | 同上 | トラップドア |
| `facing_direction` | 0=下 1=上 2=北 3=南 4=西 5=東 | ホッパー・ピストン・ディスペンサー・ドロッパー・はしご |
| `minecraft:cardinal_direction` | "north" 等の文字列 | チェスト・コンパレーター・リピーター・フェンスゲート・ドア |
| `minecraft:facing_direction` | "down" 等の文字列 | オブザーバー |
| `ground_sign_direction` | 0〜15（0=南、時計回り） | 看板 |

**上下を向けるのは `facing_direction` 系だけ**。階段やチェストに「下向き」を指定しても
無視されるので、検品でエラーにしている。

変換表は `blueprint/blockstate.py`。状態プロパティ名が実在するかも
`tools/verify_block_ids.py` が公式データと照合する。

## レッドストーンで学んだこと（設計上の要点）

- **ピストンは前2マス目が空いていないと伸びない**。前1マスのブロックを前2マス目へ
  押し出すため。2マス幅の自動ドアを作るとき、通路の両どなりにピストンを置くと
  互いの可動域が重なって永久に動かない（実際にそうなった）
- **動力が来ている場所にピストンを置くと即座に伸びる**。動かす板を先に置き、
  ピストンは最後に置く
- **レッドストーントーチは真下のブロックが動力を受けると消える**。これで信号を
  反転でき、「ふだん閉・踏むと開く」自動ドアが作れる
- **コンパレーターは容器の中身の量を信号の強さにする**。中身1個だと信号は1しかなく、
  そのままでは1マスも進まない。リピーターで15に戻す必要がある
- **コンパレーターの真横にダストを置くと止まる**（横入力が背面入力以上だと出力0）
- 「中身が入ったら撃つ」装置は、コンパレーター＋リピーターでディスペンサーに
  信号を戻すだけでよい。クロック回路は要らず、空になると自然に止まる
- 斜めに接したブロックは「浮いている」ではない。階段を1段ずつずらす勾配屋根は
  面では接していないが正しい作り方（面接触だけで判定してエラーにしていた）

## まだ確認できていないこと

- **MakeCode（Code Builder）のブロック定数名**。定義ファイルが取得できず未検証。
  `commands.txt` の方はIDも向きも公式データで検証済みなので、確実さを求めるなら
  そちらを使う
- **溶岩の当たり判定の高さ**（看板で溶岩を支えてヒナだけ助ける仕組み）。
  公式資料が参照できず、実機での確認が必要
