#!/bin/bash
# Gmail ラベル統合 - Cloud Run Jobs で実行するスクリプト
set -e

PROJECT_ID="gmail-manager-auto"
REGION="asia-northeast1"
JOB_NAME="label-consolidation"

echo "======================================"
echo "📁 Gmail ラベル統合 実行"
echo "======================================"

# Cloud Run Jobs としてデプロイ（label_consolidation.py を実行する一時ジョブ）
echo "🚀 Cloud Run Jobs にデプロイ中..."
gcloud run jobs deploy "$JOB_NAME" \
    --source="$(dirname "$0")" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --command="python" \
    --args="label_consolidation.py" \
    --task-timeout=3600 \
    --memory=512Mi \
    --cpu=1 \
    --max-retries=0 \
    --set-env-vars="GCP_PROJECT=$PROJECT_ID"

echo "✅ デプロイ完了"

# 即座に実行
echo ""
echo "▶️  ジョブ実行中..."
gcloud run jobs execute "$JOB_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --wait

echo ""
echo "📋 ログ確認:"
EXEC_ID=$(gcloud run jobs executions list \
    --job="$JOB_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --format="value(name)" \
    --limit=1)
gcloud beta run jobs executions logs tail "$EXEC_ID" \
    --region="$REGION" \
    --project="$PROJECT_ID" 2>/dev/null || \
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=$JOB_NAME" \
    --project="$PROJECT_ID" \
    --limit=100 \
    --format="value(textPayload)" 2>/dev/null || true

echo ""
echo "======================================"
echo "🎉 完了！"
echo "======================================"
echo ""
echo "  ログ確認（後から）:"
echo "  gcloud run jobs executions list --job=$JOB_NAME --region=$REGION --project=$PROJECT_ID"
echo ""
echo "  ジョブ削除（片付け）:"
echo "  gcloud run jobs delete $JOB_NAME --region=$REGION --project=$PROJECT_ID"
echo "======================================"
