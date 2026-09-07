#!/usr/bin/env python3
import json
import os
import sys
import unicodedata

# 共通API通信モジュールのインポート
from zaim_api import zaim_request

# ==============================================================================
# 1. パス & キャッシュ設定
# ==============================================================================
data_dir = os.environ.get("alfred_workflow_data")
if not data_dir:
  BASE_DIR = os.path.dirname(os.path.abspath(__file__))
  data_dir = BASE_DIR

CACHE_MONEY_FILE = os.path.join(data_dir, "zaim_money_cache.json")


def normalize_text(text: str) -> str:
  if not text:
    return ""
  return unicodedata.normalize("NFC", text).strip()


# ==============================================================================
# 2. メイン処理 (明細更新)
# ==============================================================================
ZAIM_ID = os.environ.get("zaim_id")
ZAIM_MODE = os.environ.get("zaim_mode", "payment")
ZAIM_ACTION = os.environ.get("zaim_action")

CURRENT_AMOUNT = os.environ.get("current_amount")
CURRENT_DATE = os.environ.get("current_date")

raw_arg = sys.argv[1] if len(sys.argv) > 1 else ""
new_value = normalize_text(raw_arg)

if not ZAIM_ID or not ZAIM_ACTION:
  sys.stderr.write(
      "エラー: 必須パラメータ (zaim_id または zaim_action) が不足しています\n"
  )
  sys.exit(1)

url = f"https://api.zaim.net/v2/home/money/{ZAIM_MODE}/{ZAIM_ID}"
payload = {"id": ZAIM_ID}

if CURRENT_AMOUNT is not None and CURRENT_AMOUNT != "":
  payload["amount"] = int(CURRENT_AMOUNT)

if CURRENT_DATE:
  payload["date"] = CURRENT_DATE

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

try:
  # PUT リクエストの送信
  zaim_request("PUT", url, params=payload)

  if os.path.exists(CACHE_MONEY_FILE):
    try:
      os.remove(CACHE_MONEY_FILE)
    except Exception:
      pass

  print(f"{ZAIM_ID}:{target_name}", end="")
except Exception as e:
  sys.stderr.write(f"Zaim API エラー: {e}\n")
  sys.exit(1)
