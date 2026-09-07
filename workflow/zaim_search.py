#!/usr/bin/env python3
import calendar
from datetime import datetime, timedelta
import json
import os
import sys
import time
import re
import unicodedata

# 共通API通信モジュールのインポート
from zaim_api import zaim_request

# ==============================================================================
# 1. パス & キャッシュ設定
# ==============================================================================
# --- 永続データ用 (config.json) ---
data_dir = os.environ.get("alfred_workflow_data")
if not data_dir:
  data_dir = os.path.dirname(os.path.abspath(__file__))
os.makedirs(data_dir, exist_ok=True)

# ★ config.json のパスチェック
CONFIG_FILE = os.path.join(data_dir, "config.json")
if not os.path.exists(CONFIG_FILE):
  # Terminal 実行か Alfred (Script Filter) 実行かで分岐、または Script Filter 前提で JSON 出力
  print(
      json.dumps(
          {
              "items": [{
                  "title": "設定ファイル (config.json) が見つかりません",
                  "subtitle": (
                      "初回設定が必要です。auth-zaim を実行して認証を行ってください"
                  ),
                  "valid": False,
              }]
          },
          ensure_ascii=False,
      )
  )
  sys.exit(0)

# --- 一時キャッシュ用 (master / money キャッシュ) ---
cache_dir = os.environ.get("alfred_workflow_cache")
if not cache_dir:
  cache_dir = data_dir  # フォールバック
os.makedirs(cache_dir, exist_ok=True)

CACHE_FILE = os.path.join(cache_dir, "zaim_master_cache.json")
CACHE_MONEY_FILE = os.path.join(cache_dir, "zaim_money_cache.json")

# --- 定数設定 (TTL・取得期間等) ---
CACHE_MASTER_TTL = 86400  # マスターデータキャッシュ保持時間（24時間）
CACHE_MONEY_TTL = 300  # 明細データキャッシュ保持時間（5分）
DEFAULT_DAYS = 90  # デフォルト取得日数


# ==============================================================================
# 2. 補助関数 (NFC正規化)
# ==============================================================================
def normalize_text(text: str) -> str:
    """macOS特有のNFD(濁点分離)をNFCに変換し、トリムを行う"""
    if not text:
        return ""
    return unicodedata.normalize("NFC", text).strip()


# ==============================================================================
# 3. マスターデータ（カテゴリ・ジャンル・口座・ユーザー情報）のキャッシュ管理
# ==============================================================================
def get_master_data():
    if os.path.exists(CACHE_FILE):
        mtime = os.path.getmtime(CACHE_FILE)
        if time.time() - mtime < CACHE_MASTER_TTL:
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("categories") and data.get("genres"):
                        return data
            except Exception:
                pass

    try:
        # ★ zaim_request (GET) を利用して取得
        cats_res = zaim_request(
            "GET", "https://api.zaim.net/v2/home/category"
        ).get("categories", [])
        genres_res = zaim_request(
            "GET", "https://api.zaim.net/v2/home/genre"
        ).get("genres", [])
        accs_res = zaim_request(
            "GET", "https://api.zaim.net/v2/home/account"
        ).get("accounts", [])
        user_res = zaim_request(
            "GET", "https://api.zaim.net/v2/home/user/verify"
        ).get("me", {})

        cat_map = {str(c["id"]): c["name"] for c in cats_res}
        acc_map = {
            str(a["id"]): a["name"] for a in accs_res if a.get("active") == 1
        }

        genre_map = {}
        for g in genres_res:
            g_id = str(g["id"])
            c_id = str(g["category_id"])
            c_name = cat_map.get(c_id, "")
            g_name = g["name"]
            genre_map[g_id] = f"{c_name} ＞ {g_name}" if c_name else g_name

        user_info = {
            "day_count": user_res.get("day_count", 0),
            "repeat_count": user_res.get("repeat_count", 0),
            "input_count": user_res.get("input_count", 0),
        }

        master = {
            "categories": cat_map,
            "genres": genre_map,
            "accounts": acc_map,
            "user": user_info,
        }
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(master, f, ensure_ascii=False)

        return master
    except Exception:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "categories": {},
            "genres": {},
            "accounts": {},
            "user": {"day_count": 0, "repeat_count": 0, "input_count": 0},
        }


