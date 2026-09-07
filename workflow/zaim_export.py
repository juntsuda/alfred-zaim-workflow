#!/usr/bin/env python3
import argparse
import calendar
import csv
from datetime import datetime, timedelta
import json
import os
import re
import sys
import unicodedata

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
CACHE_FILE = os.path.join(cache_dir, "zaim_master_cache.json")
CACHE_MONEY_FILE = os.path.join(cache_dir, "zaim_money_cache.json")


DEFAULT_DAYS = 90
RTM_DEFAULT_TAGS = "#賞味期限 #食材"

# ==============================================================================
# 2. 引数解析 & マスターデータロード
# ==============================================================================
parser = argparse.ArgumentParser()
parser.add_argument("--format", choices=["csv", "text", "rtm"], default="text")
parser.add_argument("query", nargs="?", default="")
args = parser.parse_args()

try:
  with open(CACHE_FILE, "r", encoding="utf-8") as f:
    master = json.load(f)
except Exception:
  master = {}

cat_map = master.get("categories", {})
genre_map = master.get("genres", {})
acc_map = master.get("accounts", {})

# ==============================================================================
# 3. クエリのパース
# ==============================================================================
raw_query_norm = unicodedata.normalize("NFC", args.query.strip())
tokens = raw_query_norm.split()

keywords = []
target_mode = None
start_date_filter = None
end_date_filter = None
allow_future = False
field_target = None

today = datetime.now().date()

for token in tokens:
  token_lower = token.lower()
  if token_lower.startswith(":"):
    if token_lower in [":支出", ":p", ":payment"]:
      target_mode = "payment"
    elif token_lower in [":収入", ":i", ":income"]:
      target_mode = "income"
    elif token_lower in [":振替", ":tr", ":transfer"]:
      target_mode = "transfer"
    elif token_lower in [":y", ":yesterday", ":昨日"]:
      yesterday = today - timedelta(days=1)
      start_date_filter = end_date_filter = yesterday.strftime("%Y-%m-%d")
    elif token_lower in [":t", ":today", ":今日"]:
      start_date_filter = end_date_filter = today.strftime("%Y-%m-%d")
    elif token_lower in [":w", ":week", ":今週"]:
      start_date_filter = (
          today - timedelta(days=today.weekday())
      ).strftime("%Y-%m-%d")
    elif token_lower in [":1w", ":7d"]:
      start_date_filter = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    elif token_lower in [":m", ":month", ":今月"]:
      start_date_filter = today.replace(day=1).strftime("%Y-%m-%d")
    elif token_lower in [":fm", ":fullmonth", ":今月全", ":今月フル"]:
      start_date_filter = today.replace(day=1).strftime("%Y-%m-%d")
      _, last_day = calendar.monthrange(today.year, today.month)
      end_date_filter = today.replace(day=last_day).strftime("%Y-%m-%d")
      allow_future = True
    elif token_lower in [":1m", ":30d"]:
      start_date_filter = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    elif token_lower in [":lm", ":lastmonth", ":先月"]:
      first_of_this_month = today.replace(day=1)
      last_day_of_last_month = first_of_this_month - timedelta(days=1)
      start_date_filter = last_day_of_last_month.replace(day=1).strftime(
          "%Y-%m-%d"
      )
      end_date_filter = last_day_of_last_month.strftime("%Y-%m-%d")
    elif token_lower in [":ty", ":thisyear", ":ytd", ":今年"]:
      start_date_filter = today.replace(month=1, day=1).strftime("%Y-%m-%d")
    elif token_lower in [":1y", ":365d", ":1年"]:
      try:
        one_year_ago = today.replace(year=today.year - 1)
      except ValueError:
        one_year_ago = today.replace(year=today.year - 1, day=28)
      start_date_filter = one_year_ago.strftime("%Y-%m-%d")
    elif token_lower in [":ly", ":lastyear", ":昨年"]:
      last_year = today.year - 1
      start_date_filter = f"{last_year}-01-01"
      end_date_filter = f"{last_year}-12-31"
    elif token_lower in [":g", ":genre", ":cat", ":ジャンル", ":カテゴリ"]:
      field_target = "genre"
    elif token_lower in [":s", ":shop", ":place", ":店舗", ":場所"]:
      field_target = "place"
    elif token_lower in [":a", ":acc", ":account", ":口座"]:
      field_target = "account"
    elif token_lower in [":memo", ":comment", ":メモ"]:
      field_target = "memo"
  elif re.match(r"^\d{4}-\d{2}-\d{2}-\d{4}-\d{2}-\d{2}$", token_lower):
    parts = token_lower.split("-")
    d1 = f"{parts[0]}-{parts[1]}-{parts[2]}"
    d2 = f"{parts[3]}-{parts[4]}-{parts[5]}"
    start_date_filter, end_date_filter = sorted([d1, d2])
  elif re.match(r"^\d{4}-\d{2}-\d{2}$", token_lower):
    start_date_filter = end_date_filter = token_lower
  else:
    keywords.append(token_lower)

