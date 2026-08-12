#!/usr/bin/env python3
import json
import os
import sys
import unicodedata

# ==============================================================================
# 1. パス & ディレクトリ定義 (環境に依存しない動的判定)
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "lib"))

from requests_oauthlib import OAuth1Session

# --- Bundle ID の自動判定 ---
plist_path = os.path.join(BASE_DIR, "info.plist")
bundle_id = "com.user.zaim"  # 未設定時のフォールバック

if os.path.exists(plist_path):
  try:
    with open(plist_path, "rb") as fp:
      plist = plistlib.load(fp)
      if plist.get("bundleid"):
        bundle_id = plist["bundleid"]
  except Exception:
    pass

# --- キャッシュ & 設定ファイルの絶対パス指定 ---
LOCAL_CACHE_DIR = os.path.expanduser(
    f"~/Library/Caches/com.runningwithcrayons.Alfred/Workflow Data/{bundle_id}"
)
os.makedirs(LOCAL_CACHE_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
CACHE_MONEY_FILE = os.path.join(LOCAL_CACHE_DIR, "zaim_money_cache.json")


# ==============================================================================
# 2. 補助関数 (NFC正規化)
# ==============================================================================
def normalize_text(text: str) -> str:
  """macOS特有のNFD(濁点分離)をNFCに変換し、トリムを行う"""
  if not text:
    return ""
  return unicodedata.normalize("NFC", text).strip()


# ==============================================================================
# 3. API 認証 & クライアント初期化
# ==============================================================================
try:
  with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    config = json.load(f)
except FileNotFoundError:
  sys.stderr.write("エラー: config.json が見つかりません。auth-zaim を実行してください。\n")
  sys.exit(1)

oauth = OAuth1Session(
    config["consumer_id"],
    client_secret=config["consumer_secret"],
    resource_owner_key=config["access_token"],
    resource_owner_secret=config["access_token_secret"],
)

# ==============================================================================
# 4. メイン処理
# ==============================================================================
ZAIM_ID = os.environ.get("zaim_id")
ZAIM_MODE = os.environ.get("zaim_mode", "payment")
ZAIM_ACTION = os.environ.get("zaim_action")

CURRENT_AMOUNT = os.environ.get("current_amount")
CURRENT_DATE = os.environ.get("current_date")

raw_arg = sys.argv[1] if len(sys.argv) > 1 else ""
new_value = normalize_text(raw_arg)

if not ZAIM_ID or not ZAIM_ACTION:
  sys.stderr.write("エラー: 必須パラメータ (zaim_id または zaim_action) が不足しています\n")
  sys.exit(1)

# PUT ペイロードの構築
url = f"https://api.zaim.net/v2/home/money/{ZAIM_MODE}/{ZAIM_ID}"
payload = {"id": ZAIM_ID}

if CURRENT_AMOUNT is not None and CURRENT_AMOUNT != "":
  payload["amount"] = int(CURRENT_AMOUNT)

if CURRENT_DATE:
  payload["date"] = CURRENT_DATE

# 変更アクションに応じた上書き
target_name = ""
if ZAIM_ACTION == "edit_comment":
  payload["comment"] = new_value
  target_name = "メモ"
elif ZAIM_ACTION == "edit_amount":
  payload["amount"] = int(new_value)
  target_name = "金額"
elif ZAIM_ACTION == "edit_date":
  payload["date"] = new_value
  target_name = "日付"
elif ZAIM_ACTION == "edit_place":
  payload["place"] = new_value
  target_name = "場所"
elif ZAIM_ACTION == "edit_genre":
  payload["genre_id"] = int(new_value)
  target_name = "カテゴリ"
elif ZAIM_ACTION == "edit_account":
  if ZAIM_MODE == "payment":
    payload["from_account_id"] = int(new_value)
  elif ZAIM_MODE == "income":
    payload["to_account_id"] = int(new_value)
  target_name = "口座"

# API 送信
response = oauth.put(url, data=payload)

if response.status_code == 200:
  # 明細が更新されたため、ローカルの明細キャッシュを破棄
  if os.path.exists(CACHE_MONEY_FILE):
    try:
      os.remove(CACHE_MONEY_FILE)
    except Exception:
      pass

  # 改行を付与せずに stdout へ出力 (後続の External Trigger へ引き継ぐ)
  print(f"{ZAIM_ID}:{target_name}", end="")
else:
  sys.stderr.write(f"Zaim API エラー [{response.status_code}]: {response.text}\n")
  sys.exit(1)