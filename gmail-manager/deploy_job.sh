#!/bin/bash
# Gmail自動管理 - Cloud Run Jobs デプロイスクリプト
set -e

PROJECT_ID="gmail-manager-auto"
REGION="asia-northeast1"
JOB_NAME="gmail-manager-job"
SA_EMAIL="$(gcloud iam service-accounts list \
    --project=$PROJECT_ID \
    --filter="displayName:gmail-manager OR email:*-compute@developer*" \
    --format="value(email)" | head -1)"

echo "======================================"
echo "☁️  Gmail自動管理 Cloud Run Jobs デプロイ"
echo "======================================"
echo "プロジェクト: $PROJECT_ID"
echo "リージョン:   $REGION"
echo "ジョブ名:     $JOB_NAME"
echo ""

# Cloud Run Jobs APIを有効化
echo "📡 APIを有効化中..."
gcloud services enable run.googleapis.com --project=$PROJECT_ID
echo "✅ API有効化完了"

# 既存のCloud Functionsスケジューラーを停止
echo ""
echo "⏸  既存のCloud Functionsスケジューラーを停止中..."
gcloud scheduler jobs pause gmail-manager-daily \
    --location=$REGION --project=$PROJECT_ID 2>/dev/null || true
echo "✅ 停止完了"

# Cloud Run Jobsとしてデプロイ
echo ""
echo "🚀 Cloud Run Jobsにデプロイ中（3〜5分かかります）..."
gcloud run jobs deploy "$JOB_NAME" \
    --source="$(dirname "$0")" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --task-timeout=86400 \
    --memory=512Mi \
    --cpu=1 \
    --max-retries=0 \
    --set-env-vars="GCP_PROJECT=$PROJECT_ID"

echo "✅ デプロイ完了"

# サービスアカウントのメールを取得
SA_EMAIL=$(gcloud run jobs describe "$JOB_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --format="value(spec.template.spec.template.spec.serviceAccountName)" 2>/dev/null || \
    gcloud iam service-accounts list \
    --project=$PROJECT_ID \
    --filter="email:*-compute@developer*" \
    --format="value(email)" | head -1)

echo "サービスアカウント: $SA_EMAIL"

# Cloud Schedulerを新しいジョブ用に設定
echo ""
echo "⏰ Cloud Scheduler設定中（毎朝8:00 JST）..."

JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"

gcloud scheduler jobs create http "${JOB_NAME}-daily" \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --schedule="0 23 * * *" \
    --uri="$JOB_URI" \
    --http-method=POST \
    --oauth-service-account-email="$SA_EMAIL" \
    --time-zone="UTC" 2>/dev/null || \
gcloud scheduler jobs update http "${JOB_NAME}-daily" \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --schedule="0 23 * * *" \
    --uri="$JOB_URI" \
    --http-method=POST \
    --oauth-service-account-email="$SA_EMAIL" \
    --time-zone="UTC"

# サービスアカウントにCloud Run Jobs起動権限を付与
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/run.invoker" 2>/dev/null || true

echo "✅ スケジューラー設定完了"

echo ""
echo "======================================"
echo "🎉 セットアップ完了！"
echo "======================================"
echo ""
echo "  今すぐテスト実行:"
echo "  gcloud run jobs execute $JOB_NAME --region=$REGION --project=$PROJECT_ID"
echo ""
echo "  ログ確認:"
echo "  gcloud run jobs executions list --job=$JOB_NAME --region=$REGION --project=$PROJECT_ID"
echo "  gcloud beta run jobs executions logs tail --region=$REGION --project=$PROJECT_ID [実行ID]"
echo ""
echo "  スケジューラー手動実行:"
echo "  gcloud scheduler jobs run ${JOB_NAME}-daily --location=$REGION --project=$PROJECT_ID"
echo "======================================"
