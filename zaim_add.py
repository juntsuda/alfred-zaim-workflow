import json
import os
import plistlib
import sys
import unicodedata
from datetime import datetime

# ==============================================================================
# 1. パス & 定数定義 (環境に依存しない動的判定)
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

DEFAULT_CATEGORY_ID = 4834408  # その他支出
DEFAULT_GENRE_ID = 22560320  # その他


# ==============================================================================
# 2. 補助関数 (NFC正規化 & テキストパース)
# ==============================================================================
def normalize_text(text: str) -> str:
  """macOS特有のNFD(濁点分離)をNFCに変換し、トリムを行う"""
  if not text:
    return ""
  return unicodedata.normalize("NFC", text).strip()


def parse_line(line_str):
  """1行のテキストから (amount, comment) をパースして返す"""
  line_str = line_str.strip()
  if not line_str:
    return None, None

  parts = line_str.split(None, 1)
  amount_str = parts[0]
  comment = parts[1] if len(parts) > 1 else ""

  # 全角数字を半角数字に変換＆カンマ等の除去
  amount_clean = amount_str.translate(
      str.maketrans("０１２３４５６７８９", "0123456789")
  ).replace(",", "")

  if not amount_clean.isdigit():
    return None, None

  return int(amount_clean), comment


# ==============================================================================
# 3. API 認証 & クライアント初期化
# ==============================================================================
try:
  with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    config = json.load(f)
except FileNotFoundError:
  sys.stderr.write(
      "エラー: config.json が見つかりません。auth-zaim を実行してください。\n"
  )
  sys.exit(1)

oauth = OAuth1Session(
    config["consumer_id"],
    client_secret=config["consumer_secret"],
    resource_owner_key=config["access_token"],
    resource_owner_secret=config["access_token_secret"],
)


# ==============================================================================
# 4. メイン処理 (登録実行 または プレビュー生成)
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

    res = oauth.post("https://api.zaim.net/v2/home/money/payment", data=payload)

    if res.status_code in [200, 201]:
      success_count += 1
      total_amount += amount
      res_data = res.json()
      last_new_id = res_data.get("money", {}).get("id")
    else:
      sys.stderr.write(
          f"Zaim API エラー [{res.status_code}]: {res.text} (対象行:"
          f" '{line}')\n"
      )

  # 1件でも登録成功した場合はローカルの明細キャッシュを破棄
  if success_count > 0 and os.path.exists(CACHE_MONEY_FILE):
    try:
      os.remove(CACHE_MONEY_FILE)
    except Exception:
      pass

  # 出力分岐
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