try:
    master = get_master_data()
except SystemExit:
    # config.json 不在等による zaim_api 側の sys.exit(1) を検知した場合は Alfred 用エラーメッセージを表示して終了
    print(
        json.dumps(
            {
                "items": [
                    {
                        "title": "設定ファイル (config.json) が見つかりません",
                        "subtitle": "auth-zaim を実行してください",
                        "valid": False,
                    }
                ]
            },
            ensure_ascii=False,
        )
    )
    sys.exit(0)

cat_map = master.get("categories", {})
genre_map = master.get("genres", {})
acc_map = master.get("accounts", {})
user_info = master.get(
    "user", {"day_count": 0, "repeat_count": 0, "input_count": 0}
)

# ==============================================================================
# 4. クエリのパース (コマンド parsing)
# ==============================================================================
raw_query = sys.argv[1] if len(sys.argv) > 1 else ""
raw_query_norm = normalize_text(raw_query)

# --- ★1. 環境変数から ALIAS_ で始まるものを取得 ---
aliases = {}
for env_key, env_val in os.environ.items():
  if env_key.startswith("ALIAS_") and env_val.strip():
    alias_name = f"_{env_key[6:].lower()}"  # ALIAS_R -> _r
    aliases[alias_name] = env_val.strip()

# --- ★2. エイリアス補完アイテムの先行生成 ---
# 入力が "_" で始まっている場合、補完リストを準備
alias_items = []
if raw_query_norm.startswith("_"):
  clean_q = raw_query_norm.strip().lower()
  for a_key, a_val in sorted(aliases.items()):
    # "_" のみ、または "_r" 等の入力に前方一致した場合
    if clean_q == "_" or a_key.startswith(clean_q):
      alias_items.append({
          "title": f"エイリアス: {a_key} ➔ {a_val}",
          "subtitle": "💡 Tab キーを押すとこのコマンドに入力窓で展開されます",
          "autocomplete": f"{a_val} ",
          "valid": False,
      })

# --- ★3. クエリ内のエイリアス置換処理 ---
tokens = raw_query_norm.split()
expanded_tokens = []
for token in tokens:
  token_lower = token.lower()
  if token_lower in aliases:
    expanded_tokens.extend(aliases[token_lower].split())
  else:
    expanded_tokens.append(token)
tokens = expanded_tokens

keywords = []
target_mode = None
start_date_filter = None
end_date_filter = None
is_command_typing = False
allow_future = False
field_target = None
force_refresh = False
is_refreshed_msg = False

today = datetime.now().date()
today_str = today.strftime("%Y-%m-%d")

