# Gmail自動管理ジョブ — 引き継ぎ / 運用ガイド

exgatta@gmail.com の受信メールを毎朝自動で「メルマガ削除＋トピック別ラベル振り分け」するシステム。
本体は `main.py` ひとつ。Google Cloud Run Jobs 上で毎朝8:00 JSTに自動実行される。

> このファイルは Claude Code が自動で読み込む引き継ぎ用ドキュメント。
> 別マシン（Web版など）でこのフォルダを開けば、ここを起点に作業を続けられる。
>
> **置き場所**: GitHub `exgatta/private` リポジトリの `gmail-manager/` フォルダ（2026-09 に旧 `exgatta/gmail-manager` から移設）。
> 下記のコマンドはすべて**この `gmail-manager/` フォルダに cd してから**実行する。

---

## クラウド構成（GCP）— ここで実際に動いている

| 要素 | 値 |
|---|---|
| Project ID | `gmail-manager-auto` |
| Region | `asia-northeast1` |
| Cloud Run Job | `gmail-manager-job` |
| Scheduler | `gmail-manager-job-daily` … `0 23 * * *` UTC（= **毎朝8:00 JST**）, ENABLED |
| 旧Scheduler | `gmail-manager-daily`（Cloud Functions時代の遺物, PAUSED。再開しない） |
| Secrets | `gmail-app-password`（IMAP用アプリパスワード）, `gmail-oauth-credentials`（配信停止/フィルタ操作用 OAuth refresh token） |
| コンテナイメージ | `asia-northeast1-docker.pkg.dev/gmail-manager-auto/cloud-run-source-deploy/gmail-manager-job` |
| Task timeout | 86400秒（24h）/ メモリ512Mi / CPU1 / max-retries 0 |

**重要**: 認証情報はすべて Secret Manager にある。コードにもローカルにも秘密情報は無い。
デプロイ済みジョブはコンテナイメージ＋Secret＋Schedulerだけで完結し、ローカルPCに依存しない。

---

## ローカル構成

- フォルダ: `/Users/macuser/gmail_function/`
- **`main.py`** … 日次ジョブの本体（これだけが本番に効く）
- **`deploy_job.sh`** … デプロイ＋スケジューラ設定スクリプト
- その他大量の `*.py`（`fix_*.py`, `migrate_*.py`, `cleanup_*.py`, `route_co.py` など）
  … 過去にラベル整理を一括実行した**使い捨てスクリプト**。日次ジョブとは無関係。
  これらは `~/.gmail_local_credentials.json`（ローカルOAuth、現在は失効）を使っていた。

---

## ロジック（main.py の動作）

### main() の2段構え
- **Step 1 — 受信トレイ全件**: 下記①〜⑤すべて実施（削除も移動もする＝整理する）
- **Step 2 — 既存ラベル約828個を巡回**: ④で必ず「移動しない」に抜ける＝**削除だけ**。
  `EZ受信ボックス` / `EZ送信ボックス`（配下含む）は除外。ラベル自体やGmailフィルタは消さない。

### 1通ごとの判定（process_folder、上から順に最初に当たった所で確定）
1. **バウンス通知**（配信停止の失敗メール）→ 削除（`is_our_unsubscribe_bounce`）
2. **ホワイトリスト**（google/apple系 `WHITELIST_DOMAINS`）→ 絶対に削除しない・保護
3. **削除対象**（`is_delete_target`: `DELETE_SENDERS`該当 or `List-Unsubscribe`ヘッダーあり）
   → 配信停止リクエスト（`try_unsubscribe`）してから削除
4. **Step 2（既存ラベル巡回）なら**ここで終了＝**移動しない**（`if not is_inbox: continue`）
5. **ラベルを決めて移動**（`resolve_label_for_sender`）

