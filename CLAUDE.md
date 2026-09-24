# private — プライベート用プロジェクト置き場

がった（exgatta）の私用プロジェクトをまとめたリポジトリ。**1プロジェクト = 1フォルダ**。
仕事用は別リポジトリ `exgatta/work` に置く。ここには仕事のものを入れない。

## 最初に必ず読む
@PRIVATE_PROFILE.md

| フォルダ | 内容 | 詳しい説明 |
|---|---|---|
| `gmail-manager/` | Gmail 自動管理ジョブ（メルマガ削除＋ラベル振り分け。GCP Cloud Run Jobs） | `gmail-manager/CLAUDE.md` |
| `minecraft_education/` | Minecraft Education の建築設計図ジェネレーター／MakeCode コード生成 | `minecraft_education/README.md`, スキル `.claude/skills/minecraft-blueprint/` |
| `gpmf-tool/` | GoPro/DJI 動画の GPMF メタデータ変換・結合アプリ（Win/Mac, GitHub Actions でビルド） | `gpmf-tool/gpmf_tool/README.md` |
| `kanji-poster/` | 小学2年生配当漢字160字の A1 ポスター | `kanji-poster/README.md` |

## ルール
- **ブランチは main 一本**。作業ブランチや PR は作らず、main で作業して main に直接 push する（大きな作り直しで事前確認したい時だけ、指示があれば別ブランチ＋PR）。
- 新しい私用プロジェクトは、直下に新しいフォルダを作ってそこに置く。既存フォルダに混ぜない。
- 作業するときは該当フォルダの README / CLAUDE.md を先に読む。
- GitHub Actions のワークフローはリポジトリ直下 `.github/workflows/` にしか置けないので、
  各ワークフローで `working-directory` と `paths` をそのプロジェクトのフォルダに絞る。
- Claude のスキルも直下 `.claude/skills/` にしか置けない。
- 会話で新しい好み・判断パターンが分かったら `PRIVATE_PROFILE.md` を更新してコミットし、「プロフィールを更新しました」と一言報告する。
