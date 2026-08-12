#!/usr/bin/env python3
import json
import os
import sys
import unicodedata

# ==============================================================================
# 1. パス & 定数定義
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "lib"))

from requests_oauthlib import OAuth1Session

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
TEMP_TOKEN_FILE = os.path.join(BASE_DIR, ".request_token.json")

REQUEST_TOKEN_URL = "https://api.zaim.net/v2/auth/request"
AUTHORIZE_URL = "https://auth.zaim.net/users/auth"
ACCESS_TOKEN_URL = "https://api.zaim.net/v2/auth/access"


# ==============================================================================
# 2. 補助関数 (NFC正規化)
# ==============================================================================
def normalize_text(text: str) -> str:
  """macOS特有のNFD(濁点分離)をNFCに変換し、トリムを行う"""
  if not text:
    return ""
  return unicodedata.normalize("NFC", text).strip()


# ==============================================================================
# 3. 認証ロジック
# ==============================================================================
def start_login(consumer_id: str, consumer_secret: str):
  """Step 1: Consumer ID / Secret を受け取って認可ページの URL を生成・出力する"""
  oauth = OAuth1Session(
      consumer_id, client_secret=consumer_secret, callback_uri="oob"
  )

  try:
    fetch_response = oauth.fetch_request_token(REQUEST_TOKEN_URL)
  except Exception as e:
    sys.stderr.write(f"エラー: リクエストトークン取得失敗 ({e})\n")
    sys.exit(1)

  req_token = fetch_response.get("oauth_token")
  req_secret = fetch_response.get("oauth_token_secret")

  # PIN検証用に一時ファイルへ退避
  temp_data = {
      "consumer_id": consumer_id,
      "consumer_secret": consumer_secret,
      "request_token": req_token,
      "request_token_secret": req_secret,
  }
  with open(TEMP_TOKEN_FILE, "w", encoding="utf-8") as f:
    json.dump(temp_data, f, ensure_ascii=False, indent=2)

  # 認証用 URL を取得
  auth_url = oauth.authorization_url(AUTHORIZE_URL)

  # Alfred の Open URL ノードへ渡すため、末尾改行なしで出力
  print(auth_url, end="")


def verify_pin(pin_code: str):
  """Step 2: PIN を使ってアクセストークンを取得し config.json に保存"""
  pin_code = normalize_text(pin_code)

  if not pin_code or not os.path.exists(TEMP_TOKEN_FILE):
    sys.stderr.write(
        "エラー: 先に auth-zaim <consumer_id> <consumer_secret>"
        " を実行してください\n"
    )
    sys.exit(1)

  with open(TEMP_TOKEN_FILE, "r", encoding="utf-8") as f:
    temp_data = json.load(f)

  consumer_id = temp_data["consumer_id"]
  consumer_secret = temp_data["consumer_secret"]

  oauth = OAuth1Session(
      consumer_id,
      client_secret=consumer_secret,
      resource_owner_key=temp_data["request_token"],
      resource_owner_secret=temp_data["request_token_secret"],
      verifier=pin_code,
  )

  try:
    oauth_tokens = oauth.fetch_access_token(ACCESS_TOKEN_URL)
  except Exception as e:
    sys.stderr.write(
        f"エラー: アクセストークン取得失敗 (PIN不一致等: {e})\n"
    )
    sys.exit(1)

  # config.json に保存
  config_data = {
      "consumer_id": consumer_id,
      "consumer_secret": consumer_secret,
      "access_token": oauth_tokens.get("oauth_token"),
      "access_token_secret": oauth_tokens.get("oauth_token_secret"),
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
    sys.stderr.write("不正なモードです (login / 認証コード を指定してください)\n")
    sys.exit(1)