for token in tokens:
    token_lower = token.lower()

    if token_lower == ":":
        keywords.append(":")
        continue

    if token_lower.startswith(":"):
        is_command_typing = True

        if token_lower in [":refresh", ":r", ":ref", ":更新"]:
            force_refresh = True

        if token_lower in [":支出", ":p", ":payment"]:
            target_mode = "payment"
        elif token_lower in [":収入", ":i", ":income"]:
            target_mode = "income"
        elif token_lower in [":振替", ":tr", ":transfer"]:
            target_mode = "transfer"

        elif token_lower in [":y", ":yesterday", ":昨日"]:
            yesterday = today - timedelta(days=1)
            start_date_filter = end_date_filter = yesterday.strftime(
                "%Y-%m-%d"
            )
        elif token_lower in [":t", ":today", ":今日"]:
            start_date_filter = end_date_filter = today_str
        elif token_lower in [":w", ":week", ":今週"]:
            start_date_filter = (
                today - timedelta(days=today.weekday())
            ).strftime("%Y-%m-%d")
        elif token_lower in [":1w", ":7d"]:
            start_date_filter = (today - timedelta(days=7)).strftime(
                "%Y-%m-%d"
            )
        elif token_lower in [":m", ":month", ":今月"]:
            start_date_filter = today.replace(day=1).strftime("%Y-%m-%d")
        elif token_lower in [":1m", ":31d"]:
            start_date_filter = (today - timedelta(days=31)).strftime(
                "%Y-%m-%d"
            )
        elif token_lower in [":lm", ":lastmonth", ":先月"]:
            first_of_this_month = today.replace(day=1)
            last_day_of_last_month = first_of_this_month - timedelta(days=1)
            start_date_filter = last_day_of_last_month.replace(day=1).strftime(
                "%Y-%m-%d"
            )
            end_date_filter = last_day_of_last_month.strftime("%Y-%m-%d")
        elif token_lower in [":fm", ":fullmonth", ":今月末"]:
            start_date_filter = today.replace(day=1).strftime("%Y-%m-%d")
            _, last_day = calendar.monthrange(today.year, today.month)
            end_date_filter = today.replace(day=last_day).strftime("%Y-%m-%d")
            allow_future = True

        elif token_lower in [":ty", ":thisyear", ":ytd", ":今年"]:
            start_date_filter = today.replace(month=1, day=1).strftime(
                "%Y-%m-%d"
            )
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

    # 2. ★新規追加: YYYY-MM-DD-YYYY-MM-DD (範囲指定) の判定
    elif re.match(r"^\d{4}-\d{2}-\d{2}-\d{4}-\d{2}-\d{2}$", token_lower):
        parts = token_lower.split("-")
        d1 = f"{parts[0]}-{parts[1]}-{parts[2]}"
        d2 = f"{parts[3]}-{parts[4]}-{parts[5]}"

        # ★ 大小比較して小さい方を start、大きい方を end に自動設定
        start_date_filter, end_date_filter = sorted([d1, d2])

    # 3. ★新規追加: YYYY-MM-DD (単日指定) の判定
    elif re.match(r"^\d{4}-\d{2}-\d{2}$", token_lower):
        start_date_filter = end_date_filter = token_lower

    # 4. それ以外は通常検索キーワードとして扱う
    else:
        keywords.append(token_lower)

if tokens and tokens[-1].lower().startswith(":"):
    is_command_typing = True

search_query = " ".join(keywords)

# --- 強制キャッシュクリア処理 ---
if force_refresh:
    for fpath in [CACHE_FILE, CACHE_MONEY_FILE]:
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except Exception:
                pass

    master = get_master_data()
    cat_map = master.get("categories", {})
    genre_map = master.get("genres", {})
    acc_map = master.get("accounts", {})
    user_info = master.get(
        "user", {"day_count": 0, "repeat_count": 0, "input_count": 0}
    )
    is_refreshed_msg = True

# ==============================================================================
# 5. 明細データの取得 (キャッシュ付き)
# ==============================================================================
req_start_date = (
    start_date_filter
    if start_date_filter
    else (today - timedelta(days=DEFAULT_DAYS)).strftime("%Y-%m-%d")
)

_, last_day_this_month = calendar.monthrange(today.year, today.month)
end_of_this_month_str = today.replace(day=last_day_this_month).strftime(
    "%Y-%m-%d"
)
req_end_date = (
    end_date_filter
    if (end_date_filter and end_date_filter > end_of_this_month_str)
    else end_of_this_month_str
)


def get_money_data(req_start, req_end):
    # デバッグ: リクエスト対象の日付範囲を出力
    sys.stderr.write(f"[DEBUG] req_start: {req_start}, req_end: {req_end}\n")

    if os.path.exists(CACHE_MONEY_FILE):
        try:
            mtime = os.path.getmtime(CACHE_MONEY_FILE)
            if time.time() - mtime < CACHE_MONEY_TTL:
                with open(CACHE_MONEY_FILE, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    c_start = cdata.get("start_date", "")
                    c_end = cdata.get("end_date", "")
                    if c_start and c_start <= req_start and c_end >= req_end:
                        sys.stderr.write(
                            f"[DEBUG] Returned from cache: {len(cdata.get('money', []))} items\n"
                        )
                        return cdata.get("money", [])
        except Exception as e:
            sys.stderr.write(f"[DEBUG] Cache read error: {e}\n")

    # API直接取得
    try:
        res_data = zaim_request(
            "GET",
            "https://api.zaim.net/v2/home/money",
            params={"start_date": req_start, "limit": 100},
        )
        # デバッグ: APIレスポンスの型と件数を出力
        sys.stderr.write(f"[DEBUG] API Response Keys: {list(res_data.keys()) if isinstance(res_data, dict) else type(res_data)}\n")
        money_list = res_data.get("money", [])
        sys.stderr.write(f"[DEBUG] API Money Count: {len(money_list)}\n")

        try:
            with open(CACHE_MONEY_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "start_date": req_start,
                        "end_date": req_end,
                        "money": money_list,
                    },
                    f,
                    ensure_ascii=False,
                )
        except Exception as e:
            sys.stderr.write(f"[DEBUG] Cache write error: {e}\n")
            
        return money_list
    except Exception as e:
        sys.stderr.write(f"[DEBUG] API Request Exception: {e}\n")
        return []


