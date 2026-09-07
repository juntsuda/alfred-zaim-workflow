#!/usr/bin/env python3
import json
import os
import sys
import unicodedata
from datetime import datetime

# 共通API通信モジュールのインポート
from zaim_api import zaim_request

# ==============================================================================
# 1. パス & 定数定義
# ==============================================================================
# --- 永続データ用 (config.json 等) ---
data_dir = os.environ.get("alfred_workflow_data")
if not data_dir:
  data_dir = os.path.dirname(os.path.abspath(__file__))
os.makedirs(data_dir, exist_ok=True)

# --- 一時キャッシュ用 (money キャッシュ等) ---
cache_dir = os.environ.get("alfred_workflow_cache")
if not cache_dir:
  cache_dir = data_dir  # 環境変数がない場合のフォールバック
os.makedirs(cache_dir, exist_ok=True)

# キャッシュファイルは cache_dir 配下に配置
CACHE_MONEY_FILE = os.path.join(cache_dir, "zaim_money_cache.json")


DEFAULT_CATEGORY_ID = 4834408
DEFAULT_GENRE_ID = 22560320


# ==============================================================================
# 2. 補助関数 (NFC正規化 & テキストパース)
# ==============================================================================
def normalize_text(text: str) -> str:
  if not text:
    return ""
  return unicodedata.normalize("NFC", text).strip()


def parse_line(line_str):
  line_str = line_str.strip()
  if not line_str:
    return None, None

  parts = line_str.split(None, 1)
  amount_str = parts[0]
  comment = parts[1] if len(parts) > 1 else ""

  amount_clean = amount_str.translate(
      str.maketrans("０１２３４５６７８９", "0123456789")
  ).replace(",", "")

  if not amount_clean.isdigit():
    return None, None

  return int(amount_clean), comment


# ==============================================================================
# 3. メイン処理
# ==============================================================================
action_mode = os.environ.get("zaim_action")

# --- POST実行処理（Run Script から呼ばれた場合） ---
if action_mode in ["add_post", "add_batch"]:
  raw_arg = sys.argv[1] if len(sys.argv) > 1 else ""
  raw_input = normalize_text(raw_arg)

  if not raw_input:
    sys.stderr.write("エラー: 入力テキストが空です\n")
    sys.exit(1)

  today_str = datetime.now().strftime("%Y-%m-%d")
  lines = raw_input.splitlines()

  success_count = 0
  total_amount = 0
  last_new_id = None

  for line in lines:
    amount, comment = parse_line(line)
    if amount is None:
      continue

    payload = {
        "category_id": DEFAULT_CATEGORY_ID,
        "genre_id": DEFAULT_GENRE_ID,
        "price": amount,
        "amount": amount,
        "date": today_str,
        "comment": comment,
    }

    try:
      res_data = zaim_request(
          "POST", "https://api.zaim.net/v2/home/money/payment", params=payload
      )
      success_count += 1
      total_amount += amount
      last_new_id = res_data.get("money", {}).get("id")
    except Exception as e:
      sys.stderr.write(f"Zaim API エラー: {e} (対象行: '{line}')\n")

  if success_count > 0 and os.path.exists(CACHE_MONEY_FILE):
    try:
      os.remove(CACHE_MONEY_FILE)
    except Exception:
      pass

  if action_mode == "add_post":
    if last_new_id:
      print(str(last_new_id), end="")
      sys.exit(0)
    else:
      sys.stderr.write("エラー: 単発登録に失敗しました\n")
      sys.exit(1)

  elif action_mode == "add_batch":
    if success_count > 0:
      print(f"{success_count}件登録完了 (合計: ¥{total_amount:,})")
      sys.exit(0)
    else:
      print("登録に失敗しました")
      sys.exit(1)

# --- Script Filter プレビュー表示 ---
raw_arg = sys.argv[1] if len(sys.argv) > 1 else ""
raw_input = normalize_text(raw_arg)

amount, comment = parse_line(raw_input)
today_str = datetime.now().strftime("%Y-%m-%d")

if amount is None:
  print(
      json.dumps(
          {
              "items": [{
                  "title": "金額 メモ を入力してください",
                  "subtitle": "例: 1200 ランチ / 0 散歩メモ",
                  "valid": False,
              }]
          },
          ensure_ascii=False,
      )
  )
  sys.exit(0)

subtitle_text = (
    f"日付: {today_str} | カテゴリ: その他支出 ＞ その他 | メモ:"
    f" {comment if comment else '(なし)'}"
)

print(
    json.dumps(
        {
            "items": [{
                "title": f"➕ ¥{amount:,} を支出として登録",
                "subtitle": subtitle_text,
                "arg": raw_input,
                "variables": {
                    "zaim_action": "add_post",
                    "zaim_amount": str(amount),
                    "zaim_comment": comment,
                },
            }]
        },
        ensure_ascii=False,
    )
)