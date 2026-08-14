# マイクラ設計図ジェネレーター（Minecraft Education向け）

「作りたいもの」を指示すると、**レゴの組立説明書のようなレイヤー式設計図**を
自動生成する仕組み。Gmail管理ジョブとは無関係の独立フォルダ。

## できること

設計（ボクセルモデル）を1つ書くと、3点セットが出力される:

| 出力 | 内容 |
|---|---|
| `blueprint.html` | **レゴ式設計図**。完成イメージ（立体図）＋材料リスト＋1段ずつの作り方。ブラウザで開いて見ながら手で建てる |
| `makecode_build.py` | Code Builder（ゲーム内でCキー→MakeCode Python）に貼ると、チャットで `build` と打つだけで自動で建つ |
| `commands.txt` | `/fill`・`/setblock` コマンド版。チャットに貼っても建てられる |

## 使い方

```bash
cd minecraft_education
python3 generate.py --list    # 設計の一覧
python3 generate.py house     # 「ちいさな木の家」の設計図を samples/house/ に出力
```

依存ライブラリなし（Python 3 標準機能のみ）。

## 新しい設計図を作ってもらうには（Claudeへの頼み方）

このフォルダを開いたClaude Codeセッションで、例えばこう頼む:

> 「お城の設計図を作って」「15×15の噴水つき庭園の設計図を作って」

Claudeは `designs/house.py` を見本に新しい設計ファイルを書き、
`generate.py` で3点セットを出力して設計図を見せてくれる。
手順の詳細は `.claude/skills/minecraft-blueprint/SKILL.md` にある。

## フォルダ構成

```
minecraft_education/
├── README.md          ← このファイル
├── BUILD_PROMPT.md    ← このツールを作り直す／引き継ぐためのプロンプト
├── LEARNING.md        ← Minecraft Education の学習メモ（座標系・Code Builder等）
├── generate.py        ← CLI（設計名を渡すと3点セットを出力）
├── blueprint/         ← ジェネレーター本体
│   ├── palette.py     ← 使えるブロックの定義（色・記号・ID）。ブロック追加はここ
│   ├── model.py       ← ボクセルモデル（fill / hollow_box などの形状ヘルパー）
│   ├── render.py      ← レゴ式設計図HTMLの描画
│   └── makecode.py    ← MakeCode Python / コマンド版の出力
├── designs/           ← 設計置き場（1作品=1ファイル、__init__.py に登録）
│   └── house.py       ← サンプル: ちいさな木の家（9×7・高さ7段）
└── samples/           ← 生成された設計図
```

## 設計のルール（設計ファイルの書き方）

- 座標: `x`=西→東, `z`=北→南（設計図では上が北）, `y`=段（0が1段目）
- ブロックは `palette.py` にあるキーのみ使える。足りなければ先にパレットへ追加
- ドア・たいまつ等の「置き物」は `marker` 扱いで、自動建築では手動設置を案内
- 大きさの目安: 初心者向けは20×20×15段以内が作りやすい
