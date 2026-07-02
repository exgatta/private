# gpmf_tool — GPMF 完全パーサ & GoPro 化メタデータ注入ツール

GPMF (GoPro Metadata Format) を完全に解析し、他社カメラ・スマホ・ドローン等で
撮影した MP4 に GPMF テレメトリトラックと GoPro 識別メタデータを注入して、
テレメトリ対応ソフト (GoPro Quik, Telemetry Extractor, DashWare など) から
**GoPro の動画と同じように扱える**ようにするツール。

Python 3.8+ / **標準ライブラリのみ**（依存パッケージなし）。

## できること

| 機能 | コマンド |
|---|---|
| GPMF の完全パース（人間可読ダンプ / JSON） | `parse` |
| MP4 から GPMF 抽出（生バイナリ / JSON / GPX） | `extract` |
| MP4 へ GPMF トラック + GoPro 識別情報を注入 | `inject` |
| MP4 の構造・GoPro メタデータ状況の確認 | `info` |

## 使い方

このディレクトリの**親ディレクトリ**から `python3 -m gpmf_tool` で実行する。

### 1. 他社カメラの動画を GoPro 化する

```bash
# GPS ログ (GPX) 付きで注入 — GoPro HERO11 として認識される
python3 -m gpmf_tool inject input.mp4 -o output.mp4 --gpx ride.gpx --device hero11

# GPS ログが無い場合（デバイス情報のみの GPMF を注入）
python3 -m gpmf_tool inject input.mp4 -o output.mp4 --device hero9
```

注入される内容:

- **gpmd タイムドメタデータトラック** — GoPro 実機と同一構造
  (handler `meta` / 名前 `GoPro MET  ` / stsd `gpmd`)。1 秒 = 1 ペイロードで
  `DEVC > STRM > GPS5`（緯度・経度・高度・2D/3D 速度、10 Hz、実機と同じ
  SCAL/UNIT/GPSU/GPSF/GPSP 付き）を格納
- **moov/udta の GoPro 識別ボックス** — `FIRM`（ファームウェア）/ `LENS` /
  `CAME`（シリアル）/ `MUID` / `GPMF`（デバイス情報）
- **ftyp** を GoPro と同じ `mp41` ブランドに置換（`--keep-ftyp` で無効化）
- 既存トラックの **hdlr 名**を `GoPro AVC` / `GoPro AAC` に変更
  （`--no-handler-rename` で無効化）

主なオプション:

| オプション | 説明 |
|---|---|
| `--device {hero5..hero13}` | 機種プリセット（DVNM/FIRM が変わる。既定 hero9） |
| `--gpx file.gpx` | GPS テレメトリの元データ |
| `--rate 10` | GPS サンプリングレート Hz（実機は 10〜18 Hz） |
| `--no-fit` | GPX の時間軸を動画長に合わせて伸縮しない |
| `--firmware` / `--device-name` / `--serial-seed` | 識別情報の上書き |

GPX と動画の長さが違う場合、既定では GPX の時間軸を動画長に合わせて伸縮する
（30 分のライドログを 5 秒のクリップに割り当てる、といった使い方ができる）。

### 2. GoPro 動画の GPMF を解析する

```bash
python3 -m gpmf_tool parse GH010001.MP4            # 人間可読ダンプ
python3 -m gpmf_tool parse GH010001.MP4 --json out.json
python3 -m gpmf_tool parse telemetry.bin --lenient  # 生バイナリも可・壊れた要素はスキップ
```

### 3. GPMF を抽出する

```bash
python3 -m gpmf_tool extract GH010001.MP4 -o raw.bin --json full.json --gpx track.gpx
```

`--gpx` は GPS5/GPS9 ストリームを SCAL でスケール解除し GPSU の UTC 時刻付きで
GPX 1.1 に書き出す（Google Earth や Strava 等で開ける）。

### 4. 確認

```bash
python3 -m gpmf_tool info output.mp4
# トラック一覧 / gpmd トラック有無 / FIRM などの GoPro ボックスを表示
```

## GPMF 対応範囲

- 全データ型: `b B s S l L j J f d`（整数・浮動小数点）、`c`（文字列）、
  `F`（4CC）、`G`（GUID）、`q Q`（固定小数点 Q15.16/Q31.32）、`U`（UTC 日時）
- ネストコンテナ（`DEVC`/`STRM` 等、型 0x00）の再帰パース
- **複合型 `?`** — 直前の `TYPE` 要素による構造定義（`f[4]` 形式の配列も対応）
- マルチ要素サンプル（GPS5 = 5 要素 × N サンプル等）
- 4 バイトアラインメント、`strict`/`lenient` 両モード
- 主要 4CC キー 50 種以上の日本語注釈付きダンプ

## MP4 対応範囲

- 通常の ISO BMFF (非フラグメント)。moov が先頭 (faststart) でも末尾でも可
- 注入は「moov 以外を元順で維持 → GPMF 用 mdat 追加 → moov を末尾に再配置」で行い、
  既存トラックの **stco/co64 チャンクオフセットを自動補正**する
  （映像・音声データは 1 バイトも変更しない）
- 二重注入は検出してエラーにする
- 4GB 超のオフセットは新トラック側で co64 に自動切替

## テスト

```bash
python3 -m unittest discover -s gpmf_tool/tests -v
```

合成 MP4（moov 先頭/末尾の両レイアウト）への注入 → 抽出 → パースの
ラウンドトリップ、全データ型の往復、GPX リサンプリング等 19 テスト。

## Python API

```python
from gpmf_tool import klv, mp4, telemetry, gopro

# パース
with open("GH010001.MP4", "rb") as f:
    samples = mp4.extract_gpmf_samples(f)
items = klv.parse(samples[0].data)
print(klv.dump(items))

# 注入
points, start = telemetry.load_gpx("ride.gpx")
resampled = telemetry.resample_track(points, duration_sec=60.0, rate_hz=10)
payloads, durations = telemetry.build_payloads(resampled, 60.0, "HERO11 Black", start)
udta = gopro.build_udta_boxes(gopro.DEVICE_PRESETS["hero11"], serial_seed="myvideo")
with open("in.mp4", "rb") as src, open("out.mp4", "wb") as dst:
    mp4.inject_gpmf_track(src, dst, payloads, durations, udta_extra=udta,
                          new_ftyp=mp4.build_ftyp_gopro(),
                          handler_renames=gopro.HANDLER_RENAMES)
```

## 注意事項

- 生成される GPS データの精度はソースの GPX に依存する。速度 (2D/3D) は
  座標の前進差分から自動計算される
- フラグメント化 MP4 (moof) と HEVC の `.360` 一部形式は注入非対応（抽出は可）
- 撮影機材の詐称にあたる用途（コンテスト応募・証拠資料など）には使わないこと。
  想定用途は、手持ちの他社カメラ映像を GoPro 系ツールチェーン
  （テレメトリオーバーレイ等）で扱えるようにすること
