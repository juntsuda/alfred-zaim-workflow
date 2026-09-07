#!/usr/bin/env python3
import json
import os
import sys
import unicodedata
import urllib.parse
import urllib.request

# 共通API通信モジュールの署名関数をインポート（または同一ロジックを呼び出し）
from zaim_api import generate_oauth_header

# ==============================================================================
# 1. パス & 定数定義 (alfred_workflow_data への保存)
# ==============================================================================
data_dir = os.environ.get("alfred_workflow_data")
if not data_dir:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    data_dir = BASE_DIR

os.makedirs(data_dir, exist_ok=True)

CONFIG_FILE = os.path.join(data_dir, "config.json")
TEMP_TOKEN_FILE = os.path.join(data_dir, ".request_token.json")

REQUEST_TOKEN_URL = "https://api.zaim.net/v2/auth/request"
AUTHORIZE_URL = "https://auth.zaim.net/users/auth"
ACCESS_TOKEN_URL = "https://api.zaim.net/v2/auth/access"


# ==============================================================================
# 2. 補助関数 (NFC正規化 & 通信ヘルパー)
# ==============================================================================
def normalize_text(text: str) -> str:
    """macOS特有のNFD(濁点分離)をNFCに変換し、トリムを行う"""
    if not text:
        return ""
    return unicodedata.normalize("NFC", text).strip()


def send_oauth_post(url, oauth_params, post_data=None):
    """OAuth 1.0a 認証用の POST リクエスト（フォームデコードレスポンス用）"""
    if post_data is None:
        post_data = {}

    auth_header = generate_oauth_header(
        url=url,
        method="POST",
        params={**oauth_params, **post_data},
        consumer_key=oauth_params.get("consumer_key", ""),
        consumer_secret=oauth_params.get("consumer_secret", ""),
        token=oauth_params.get("token", ""),
        token_secret=oauth_params.get("token_secret", ""),
    )

    data_encoded = urllib.parse.urlencode(post_data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data_encoded,
        headers={
            "Authorization": auth_header,
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Alfred-Zaim-Workflow/1.0",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=10) as response:
        res_body = response.read().decode("utf-8")
        # レスポンス (oauth_token=xxx&oauth_token_secret=yyy...) を辞書に変換
        return dict(urllib.parse.parse_qsl(res_body))


# ==============================================================================
# 3. 認証ロジック
# ==============================================================================
def start_login(consumer_id: str, consumer_secret: str):
    """Step 1: Request Token を取得し、認可ページ URL を生成・出力"""
    oauth_params = {
        "consumer_key": consumer_id,
        "consumer_secret": consumer_secret,
        "token": "",
        "token_secret": "",
    }

    try:
        # callback_uri="oob" (Out of Band / PIN入力方式)
        res_data = send_oauth_post(
            REQUEST_TOKEN_URL,
            oauth_params,
            post_data={"oauth_callback": "oob"},
        )
    except Exception as e:
        sys.stderr.write(f"エラー: リクエストトークン取得失敗 ({e})\n")
        sys.exit(1)

    req_token = res_data.get("oauth_token")
    req_secret = res_data.get("oauth_token_secret")

    if not req_token or not req_secret:
        sys.stderr.write("エラー: 有効な Request Token が取得できませんでした\n")
        sys.exit(1)

    # PIN検証用に一時ファイルへ退避
    temp_data = {
        "consumer_id": consumer_id,
        "consumer_secret": consumer_secret,
        "request_token": req_token,
        "request_token_secret": req_secret,
    }
    with open(TEMP_TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(temp_data, f, ensure_ascii=False, indent=2)

    # 認証用 URL を生成
    auth_url = f"{AUTHORIZE_URL}?oauth_token={urllib.parse.quote(req_token)}"

    # Alfred の Open URL ノードへ渡すため、末尾改行なしで出力
    print(auth_url, end="")


def verify_pin(pin_code: str):
    """Step 2: PIN (verifier) を使って Access Token を取得し config.json に保存"""
    pin_code = normalize_text(pin_code)

    if not pin_code or not os.path.exists(TEMP_TOKEN_FILE):
        sys.stderr.write(
            "エラー: 先に login モードで認証を開始してください\n"
        )
        sys.exit(1)

    with open(TEMP_TOKEN_FILE, "r", encoding="utf-8") as f:
        temp_data = json.load(f)

    consumer_id = temp_data["consumer_id"]
    consumer_secret = temp_data["consumer_secret"]
    req_token = temp_data["request_token"]
    req_secret = temp_data["request_token_secret"]

    oauth_params = {
        "consumer_key": consumer_id,
        "consumer_secret": consumer_secret,
        "token": req_token,
        "token_secret": req_secret,
    }

    try:
        # PIN (oauth_verifier) を付与して Access Token を請求
        res_data = send_oauth_post(
            ACCESS_TOKEN_URL, oauth_params, post_data={"oauth_verifier": pin_code}
        )
    except Exception as e:
        sys.stderr.write(
            f"エラー: アクセストークン取得失敗 (PIN不一致等: {e})\n"
        )
        sys.exit(1)

    access_token = res_data.get("oauth_token")
    access_token_secret = res_data.get("oauth_token_secret")

    if not access_token or not access_token_secret:
        sys.stderr.write("エラー: 有効な Access Token が取得できませんでした\n")
        sys.exit(1)

    # config.json に保存 (各モジュールで読み込めるようキー名を統一)
    config_data = {
        "consumer_id": consumer_id,
        "consumer_secret": consumer_secret,
        "access_token": access_token,
        "access_token_secret": access_token_secret,
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config_data, f, ensure_ascii=False, indent=2)

    # 一時ファイルの削除
    if os.path.exists(TEMP_TOKEN_FILE):
        try:
            os.remove(TEMP_TOKEN_FILE)
        except Exception:
            pass

    print("Zaim の認証が完了しました！config.json を生成しました。", end="")


# ==============================================================================
# 4. エントリポイント
# ==============================================================================
if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""

    if mode == "login":
        args = sys.argv[2:]

        if len(args) == 1:
            parts = args[0].strip().split()
        elif len(args) >= 2:
            parts = args
        else:
            parts = []

        if len(parts) < 2:
            sys.stderr.write(
                "使用法: auth-zaim <consumer_id> <consumer_secret>\n"
            )
            sys.exit(1)

        c_id = normalize_text(parts[0])
        c_secret = normalize_text(parts[1])
        start_login(c_id, c_secret)

    elif mode == "pin":
        if len(sys.argv) < 3:
            sys.stderr.write("使用法: pin-zaim <認証コード>\n")
            sys.exit(1)
        verify_pin(sys.argv[2])

    else:
        sys.stderr.write(
            "不正なモードです (login / pin を指定してください)\n"
        )
        sys.exit(1)