search_query = " ".join(keywords)

# ==============================================================================
# 4. 明細データの取得とフィルタリング
# ==============================================================================
api_start_date = (
    start_date_filter
    if start_date_filter
    else (today - timedelta(days=DEFAULT_DAYS)).strftime("%Y-%m-%d")
)
today_str = today.strftime("%Y-%m-%d")

filtered_items = []

try:
  res_data = zaim_request(
      "GET",
      "https://api.zaim.net/v2/home/money",
      params={"start_date": api_start_date, "limit": 100},
  )
  money_list = res_data.get("money", [])

  target_items = [
      item
      for item in money_list
      if allow_future or item.get("date", "") <= today_str
  ]
  target_items.sort(key=lambda x: x.get("date", ""), reverse=False)

  for item in target_items:
    mode = item.get("mode", "payment")
    date = item.get("date", "")

    if target_mode and mode != target_mode:
      continue
    if end_date_filter and date > end_date_filter:
      continue
    if start_date_filter and date < start_date_filter:
      continue

    comment = item.get("comment", "").strip()
    raw_place = item.get("place", "").strip()
    amount = item.get("amount", 0)

    cat_id_str = str(item.get("category_id", ""))
    genre_id_str = str(item.get("genre_id", ""))
    from_id_val = (
        item.get("from_account_id")
        if item.get("from_account_id") is not None
        else item.get("account_id")
    )
    to_id_val = item.get("to_account_id")

    from_id_str = str(from_id_val) if from_id_val is not None else ""
    to_id_str = str(to_id_val) if to_id_val is not None else ""

    from_acc = acc_map.get(from_id_str) or (
        "お財布" if from_id_str in ["1", "0", ""] else f"口座未設定({from_id_str})"
    )
    to_acc = acc_map.get(to_id_str) or (
        "お財布" if to_id_str in ["1", "0", ""] else f"口座未設定({to_id_str})"
    )

    category_large = cat_map.get(cat_id_str, "-")
    genre_full = genre_map.get(genre_id_str, "")
    if " ＞ " in genre_full:
      category_sub = genre_full.split(" ＞ ", 1)[1]
    else:
      category_sub = genre_full if genre_full else "-"

    cat_disp_name = genre_full or category_large

    if field_target == "genre":
      search_raw = f"{cat_disp_name}"
    elif field_target == "place":
      search_raw = f"{raw_place}"
    elif field_target == "account":
      search_raw = f"{from_acc} {to_acc}"
    elif field_target == "memo":
      search_raw = f"{comment}"
    else:
      search_raw = (
          f"{comment} {raw_place} {cat_disp_name} {from_acc} {to_acc} {amount}"
          f" {date}"
      )

    search_target = unicodedata.normalize("NFC", search_raw).lower()

    if search_query and not all(k in search_target for k in keywords):
      continue

    filtered_items.append({
        "date": date,
        "mode": mode,
        "category_large": category_large,
        "category_sub": category_sub,
        "from_acc": from_acc,
        "to_acc": to_acc,
        "amount": amount,
        "place": raw_place,
        "comment": comment,
    })
except Exception as e:
  sys.stderr.write(f"Zaim 取得エラー: {e}\n")

