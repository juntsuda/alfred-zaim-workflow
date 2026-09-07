#!/usr/bin/env python3
import csv
import json
import os
import sys

# 共通API通信モジュールのインポート
from zaim_api import zaim_request

DESKTOP_DIR = os.path.expanduser("~/Desktop")


def export_endpoint_to_csv(endpoint_url: str, key_name: str, output_filename: str):
  """Zaim API からデータを取得し、全フィールドをデスクトップ上の CSV に出力する"""
  try:
    res_data = zaim_request("GET", endpoint_url)
  except Exception as e:
    print(f"❌ [{output_filename}] 取得失敗: {e}")
    return

  data_list = res_data.get(key_name, [])
  if not data_list:
    print(f"⚠️ [{output_filename}] データが存在しません。")
    return

  fieldnames = []
  for row in data_list:
    for key in row.keys():
      if key not in fieldnames:
        fieldnames.append(key)

  os.makedirs(DESKTOP_DIR, exist_ok=True)
  csv_path = os.path.join(DESKTOP_DIR, output_filename)

  with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()

    for row in data_list:
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

  export_endpoint_to_csv(
      "https://api.zaim.net/v2/home/category",
      "categories",
      "zaim_categories_full.csv",
  )
  export_endpoint_to_csv(
      "https://api.zaim.net/v2/home/genre", "genres", "zaim_genres_full.csv"
  )
  export_endpoint_to_csv(
      "https://api.zaim.net/v2/home/account",
      "accounts",
      "zaim_accounts_full.csv",
  )


if __name__ == "__main__":
  main()
