#!/usr/bin/env python3
import csv
import json
import os
import sys

# ==============================================================================
# 1. パス & 定数定義 (デスクトップ保存)
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "lib"))

from requests_oauthlib import OAuth1Session

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
DESKTOP_DIR = os.path.expanduser("~/Desktop")

# ==============================================================================
# 2. API 認証 & クライアント初期化
# ==============================================================================
try:
  with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    config = json.load(f)
except FileNotFoundError:
  print("❌ 設定ファイル (config.json) が見つかりません。auth-zaim を実行してください。")
  sys.exit(1)

oauth = OAuth1Session(
    config["consumer_id"],
    client_secret=config["consumer_secret"],
    resource_owner_key=config["access_token"],
    resource_owner_secret=config["access_token_secret"],
)


# ==============================================================================
# 3. エクスポート処理
# ==============================================================================
def export_endpoint_to_csv(endpoint_url: str, key_name: str, output_filename: str):
  """Zaim API からデータを取得し、全フィールドをデスクトップ上の CSV に出力する"""
  res = oauth.get(endpoint_url)
  if res.status_code != 200:
    print(
        f"❌ [{output_filename}] 取得失敗: ステータスコード {res.status_code}"
    )
    return

  data_list = res.json().get(key_name, [])
  if not data_list:
    print(f"⚠️ [{output_filename}] データが存在しません。")
    return

  # 1. 存在するすべてのフィールド（キー）を動的に集計
  fieldnames = []
  for row in data_list:
    for key in row.keys():
      if key not in fieldnames:
        fieldnames.append(key)

  # 2. デスクトップの CSV ファイルへの書き出し (utf-8-sig で Excel の文字化け防止)
  os.makedirs(DESKTOP_DIR, exist_ok=True)
  csv_path = os.path.join(DESKTOP_DIR, output_filename)

  with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()

    for row in data_list:
      # 配列や辞書型が含まれる場合は文字列化して保持
      formatted_row = {}
      for k, v in row.items():
        if isinstance(v, (dict, list)):
          formatted_row[k] = json.dumps(v, ensure_ascii=False)
        else:
          formatted_row[k] = v
      writer.writerow(formatted_row)

  print(
      f"✅ 出力完了: デスクトップ/{output_filename} ({len(data_list)} 件 /"
      f" フィールド数: {len(fieldnames)})"
  )


def main():
  print("Zaim API からマスターデータを取得してデスクトップへ出力します...\n")

  # 1. カテゴリ (カテゴリ大項目)
  export_endpoint_to_csv(
      "https://api.zaim.net/v2/home/category",
      "categories",
      "zaim_categories_full.csv",
  )

  # 2. ジャンル (カテゴリ小項目)
  export_endpoint_to_csv(
      "https://api.zaim.net/v2/home/genre", "genres", "zaim_genres_full.csv"
  )

  # 3. 口座情報
  export_endpoint_to_csv(
      "https://api.zaim.net/v2/home/account",
      "accounts",
      "zaim_accounts_full.csv",
  )


if __name__ == "__main__":
  main()