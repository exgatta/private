"""
Gmail OAuth2セットアップスクリプト（一度だけ実行）
リフレッシュトークンを取得してSecret Managerに保存します。

事前準備:
  1. https://console.cloud.google.com/apis/credentials
     → 「認証情報を作成」→「OAuthクライアントID」
     → アプリの種類: 「デスクトップアプリ」
     → 作成後「JSONをダウンロード」してこのスクリプトと同じフォルダに置く
     → ファイル名を "credentials.json" にリネーム

  2. Gmail API を有効化（未済の場合）:
     gcloud services enable gmail.googleapis.com --project=gmail-manager-auto

実行方法:
  pip3 install google-auth-oauthlib --break-system-packages
  python3 setup_oauth.py
"""

import json
import os
import subprocess
import tempfile

PROJECT_ID   = "gmail-manager-auto"
SECRET_NAME  = "gmail-oauth-credentials"
CREDS_FILE   = "credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.settings.basic",
]


def main():
    # 依存チェック
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("❌ ライブラリが不足しています。以下を実行してください:")
        print("   pip3 install google-auth-oauthlib --break-system-packages")
        return

    if not os.path.exists(CREDS_FILE):
        print(f"❌ {CREDS_FILE} が見つかりません。")
        print("   Google Cloud Console → APIとサービス → 認証情報")
        print("   → 「OAuthクライアントID」(デスクトップアプリ) を作成")
        print(f"   → ダウンロードしたJSONを {CREDS_FILE} にリネームしてここに置く")
        return

    print("🔐 ブラウザが開きます。Googleアカウントでログインしてください...")
    flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    creds_data = {
        "client_id":     creds.client_id,
        "client_secret": creds.client_secret,
        "refresh_token": creds.refresh_token,
    }
    creds_json = json.dumps(creds_data)
    print("✅ 認証成功！")

    # Secret Manager に保存
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(creds_json)
        tmp = f.name

    try:
        print(f"📤 Secret Manager [{SECRET_NAME}] に保存中...")
        create_cmd = (
            f'gcloud secrets create {SECRET_NAME} '
            f'--data-file="{tmp}" '
            f'--replication-policy=automatic '
            f'--project={PROJECT_ID}'
        )
        update_cmd = (
            f'gcloud secrets versions add {SECRET_NAME} '
            f'--data-file="{tmp}" '
            f'--project={PROJECT_ID}'
        )
        result = subprocess.run(create_cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            # 既存 → バージョン追加
            subprocess.run(update_cmd, shell=True, check=True)

        print(f"✅ Secret Manager保存完了: {SECRET_NAME}")

        # Cloud Functionのサービスアカウントにアクセス権を付与
        print("\n🔑 Cloud FunctionのサービスアカウントにSecret Accessを付与中...")
        sa_cmd = (
            f'gcloud functions describe gmail-manager '
            f'--region=asia-northeast1 --gen2 '
            f'--format="value(serviceConfig.serviceAccountEmail)" '
            f'--project={PROJECT_ID}'
        )
        sa_result = subprocess.run(sa_cmd, shell=True, capture_output=True, text=True)
        sa_email = sa_result.stdout.strip()

        if sa_email:
            iam_cmd = (
                f'gcloud secrets add-iam-policy-binding {SECRET_NAME} '
                f'--member="serviceAccount:{sa_email}" '
                f'--role="roles/secretmanager.secretAccessor" '
                f'--project={PROJECT_ID}'
            )
            subprocess.run(iam_cmd, shell=True, check=True)
            print(f"✅ アクセス権付与完了: {sa_email}")
        else:
            print("⚠️ サービスアカウントが取得できませんでした。手動で付与してください。")

    finally:
        os.unlink(tmp)

    print("\n" + "="*50)
    print("🎉 セットアップ完了！")
    print("="*50)
    print("\n次はCloud Functionを再デプロイしてください:")
    print("  bash deploy.sh")
    print("\nその後、手動テスト実行:")
    print("  gcloud scheduler jobs run gmail-manager-daily --location=asia-northeast1")


if __name__ == "__main__":
    main()