money_list = get_money_data(req_start_date, req_end_date)

# ==============================================================================
# 6. 今月の集計計算
# ==============================================================================
this_month_prefix = today.strftime("%Y-%m")
this_month_items = [
    item
    for item in money_list
    if item.get("date", "").startswith(this_month_prefix)
]

tm_payment = sum(
    i.get("amount", 0)
    for i in this_month_items
    if i.get("mode", "payment") == "payment"
)
tm_income = sum(
    i.get("amount", 0)
    for i in this_month_items
    if i.get("mode", "payment") == "income"
)
tm_balance = tm_income - tm_payment
tm_balance_str = (
    f"+¥{tm_balance:,}" if tm_balance >= 0 else f"-¥{abs(tm_balance):,}"
)

# ==============================================================================
# 7. 明細データのフィルタリング & Alfredアイテムリスト構築
# ==============================================================================
items = []
sum_payment = sum_income = sum_transfer = 0
count_payment = count_income = count_transfer = 0

export_mods = {
    "cmd": {
        "valid": True,
        "arg": raw_query,
        "variables": {"action_type": "export", "export_format": "text"},
        "subtitle": "📝 テキスト形式で出力 / Text View 表示 (⌘↵)",
    },
    "alt": {
        "valid": True,
        "arg": raw_query,
        "variables": {"action_type": "export", "export_format": "csv"},
        "subtitle": "📊 純正 CSV 形式で保存 (⌥↵)",
    },
    "cmd+alt": {
        "valid": True,
        "arg": raw_query,
        "variables": {"action_type": "export", "export_format": "rtm"},
        "subtitle": "🚀 RTM 用タスク形式で出力 (⌘⌥↵)",
    },
}

target_items = [
    item
    for item in money_list
    if allow_future or item.get("date", "") <= today_str
]
target_items.sort(key=lambda x: x.get("date", ""), reverse=True)

for item in target_items:
    mode = item.get("mode", "payment")
    date = item.get("date", "")

    if target_mode and mode != target_mode:
        continue
    if end_date_filter and date > end_date_filter:
        continue
    if start_date_filter and date < start_date_filter:
        continue

    rec_id = item.get("id")
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

    cat_disp_name = genre_map.get(genre_id_str) or cat_map.get(
        cat_id_str, "カテゴリなし"
    )

    if mode == "transfer":
        acc_disp = f"{from_acc} → {to_acc}"
        cat_label = "振替"
        place_disp = ""
    elif mode == "income":
        acc_disp = to_acc if "未設定" not in to_acc else from_acc
        cat_label = f"【収入】{cat_disp_name}"
        place_disp = raw_place if raw_place else "場所未設定"
    else:
        acc_disp = from_acc
        cat_label = cat_disp_name
        place_disp = raw_place if raw_place else "場所未設定"

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

    search_target = normalize_text(search_raw).lower()

    if search_query and not all(k in search_target for k in keywords):
        continue

    if mode == "income":
        sum_income += amount
        count_income += 1
    elif mode == "transfer":
        sum_transfer += amount
        count_transfer += 1
    else:
        sum_payment += amount
        count_payment += 1

    subtitle_parts = [date]
    if place_disp:
        subtitle_parts.append(place_disp)
    subtitle_parts.extend([cat_label, acc_disp, f"¥{amount:,}"])
    subtitle_text = " | ".join(subtitle_parts)

    title_text = (
        comment
        if comment
        else (
            f"【振替】{acc_disp}"
            if mode == "transfer"
            else f"【{cat_disp_name}】{place_disp}"
        )
    )

    items.append(
        {
            "title": title_text,
            "subtitle": subtitle_text,
            "arg": str(rec_id),
            "variables": {
                "action_type": "detail",
                "zaim_id": str(rec_id),
                "zaim_mode": mode,
            },
            #"mods": export_mods,
            # ★ Command キーを押した時だけ Large Type (⌘L) のガイド説明を表示
            "mods": {
                "cmd": {
                    "valid": True,
                    "arg": str(rec_id),
                    "variables": {
                        "action_type": "detail",
                        "zaim_id": str(rec_id),
                        "zaim_mode": mode,
                    },
                    "subtitle": f"🔍 ⌘L で拡大表示 (メモ/詳細): {comment if comment else title_text}",
                }
            },
            "text": {
                "copy": comment if comment else title_text,
                "largetype": f"{title_text}\n\n{subtitle_text}",
            },
            "action": {"text": comment if comment else title_text},
        }
    )

