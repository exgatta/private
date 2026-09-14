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
| `--device {hero5..hero13, max, fusion}` | 機種プリセット（DVNM/FIRM が変わる。既定 hero9。`max`/`fusion` は 360 度カメラ用で `.360` にも対応）|
| `--gpx file.gpx` | GPS テレメトリの元データ |
| `--rate 10` | GPS サンプリングレート Hz（実機は 10〜18 Hz） |
| `--no-fit` | GPX の時間軸を動画長に合わせて伸縮しない |
| `--firmware` / `--device-name` / `--serial-seed` | 識別情報の上書き |

GPX と動画の長さが違う場合、既定では GPX の時間軸を動画長に合わせて伸縮する
（30 分のライドログを 5 秒のクリップに割り当てる、といった使い方ができる）。

### 1.2 他機種の動画に埋め込まれた GPS を使う (GPX 不要)

DJI / iPhone / Android / Sony / Insta360 の動画が持っているテレメトリを
そのまま読み取って GoPro 化できる（外部 GPX を用意しなくてよい）。

```bash
# 動画内蔵の GPS を使って GoPro 化
python3 -m gpmf_tool inject dji.mp4 -o out.mp4 --from-video --device hero11

# どの機種の動画でも、GPS を GPX に書き出す
python3 -m gpmf_tool to-gpx dji.mp4 -o track.gpx
```

対応している埋め込み形式と取り出せる内容:

| 機種 | 形式 | 取り出せるもの |
|---|---|---|
| **DJI**（ドローン/Osmo）| SRT 字幕（動画内トラック or 同名 `.srt`）| GPS **軌跡**（緯度経度高度）|
| **iPhone / Android** | `©xyz` / QuickTime ISO6709 | **撮影地点 1 点**（軌跡ではない）|
| **Sony** | `©xyz`（機種による）| 撮影地点 1 点 |
| **Insta360 / その他** | Studio 等で書き出した `.srt` / `.gpx` | あれば軌跡 |

自動判定の優先順: GoPro GPMF → 動画内 SRT 字幕 → 同名 `.srt` → 撮影地点1点。
DJI の SRT は複数方言（`[latitude: ...]` 形式・`GPS(経度,緯度,...)` 形式）に対応。

> スマホ/Sony の「撮影地点1点」は移動軌跡ではないため、動画全体が同じ座標に
> なる（撮影場所の記録として使える）。移動を再現したい場合は別途 GPX を使う。

GUI では **「動画に埋め込まれたGPSを使う」** にチェックを入れるだけ。一括処理と
併用すれば、DJI 動画フォルダを**各ファイル自身の GPS で**まとめて GoPro 化できる。

### 1.4 自動分割された動画を結合する (再エンコードなし)

DJI / Insta360 / GoPro は撮影中に自動でファイルを分割する (FAT32 の 4GB 制限
やカメラ側の仕様)。これを **画質を一切落とさずに** 1 本へ結合できる。

```bash
# フォルダを渡すだけ。「1本の撮影が強制分割されたもの」を自動判定して結合
python3 -m gpmf_tool join ./videos --output-dir ./out

# 判定結果だけ先に確認する
python3 -m gpmf_tool join ./videos --dry-run

# 結合と同時に GoPro 化 (一時ファイルを作らないので容量は1本分だけ)
python3 -m gpmf_tool join ./videos --gopro --device max --output-dir ./out

# 判定せず、指定した全ファイルを強制的に1本にまとめる
python3 -m gpmf_tool join a.mp4 b.mp4 --no-detect -o 結合.mp4
```

**結合すべきかの判定**は、ファイル名ではなく中身で行う:

1. **撮影時刻の連続性** — 次ファイルの撮影開始が
   「前ファイルの開始 + 前ファイルの長さ」とほぼ一致するか（±90秒）
2. **コーデック・解像度・トラック構成**が完全一致するか
3. 撮影時刻が全ファイル同一 or 記録なしのカメラのみ、ファイル名で代替判定

別々の撮影は結合されず、単独の動画はそのまま残る。

- **再エンコードしない**ので画質劣化ゼロ・処理はコピー並みに高速
- 映像/音声/GPMF の各トラックのサンプルテーブル
  (stts/stsz/stsc/stco/stss/ctts) を正しく合成し、キーフレーム位置も維持
- 4GB を超える結合結果は自動的に 64bit (co64/largesize) で出力
- コーデックや解像度が違うファイルは結合せずエラーで知らせる
- GUI では **「分割動画を結合 (DJI等)」** ボタン → 動画をまとめて選択 →
  判定結果が出て、GoPro 化するかを聞かれ、保存先を選ぶだけ

**タイムスタンプの扱い**:

| | 結合後どうなるか |
|---|---|
| 動画内の撮影日時 (mvhd) | **先頭素材の撮影日時**を引き継ぐ（撮影開始時刻）|
| ファイルの更新日時 | 同じく先頭素材の撮影日時に合わせる（撮影順に並ぶ）|
| GPS の時刻 (GPSU) | GPX / 動画内蔵テレメトリの時刻をそのまま使う |

`info` で表示される「撮影日時」も、結合前の先頭ファイルと同じ値になる。

### 1.5 複数ファイルを一括で GoPro 化する