# ==============================================================================
# 5. フォーマット別出力処理
# ==============================================================================
if args.format == "csv":
  OFFICIAL_HEADERS = [
      "日付",
      "方法",
      "カテゴリ",
      "カテゴリの内訳",
      "支払元",
      "入金先",
      "品目",
      "メモ",
      "お店",
      "通貨",
      "収入",
      "支出",
      "振替",
      "残高調整",
      "通貨変換前の金額",
      "集計の設定",
  ]

  desktop_dir = os.path.expanduser("~/Desktop")
  filename = f"Zaim.{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"
  filepath = os.path.join(desktop_dir, filename)

  with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f)
    writer.writerow(OFFICIAL_HEADERS)

    for item in filtered_items:
      mode = item["mode"]
      amount = item["amount"]

      income = amount if mode == "income" else 0
      payment = amount if mode == "payment" else 0
      transfer = amount if mode == "transfer" else 0

      cat_main = item["category_large"] if mode != "transfer" else "-"
      cat_sub = item["category_sub"] if mode != "transfer" else "-"
      from_a = item["from_acc"] if mode != "income" else "-"
      to_a = item["to_acc"] if mode != "payment" else "-"
      place_str = item["place"] if item["place"] else "-"

      writer.writerow([
          item["date"],
          mode,
          cat_main,
          cat_sub,
          from_a,
          to_a,
          "",
          item["comment"],
          place_str,
          "JPY",
          income,
          payment,
          transfer,
          0,
          amount,
          "常に集計に含める",
      ])

  print(f"デスクトップに保存しました:\n{filename}", end="")

elif args.format == "text":
  period_str = f"{start_date_filter or api_start_date} 〜 {end_date_filter or (today_str if not allow_future else '月末')}"
  query_str = f"（検索: {' '.join(keywords)}）" if keywords else ""

  payments = [i for i in filtered_items if i["mode"] == "payment"]
  incomes = [i for i in filtered_items if i["mode"] == "income"]
  transfers = [i for i in filtered_items if i["mode"] == "transfer"]

  sum_p = sum(i["amount"] for i in payments)
  sum_i = sum(i["amount"] for i in incomes)
  sum_t = sum(i["amount"] for i in transfers)

  lines = [f"集計期間：{period_str}{query_str}", "-" * 40, ""]

  if payments:
    lines.append(f"■ 支出項目：合計 ¥{sum_p:,} ({len(payments)}件)")
    for i in payments:
      place_str = f" / {i['place']}" if i["place"] else ""
      memo_str = f" [{i['comment']}]" if i["comment"] else ""
      cat_full = (
          f"{i['category_large']} ＞ {i['category_sub']}"
          if i["category_sub"] != "-"
          else i["category_large"]
      )
      lines.append(
          f"・{i['date']} [{cat_full}] ¥{i['amount']:,}"
          f" ({i['from_acc']}){place_str}{memo_str}"
      )
    lines.append("")

  if incomes:
    lines.append(f"■ 収入項目：合計 ¥{sum_i:,} ({len(incomes)}件)")
    for i in incomes:
      place_str = f" / {i['place']}" if i["place"] else ""
      memo_str = f" [{i['comment']}]" if i["comment"] else ""
      cat_full = (
          f"{i['category_large']} ＞ {i['category_sub']}"
          if i["category_sub"] != "-"
          else i["category_large"]
      )
      lines.append(
          f"・{i['date']} [{cat_full}] ¥{i['amount']:,}"
          f" ({i['to_acc']}){place_str}{memo_str}"
      )
    lines.append("")

  if transfers:
    lines.append(f"■ 振替項目：合計 ¥{sum_t:,} ({len(transfers)}件)")
    for i in transfers:
      memo_str = f" [{i['comment']}]" if i["comment"] else ""
      lines.append(
          f"・{i['date']} [振替] ¥{i['amount']:,} ({i['from_acc']} ➔"
          f" {i['to_acc']}){memo_str}"
      )
    lines.append("")

  lines.append("-" * 40)
  lines.append(f"総合計: 支出 ¥{sum_p:,} / 収入 ¥{sum_i:,} / 振替 ¥{sum_t:,}")
  print("\n".join(lines))

elif args.format == "rtm":
  rtm_lines = []

  for item in filtered_items:
    cat_full = (
        f"{item['category_large']} {item['category_sub']}"
        if item["category_sub"] != "-"
        else item["category_large"]
    )
    target_text = (
        item["comment"]
        if item["comment"]
        else f"{cat_full} {item['place']}".strip()
    )
    pattern = r"^(.*?)\s*((\d{1,4}[/-])?\d{1,2}[/-]\d{1,2})\s*期限"
    match = re.search(pattern, target_text)

    if match:
      item_name = match.group(1).strip()
      due_date = match.group(2)
      line = f"{item_name} ^{due_date} {RTM_DEFAULT_TAGS}".strip()
      rtm_lines.append(line)
    else:
      if target_text:
        line = f"{target_text} {RTM_DEFAULT_TAGS}".strip()
        rtm_lines.append(line)

  print("\n".join(rtm_lines))