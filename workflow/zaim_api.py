#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
import urllib.request

# ==============================================================================
# 1. 設定ファイル (config.json) のパス解決
# ==============================================================================
data_dir = os.environ.get("alfred_workflow_data")
if not data_dir:
  data_dir = os.path.dirname(os.path.abspath(__file__))

os.makedirs(data_dir, exist_ok=True)
CONFIG_PATH = os.path.join(data_dir, "config.json")


def load_config():
  """設定ファイルを読み込む"""
  if not os.path.exists(CONFIG_PATH):
    sys.stderr.write(
        f"エラー: config.json が見つかりません ({CONFIG_PATH})。\n"
    )
    sys.exit(1)
  with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    return json.load(f)


# ==============================================================================
# 2. OAuth 1.0a 署名 & API通信 (標準ライブラリのみ)
# ==============================================================================
def generate_oauth_header(
    url, method, params, consumer_key, consumer_secret, token, token_secret
):
  """標準ライブラリのみで OAuth 1.0a Authorization ヘッダーを生成"""
  oauth_params = {
      "oauth_consumer_key": str(consumer_key),
      "oauth_nonce": str(int(time.time() * 1000)),
      "oauth_signature_method": "HMAC-SHA1",
      "oauth_timestamp": str(int(time.time())),
      "oauth_token": str(token),
      "oauth_version": "1.0",
  }

  # ★ 全てのキーと値を完全に str 型に変換して統合
  clean_params = {str(k): str(v) for k, v in params.items()}
  all_params = {**clean_params, **oauth_params}

  sorted_params = "&".join(
      f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
      for k, v in sorted(all_params.items())
  )

  base_string = f"{method.upper()}&{urllib.parse.quote(url, safe='')}&{urllib.parse.quote(sorted_params, safe='')}"
  signing_key = f"{urllib.parse.quote(consumer_secret, safe='')}&{urllib.parse.quote(token_secret, safe='')}".encode(
      "utf-8"
  )

  hashed = hmac.new(signing_key, base_string.encode("utf-8"), hashlib.sha1)
  signature = base64.b64encode(hashed.digest()).decode("utf-8")

  oauth_params["oauth_signature"] = signature

  header_parts = ", ".join(
      f'{k}="{urllib.parse.quote(v, safe="")}"'
      for k, v in sorted(oauth_params.items())
  )
  return f"OAuth {header_parts}"


def zaim_request(method, url, params=None):
  """Zaim API へリクエストを送信する統一関数 (GET / POST / PUT 対応)"""
  if params is None:
    params = {}

  cfg = load_config()

  c_key = cfg.get("consumer_key") or cfg.get("consumer_id", "")
  c_secret = cfg.get("consumer_secret", "")
  a_token = cfg.get("access_token") or cfg.get("oauth_token", "")
  a_token_secret = cfg.get("access_token_secret") or cfg.get(
      "oauth_token_secret", ""
  )

  method_upper = method.upper()

  # ★ 送信用ディクショナリのキーと値を全て str 型に事前揃え
  stringified_params = {str(k): str(v) for k, v in params.items()}

  auth_header = generate_oauth_header(
      url=url,
      method=method_upper,
      params=stringified_params,
      consumer_key=c_key,
      consumer_secret=c_secret,
      token=a_token,
      token_secret=a_token_secret,
  )

  headers = {
      "Authorization": auth_header,
      "User-Agent": "Alfred-Zaim-Workflow/1.0",
  }

  req_url = url
  data_encoded = None

  if method_upper == "GET":
    if stringified_params:
      query_str = urllib.parse.urlencode(stringified_params)
      req_url = f"{url}?{query_str}"
  elif method_upper in ["POST", "PUT"]:
    # フォームデータとして文字列エンコード
    data_encoded = urllib.parse.urlencode(stringified_params).encode("utf-8")
    headers["Content-Type"] = "application/x-www-form-urlencoded"

  req = urllib.request.Request(
      req_url, data=data_encoded, headers=headers, method=method_upper
  )

  with urllib.request.urlopen(req, timeout=10) as response:
    res_body = response.read().decode("utf-8")
    return json.loads(res_body)