### ⑤ ラベル決定の優先順位（resolve_label_for_sender）
1. `LABEL_RULES`（182件, `(ラベル, [ドメイン/キーワード])`）に一致 → そのラベル
2. 送信者名が既存の入れ子ラベルの“子名”に一致 → その既存ラベル（手動整理を尊重）
3. `LABEL_PARENT_MAP`（16件）のドメインに一致 → `親/送信者名` を新規作成
4. どれも無し → **受信トレイに残す（None）**。フラットラベルは作らない

### 効いている安全装置
- `DRY_RUN=1` 環境変数で破壊的操作（削除・移動）を全部ログ出力だけにできる（ブラスト半径確認用）
- `_org_from_domain` が複合TLD（co.jp/ne.jp/or.jp等）を正しく処理。
  旧バグ（`docomo.ne.jp`→`ne` を量産）は修正済み。`_JP_SLD` で属性型SLDを除外
- 分類は送信者ドメインだけでなく**件名（本文snippet含む）**も見る

---

## 運用コマンド（このフォルダから実行）

```bash
# デプロイ（コード変更後）
bash deploy_job.sh
# もしくは直接:
gcloud run jobs deploy gmail-manager-job --source=. --region=asia-northeast1 \
  --project=gmail-manager-auto --task-timeout=86400 --memory=512Mi --cpu=1 \
  --max-retries=0 --set-env-vars="GCP_PROJECT=gmail-manager-auto"

# 手動実行（約35〜40分）
gcloud run jobs execute gmail-manager-job --region=asia-northeast1 --project=gmail-manager-auto --wait

# ドライラン（消さずに何が削除されるか確認）
gcloud run jobs update gmail-manager-job --region=asia-northeast1 --project=gmail-manager-auto --update-env-vars DRY_RUN=1
gcloud run jobs execute gmail-manager-job --region=asia-northeast1 --project=gmail-manager-auto --wait
gcloud run jobs update gmail-manager-job --region=asia-northeast1 --project=gmail-manager-auto --remove-env-vars DRY_RUN  # 本番に戻す

# 実行履歴・ログ
gcloud run jobs executions list --job=gmail-manager-job --region=asia-northeast1 --project=gmail-manager-auto --limit=10
gcloud logging read 'resource.type="cloud_run_job" AND labels."run.googleapis.com/execution_name"="<EXEC_NAME>"' \
  --project=gmail-manager-auto --limit=200000 --format="value(textPayload)" --order=asc
```

---

## ユーザー合意事項（必ず守る運用ルール）

- **`EZ受信ボックス` / `EZ送信ボックス` の中身はラベル含め触らない**（Step 2で除外済み）
- **既存ラベルは「削除」だけ。移動・ラベル変更・ラベル削除はしない**（2026-05-31 指示）
- **破壊的操作は必ず dry-run を先に**実行して規模を見せてから本番
- **分類はドメインだけでなく本文（件名/snippet）も確認**する
- **未登録の送信者はフラットラベルを作らず受信トレイに残す**（ラベル乱立の防止）

## ラベルルールの足し方

`main.py` の `LABEL_RULES` に `("親/子ラベル名", ["ドメイン断片"])` を1行足して `bash deploy_job.sh`。
受信トレイは毎朝Step 1で全件再処理されるので、既存の該当メールも翌朝自動で移動する。
Yahoo等の汎用ドメイン（ymail.ne.jp等）はドメインでなくフルアドレスで指定する。

## 既知の残課題

- `yosetti.com`（寄せ書きサービス）… 対応ラベルが無く受信トレイ残留（仕様。必要なら新ラベル＋ルール）
- Google系セキュリティ通知・gmailカレンダー招待 … ホワイトリスト保護で受信トレイ残留（仕様）

## これまでの主な作業履歴

- トピックベースのラベル階層へ再編、フラットラベル約184個を整理、co/ne乱立バグを修正
- ezwebメールの重複ラベル剥がし（EZ箱へ集約）
- Step 2 を「削除専用」で復活＋DRY_RUN検証（2026-05-31）
- 受信トレイ精査でラベルルール追加: 9件（2026-06-10）＋写真整理協会（2026-06-14）
- 現状: 毎朝成功で安定稼働、受信トレイ 31通 → 9通