# ==============================================================================
# 8. サマリー行 & 今月収支（モチベーション）行の生成
# ==============================================================================

total_hits = count_payment + count_income + count_transfer

if total_hits > 0:
    breakdown_parts = []
    if count_payment > 0 or target_mode == "payment":
        breakdown_parts.append(f"支出: ¥{sum_payment:,}")
    if count_income > 0 or target_mode == "income":
        breakdown_parts.append(f"収入: ¥{sum_income:,}")
    if count_transfer > 0 or target_mode == "transfer":
        breakdown_parts.append(f"振替: ¥{sum_transfer:,}")

    summary_title = f"検索結果: {total_hits}件 | " + " / ".join(
        breakdown_parts
    )

    if is_command_typing:
        summary_subtitle = (
            "💡 コマンドガイド: :fm(今月全) :m(今月) :lm(先月) :1w(7日) :w(今週)"
            " :t(今日) :y(昨日) | :p(支出) :i(収入) :tr(振替)"
        )
    else:
        filters_desc = []
        if is_refreshed_msg:
            filters_desc.append("🔄 キャッシュ更新完了")
        if target_mode:
            mode_label = (
                "支出"
                if target_mode == "payment"
                else ("収入" if target_mode == "income" else "振替")
            )
            filters_desc.append(f"種別: {mode_label}")
        if start_date_filter:
            filters_desc.append(
                f"期間: {start_date_filter} 〜 {end_date_filter or '本日'}"
            )
        else:
            filters_desc.append(f"直近{DEFAULT_DAYS}日間")
        if keywords:
            filters_desc.append(f"検索: '{' '.join(keywords)}'")

        summary_subtitle = "💡 " + " / ".join(filters_desc)

    if force_refresh:
        summary_vars = {
            "action_type": "notify",
            "notification_msg": (
                "🔄 Zaim のキャッシュを最新状態に更新しました"
            ),
        }
    else:
        summary_vars = {"action_type": "export", "export_format": "text"}

    summary_item = {
        "title": summary_title,
        "subtitle": summary_subtitle,
        "valid": True,
        "arg": raw_query,
        "variables": summary_vars,
        "mods": export_mods,
    }

    if not raw_query:
        monthly_title = (
            f"📊 今月の見込み収支: 支出 ¥{tm_payment:,} / 収入 ¥{tm_income:,}（収支"
            f" {tm_balance_str}）"
        )
        monthly_subtitle = (
            f"🔥 連続記録: {user_info['repeat_count']}日目 | 累計:"
            f" {user_info['day_count']}日 ({user_info['input_count']:,}件記録)"
        )

        monthly_item = {
            "title": monthly_title,
            "subtitle": monthly_subtitle,
            "valid": True,
            "arg": raw_query,
            "variables": {"action_type": "export", "export_format": "text"},
            "mods": export_mods,
        }
        items.insert(0, monthly_item)
        items.insert(1, summary_item)
    else:
        items.insert(0, summary_item)

else:
    items.append(
        {
            "title": "該当する履歴がありません",
            "subtitle": (
                "検索キーワードやコマンド（:m, :支出 等）を変更してください"
            ),
            "valid": False,
        }
    )

# ★ 準備しておいたエイリアス補完アイテムがあれば先頭に追加
if alias_items:
  items = alias_items + items

print(json.dumps({"items": items}, ensure_ascii=False))