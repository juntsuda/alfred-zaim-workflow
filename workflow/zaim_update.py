#!/usr/bin/env python3
import json
import os
import sys
import unicodedata

# 共通API通信モジュールのインポート
from zaim_api import zaim_request

# ==============================================================================
# 1. パス & 定数定義
# ==============================================================================
data_dir = os.environ.get("alfred_workflow_data")
if not data_dir:
  data_dir = os.path.dirname(os.path.abspath(__file__))
os.makedirs(data_dir, exist_ok=True)

cache_dir = os.environ.get("alfred_workflow_cache")
if not cache_dir:
  cache_dir = data_dir
os.makedirs(cache_dir, exist_ok=True)

CACHE_MONEY_FILE = os.path.join(cache_dir, "zaim_money_cache.json")
CACHE_MASTER_FILE = os.path.join(cache_dir, "zaim_master_cache.json")


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
  genre_id_str = str(int(new_value))
  payload["genre_id"] = int(genre_id_str)

  # ★★★ キャッシュから親カテゴリIDを名前経由で逆引き・自動補完 ★★★
  if os.path.exists(CACHE_MASTER_FILE):
    try:
      with open(CACHE_MASTER_FILE, "r", encoding="utf-8") as f:
        master = json.load(f)
        categories = master.get("categories", {})  # {"4834396": "交通"}
        genres = master.get(
            "genres", {}
        )  # {"22560234": "交通 ＞ 鉄道運賃"}

        genre_full_name = genres.get(genre_id_str, "")
        if " ＞ " in genre_full_name:
          parent_cat_name = genre_full_name.split(" ＞ ", 1)[0].strip()
          # カテゴリ名から ID を検索
          for cat_id, cat_name in categories.items():
            if cat_name == parent_cat_name:
              payload["category_id"] = int(cat_id)
              break
    except Exception as e:
      sys.stderr.write(f"マスタキャッシュ読み込み警告: {e}\n")

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