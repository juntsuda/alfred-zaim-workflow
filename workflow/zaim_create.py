#!/usr/bin/env python3
import datetime
import json
import os
import sys

# 共通API通信モジュールのインポート
from zaim_api import zaim_request

# ==============================================================================
# 1. パス & キャッシュ設定
# ==============================================================================
cache_dir = os.environ.get("alfred_workflow_cache")
if not cache_dir:
  cache_dir = os.environ.get("alfred_workflow_data") or os.path.dirname(
      os.path.abspath(__file__)
  )
os.makedirs(cache_dir, exist_ok=True)

CACHE_MONEY_FILE = os.path.join(cache_dir, "zaim_money_cache.json")
CACHE_MASTER_FILE = os.path.join(cache_dir, "zaim_master_cache.json")


def clean_id(val) -> int:
  """安全に整数IDに変換する"""
  if not val:
    return 0
  s = str(val).strip()
  if s.isdigit() and s != "0":
    return int(s)
  return 0


# ==============================================================================
# 2. 環境変数 (Variables) のパース
# ==============================================================================
mode = os.environ.get("zaim_mode", "payment").strip().lower()
if mode not in ["payment", "income", "transfer"]:
  mode = "payment"

# 金額 (zaim_add.py と同様に int 化)
raw_amount = os.environ.get("amount") or os.environ.get("current_amount", "0")
try:
  amount_int = int(raw_amount)
except ValueError:
  amount_int = 0

# 日付
date = os.environ.get("date") or os.environ.get("current_date", "")
if not date.strip():
  date = datetime.date.today().isoformat()

# 各種 ID の取得
c_id = clean_id(os.environ.get("category_id"))
g_id = clean_id(os.environ.get("genre_id"))
f_id = clean_id(os.environ.get("from_account_id"))
t_id = clean_id(os.environ.get("to_account_id"))

place = os.environ.get("place", "").strip()
comment = os.environ.get("comment", "").strip()

# ==============================================================================
# 3. カテゴリID・ジャンルIDの確実な解決 (zaim_add.py の安全性を取り入れる)
# ==============================================================================
# もし g_id がある場合、マスタキャッシュのキー構造から正しい category_id を厳密に逆引き
if g_id and os.path.exists(CACHE_MASTER_FILE):
  try:
   with open(CACHE_MASTER_FILE, "r", encoding="utf-8") as f:
      master = json.load(f)
      categories = master.get("categories", {})  # {"4834396": "交通"}
      genres = master.get("genres", {})  # {"22560234": "交通 ＞ 鉄道運賃"}

      genre_str = str(g_id)
      if genre_str in genres:
        genre_full_name = genres[genre_str]
        if " ＞ " in genre_full_name:
          parent_name = genre_full_name.split(" ＞ ", 1)[0].strip()
          for cat_key, cat_val in categories.items():
            if cat_val == parent_name:
              c_id = int(cat_key)
              break
  except Exception:
    pass

# 万が一 category_id が取れなかった場合のフォールバック（zaim_add.pyのデフォルト値を利用）
if not c_id and mode == "payment":
  c_id = 4834408  # その他支出
  g_id = 22560320  # その他

# ==============================================================================
# 4. ペイロード構築 (zaim_add.py と全く同じ構造)
# ==============================================================================
if mode == "payment":
  url = "https://api.zaim.net/v2/home/money/payment"
  payload = {
      "category_id": c_id,
      "genre_id": g_id,
      "price": amount_int,
      "amount": amount_int,
      "date": date,
  }
  if f_id:
    payload["from_account_id"] = f_id
  if place:
    payload["place"] = place
  if comment:
    payload["comment"] = comment

elif mode == "income":
  url = "https://api.zaim.net/v2/home/money/income"
  payload = {
      "category_id": c_id,
      "genre_id": g_id,
      "price": amount_int,
      "amount": amount_int,
      "date": date,
  }
  if t_id:
    payload["to_account_id"] = t_id
  if place:
    payload["place"] = place
  if comment:
    payload["comment"] = comment

elif mode == "transfer":
  url = "https://api.zaim.net/v2/home/money/transfer"
  payload = {
      "price": amount_int,
      "amount": amount_int,
      "date": date,
  }
  if f_id:
    payload["from_account_id"] = f_id
  if t_id:
    payload["to_account_id"] = t_id
  if comment:
    payload["comment"] = comment

# ==============================================================================
# 5. API 送信 & キャッシュクリア
# ==============================================================================
try:
  res_data = zaim_request("POST", url, params=payload)

  if os.path.exists(CACHE_MONEY_FILE):
    try:
      os.remove(CACHE_MONEY_FILE)
    except Exception:
      pass

  new_zaim_id = str(res_data.get("money", {}).get("id", ""))
  print(new_zaim_id, end="")

except Exception as e:
  sys.stderr.write(f"エラー: 新規記録に失敗しました ({e})\n")
  sys.exit(1)