```bash
# フォルダ内の全動画をまとめて処理 (出力は out/ に <名前>_gopro.mp4)
python3 -m gpmf_tool batch ./videos -o ./out --device hero11 --gpx ride.gpx

# 複数ファイル/フォルダを混ぜて指定・再帰探索も可
python3 -m gpmf_tool batch a.mp4 b.mov ./more_videos -o ./out --recursive
```

- 対象拡張子: `.mp4 .mov .m4v .360`（`*_gopro.*` と非動画は自動除外）
- `--gpx` を付けると**全ファイルに同じ GPX** を適用（各動画長に自動で伸縮）
- 出力済みファイルは既定でスキップ（`--overwrite` で上書き）
- 1 本が失敗しても残りは続行し、最後に「成功 / スキップ / 失敗」を集計
GUI での一括処理は 3 通り:

- **「複数ファイルを一括」** ボタン → 動画を複数選択
- **「フォルダを一括」** ボタン → フォルダを選ぶと中の動画を再帰的に全部処理
- **ドラッグ&ドロップ** → ウィンドウに動画やフォルダを放り込む
  （`tkinterdnd2` を同梱したビルドで有効。未対応環境ではボタンで代替）

いずれも最後に出力先フォルダを選ぶだけ。

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

### 4. 確認 / 動画に入っている位置情報を調べる

```bash
python3 -m gpmf_tool info video.mp4
```

**動画の基本情報**（撮影日時・解像度・フレームレート・コーデック・
平均ビットレート・長さ）を表示し、さらにトラック一覧・gpmd トラック有無・
FIRM・360度マーカー、そして**位置情報/テレメトリを自動判定**する
（GoPro 以外の形式も検出）:

- **GoPro GPMF**（gpmd トラック）
- **スマホの撮影地点**（`©xyz` / QuickTime の ISO6709。緯度経度を地図リンク付きで表示）
- **Camera Motion Metadata (camm)**（Street View 系・一部 360 カメラ）
- **DJI / Insta360** 系メタデータのヒント

手持ちの動画に何が入っているか分からないときは、まず `info` で覗くとよい。
GoPro 形式なら `extract --gpx` で軌跡を取り出せ、何も無ければ
`inject --gpx` で後付けできる。

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

## アプリとしてパッケージ化する

依存パッケージゼロなので、単体実行ファイル (Python 不要) に固められる。

### 単体exe / アプリのビルド

```bash
# Linux / macOS
bash build_app.sh
# Windows
build_app.bat
```

**PyInstaller はクロスコンパイル不可**なので、OS ごとにその OS 上でビルドする。
出力形態は OS で変わる:

- **macOS**: `dist/GPMF-GoPro.app` … Finder で**ダブルクリック起動できる .app**
  （引数なしで GUI が開く。Terminal は開かない）
- **Windows**: `dist/gpmf.exe` … ダブルクリックで GUI、引数付きで CLI
- **Linux**: `dist/gpmf` … 単体バイナリ

```bash
# macOS: ダブルクリックで起動。CLI は .app 内の実行体を直接呼ぶ
open dist/GPMF-GoPro.app
./dist/GPMF-GoPro.app/Contents/MacOS/gpmf inject in.mp4 -o out.mp4 --gpx ride.gpx --device hero11

# Windows / Linux
./dist/gpmf                    # 引数なし → GUI
./dist/gpmf inject in.mp4 -o out.mp4 --gpx ride.gpx --device hero11
```

> **Mac の初回起動について**: 未署名アプリのため、ダウンロード直後は
> Gatekeeper が「開発元を確認できません」と警告する。`mac_setup.sh` を使うか
> `xattr -dr com.apple.quarantine GPMF-GoPro.app` を一度実行すれば、
> 以降は普通にダブルクリックで起動できる（右クリック→開く でも可）。

GUI では、入力 MP4・出力先・GPX を選び、機種を選んで「GoPro化を実行」を
押すだけ（Tkinter 製・追加依存なし）。

### Mac用・Windows用を別々に自動ビルドする (GitHub Actions)

PyInstaller はクロスコンパイル不可なので、手元に Mac と Windows の両方が
無い場合は CI で各 OS のランナー上でビルドする。
`.github/workflows/build-app.yml` を同梱済み:

- GitHub の **Actions タブ → "Build gpmf app" → Run workflow** で実行
- 完了後、実行結果ページ下部の **Artifacts** から
  `gpmf-windows.exe`（Windows）と `gpmf-macos-arm64`（Mac / Apple Silicon）
  をダウンロードできる

Windows と macOS (Apple Silicon) の 2 バイナリが並列で作られる。

### pip でインストールする場合

```bash
pip install .
gpmf inject in.mp4 -o out.mp4 --gpx ride.gpx --device hero11   # CLI
gpmf-gui                                                        # GUI
```

## 注意事項

- 生成される GPS データの精度はソースの GPX に依存する。速度 (2D/3D) は
  座標の前進差分から自動計算される
- フラグメント化 MP4 (moof) と HEVC の `.360` 一部形式は注入非対応（抽出は可）
- 撮影機材の詐称にあたる用途（コンテスト応募・証拠資料など）には使わないこと。
  想定用途は、手持ちの他社カメラ映像を GoPro 系ツールチェーン
  （テレメトリオーバーレイ等）で扱えるようにすること
