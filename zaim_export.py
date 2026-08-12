import argparse
import calendar
import csv
from datetime import datetime, timedelta
import json
import os
import re
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
CACHE_FILE = os.path.join(LOCAL_CACHE_DIR, "zaim_master_cache.json")
CACHE_MONEY_FILE = os.path.join(LOCAL_CACHE_DIR, "zaim_money_cache.json")

# --- 定数設定 (TTL・取得期間等) ---
CACHE_MASTER_TTL = 86400  # マスターデータキャッシュ保持時間（24時間）
CACHE_MONEY_TTL = 300  # 明細データキャッシュ保持時間（5分）
DEFAULT_DAYS = 90  # デフォルト取得日数

# --- 定数設定 (エクスポート用) ---
RTM_DEFAULT_TAGS = "#賞味期限 #食材"  # タグ不要な場合は "" に変更

# ==============================================================================
# 2. API 認証 & クライアント初期化
# ==============================================================================
try:
  with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    config = json.load(f)
except FileNotFoundError:
  print(
      json.dumps(
          {
              "items": [{
                  "title": "設定ファイル (config.json) が見つかりません",
                  "subtitle": "auth-zaim を実行してください",
                  "valid": False,
              }]
          },
          ensure_ascii=False,
      )
  )
  sys.exit(1)

oauth = OAuth1Session(
    config["consumer_id"],
    client_secret=config["consumer_secret"],
    resource_owner_key=config["access_token"],
    resource_owner_secret=config["access_token_secret"],
)


# ==============================================================================
# 3. 個別コード
# ==============================================================================
# --- 2. 引数の解析 ---
parser = argparse.ArgumentParser()
parser.add_argument("--format", choices=["csv", "text", "rtm"], default="text")
parser.add_argument("query", nargs="?", default="")
args = parser.parse_args()

# --- マスターデータのロード ---
with open(CACHE_FILE, "r", encoding="utf-8") as f:
  master = json.load(f)

cat_map = master.get("categories", {})  # id -> 大項目名
genre_map = master.get("genres", {})  # id -> "大項目 ＞ 中項目"
acc_map = master.get("accounts", {})  # id -> 口座名

# --- クエリのパース (zaim_search.py と完全一致) ---
raw_query_norm = unicodedata.normalize("NFC", args.query.strip())
tokens = raw_query_norm.split()

keywords = []
target_mode = None  # payment / income / transfer
start_date_filter = None
end_date_filter = None
allow_future = False
field_target = None

today = datetime.now().date()

for token in tokens:
  token_lower = token.lower()
  if token_lower.startswith(":"):
    # モード指定
    if token_lower in [":支出", ":p", ":payment"]:
      target_mode = "payment"
    elif token_lower in [":収入", ":i", ":income"]:
      target_mode = "income"
    elif token_lower in [":振替", ":tr", ":transfer"]:
      target_mode = "transfer"

    # 期間指定
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

    # 検索対象フィールド絞り込み
    elif token_lower in [":g", ":genre", ":cat", ":ジャンル", ":カテゴリ"]:
      field_target = "genre"
    elif token_lower in [":s", ":shop", ":place", ":店舗", ":場所"]:
      field_target = "place"
    elif token_lower in [":a", ":acc", ":account", ":口座"]:
      field_target = "account"
    elif token_lower in [":memo", ":comment", ":メモ"]:
      field_target = "memo"

  else:
    keywords.append(token_lower)

search_query = " ".join(keywords)

# --- 明細データの取得とフィルタリング ---
api_start_date = (
    start_date_filter
    if start_date_filter
    else (today - timedelta(days=DEFAULT_DAYS)).strftime("%Y-%m-%d")
)
today_str = today.strftime("%Y-%m-%d")

params = {"start_date": api_start_date, "limit": 100}
response = oauth.get("https://api.zaim.net/v2/home/money", params=params)

filtered_items = []

if response.status_code == 200:
  money_list = response.json().get("money", [])

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

    # カテゴリ・ジャンル名のパース
    category_large = cat_map.get(cat_id_str, "-")
    genre_full = genre_map.get(genre_id_str, "")
    if " ＞ " in genre_full:
      category_sub = genre_full.split(" ＞ ", 1)[1]
    else:
      category_sub = genre_full if genre_full else "-"

    cat_disp_name = genre_full or category_large

    # フィールド指定判定
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

# --- フォーマット別出力処理 ---

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

  # デスクトップ等へファイル保存する場合は標準出力ではなく直接書き出しも可能
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
          "",  # 品目
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

  # Alfred の通知ノードへメッセージを渡す
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
      # .strip() により RTM_DEFAULT_TAGS が空でも末尾の無駄なスペースが消去される
      line = f"{item_name} ^{due_date} {RTM_DEFAULT_TAGS}".strip()
      rtm_lines.append(line)
    else:
      if target_text:
        line = f"{target_text} {RTM_DEFAULT_TAGS}".strip()
        rtm_lines.append(line)

  print("\n".join(rtm_lines))
