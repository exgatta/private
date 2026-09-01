# 小学2年生でならう かん字160字ポスター（A1）

小学2年生の配当漢字160字を、書き順・音読み・訓読みつきで1枚のA1ポスター（594×841mm、完全ベクターPDF）にまとめたもの。

- 成果物: `小学2年生かん字160字ポスター_A1.pdf`（1ページ、フォント埋め込み済みベクター。A1原寸でもそれ以上でも劣化しない）
- 中間生成物: `poster.html`（Chromium印刷でPDF化する組版済みHTML）

## 内容と仕様

- 掲載順: 文部科学省「学年別漢字配当表」の音読み五十音順（引〜話）
- 各セル: 大きな漢字（Klee One 教科書体風）＋番号つき書き順図＋画数＋音読み（カタカナ・青）＋訓読み（ひらがな・緑）
- 送り仮名は細字、中学・高校で学習する読みは（　）囲みの淡色
- 読みは常用漢字表（平成22年内閣告示第2号）準拠。学習段階は文科省「音訓の小・中・高等学校段階別割り振り表」（平成29年3月）準拠

## 検証（2026-09-01 実施）

- 160字のリスト: KANJIDIC2のgrade=2集合と公式配当表順リストの完全一致を機械照合
- 読み・学習段階: 官報告示の原本PDF（常用漢字表＋割り振り表）をパースして全160字照合。独立派生データセット2件とも整合
- 画数: KanjiVG・KANJIDIC2・常用漢字表の3ソースで全字一致
- レンダリング: DOM機械照合で全160セルの漢字・画数・書き順番号列（1〜n連番）・音訓読みが期待データと一致（エラー0）。目視校閲2巡で重大指摘ゼロ

## 再生成手順

```bash
pip install playwright pypdf pypdfium2   # ChromiumはPlaywright対応のものを用意
mkdir -p fonts && cd fonts
for f in kleeone/KleeOne-Regular.ttf kleeone/KleeOne-SemiBold.ttf \
         zenmarugothic/ZenMaruGothic-Medium.ttf zenmarugothic/ZenMaruGothic-Bold.ttf \
         zenmarugothic/ZenMaruGothic-Black.ttf; do
  curl -sSLO "https://raw.githubusercontent.com/google/fonts/main/ofl/$f"
done
cd ..
python3 build_poster.py   # data/final.json + data/strokes.json → poster.html
python3 fit.py            # セル溢れの実測フィッティング（data/size_overrides.json 更新）
python3 render.py         # poster.html → kanji_grade2_A1.pdf（A1ベクター）
```

※ `render.py` 内のChromium実行パスは環境に合わせて変更すること。

## ファイル

| ファイル | 内容 |
|---|---|
| `data/final.json` | 検証済み最終データ（漢字・画数・音訓読み＋学習段階、配当表順） |
| `data/strokes.json` | KanjiVG由来の書き順パスと番号位置 |
| `data/size_overrides.json` | 読みが多いセルの文字サイズ縮小指定（実測ベース） |
| `data/grade2_clean.json` | KANJIDIC2由来の元データ（参考） |
| `build_poster.py` | 組版（HTML生成） |
| `fit.py` | セル溢れの自動フィッティング |
| `render.py` | Chromium印刷によるPDF出力＋検版用スクリーンショット |
| `merge_final.py` | 検証結果のマージとクロスチェック（再検証時用） |

## ライセンス・クレジット

- 字形・書き順データ: [KanjiVG](https://kanjivg.tagaini.net)（© Ulrich Apel, CC BY-SA 3.0）— ポスターのフッターにクレジット表記済み。頒布時はCC BY-SA 3.0の条件（表示・継承）に従うこと
- 読みデータ: KANJIDIC2（EDRDG, CC BY-SA 4.0）を元に常用漢字表原本で検証
- フォント: Klee One／Zen Maru Gothic（いずれもSIL Open Font License 1.1。PDFへのサブセット埋め込みはOFLで許諾済み）
