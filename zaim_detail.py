#!/usr/bin/env python3
import json
import os
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


# ==============================================================================
# 2. 補助関数 (NFC正規化)
# ==============================================================================
def normalize_text(text: str) -> str:
  """macOS特有のNFD(濁点分離)をNFCに変換し、トリムを行う"""
  if not text:
    return ""
  return unicodedata.normalize("NFC", text).strip()


# ==============================================================================
# 3. API 認証 & クライアント初期化
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
# 4. 個別コード
# ==============================================================================
# --- マスターデータ（カテゴリ・ジャンル・口座）の取得 ---
cat_map = {}
genre_map = {}
acc_map = {}

if os.path.exists(CACHE_FILE):
  try:
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
      master = json.load(f)
      cat_map = master.get("categories", {})
      genre_map = master.get("genres", {})
      acc_map = master.get("accounts", {})
  except Exception:
    pass

# --- 引数（zaim_id または zaim_id:更新項目）の取得 ---
raw_arg = (
    sys.argv[1].strip() if len(sys.argv) > 1 else os.environ.get("zaim_id", "")
)
raw_arg = normalize_text(raw_arg)
update_msg = ""

# "10151195314:メモ" のようにコロンが含まれている場合は分解
if ":" in raw_arg:
  target_id, item_name = raw_arg.split(":", 1)
  update_msg = f"✅ {item_name}を更新しました"
else:
  target_id = raw_arg

if not target_id:
  print(
      json.dumps(
          {
              "items": [{
                  "title": "エラー: 対象の明細IDが指定されていません",
                  "valid": False,
              }]
          },
          ensure_ascii=False,
      )
  )
  sys.exit(0)

# --- Zaim API から該当明細の取得 ---
params = {"id": target_id}
response = oauth.get("https://api.zaim.net/v2/home/money", params=params)

if response.status_code != 200:
  print(
      json.dumps(
          {
              "items": [{
                  "title": "エラー: 明細データの取得に失敗しました",
                  "valid": False,
              }]
          },
          ensure_ascii=False,
      )
  )
  sys.exit(0)

money_list = response.json().get("money", [])
target_item = next(
    (item for item in money_list if str(item.get("id")) == target_id), None
)

if not target_item:
  print(
      json.dumps(
          {
              "items": [
                  {"title": "該当する明細が見つかりませんでした", "valid": False}
              ]
          },
          ensure_ascii=False,
      )
  )
  sys.exit(0)

# --- 明細情報の抽出 & NFC正規化 ---
mode = target_item.get("mode", "payment")  # payment / income / transfer
comment = normalize_text(target_item.get("comment", ""))
place = normalize_text(target_item.get("place", ""))
amount = target_item.get("amount", 0)
date = target_item.get("date", "")

cat_id_str = str(target_item.get("category_id", ""))
genre_id_str = str(target_item.get("genre_id", ""))

# 口座ID抽出
from_id_val = (
    target_item.get("from_account_id")
    if target_item.get("from_account_id") is not None
    else target_item.get("account_id")
)
to_id_val = target_item.get("to_account_id")

from_id_str = str(from_id_val) if from_id_val is not None else ""
to_id_str = str(to_id_val) if to_id_val is not None else ""

from_acc = acc_map.get(from_id_str) or (
    "お財布" if from_id_str in ["1", "0", ""] else f"口座({from_id_str})"
)
to_acc = acc_map.get(to_id_str) or (
    "お財布" if to_id_str in ["1", "0", ""] else f"口座({to_id_str})"
)

# カテゴリ/ジャンル表記
cat_disp_name = genre_map.get(genre_id_str) or cat_map.get(
    cat_id_str, "カテゴリなし"
)

# --- Alfred 用アイテムリストの構築 ---
items = []

if update_msg:
  items.append({
      "title": update_msg,
      "subtitle": "最新の明細情報を表示しています",
      "valid": False,
  })

base_vars = {
    "zaim_id": target_id,
    "zaim_mode": mode,
    "current_amount": str(amount),
    "current_date": str(date),
}

# 【1】メモ（編集可能）
items.append({
    "title": f"📝 メモ: {comment if comment else '(未設定)'}",
    "subtitle": "Enter を押してメモを変更",
    "arg": comment,
    "text": {
        "copy": comment or "",
        "largetype": comment or "(メモ未設定)",
    },
    "variables": {
        **base_vars,
        "zaim_action": "edit_comment",
        "current_val": comment,
    },
})

# 【2】金額（編集可能）
items.append({
    "title": f"💴 金額: ¥{amount:,}",
    "subtitle": "Enter を押して金額を変更",
    "arg": str(amount),
    "variables": {
        **base_vars,
        "zaim_action": "edit_amount",
        "current_val": str(amount),
    },
})

# 【3】日付（編集可能）
items.append({
    "title": f"📅 日付: {date}",
    "subtitle": "Enter を押して日付を変更",
    "arg": date,
    "variables": {
        **base_vars,
        "zaim_action": "edit_date",
        "current_val": date,
    },
})

# 【4】場所 / 店舗（編集可能・振替以外）
if mode != "transfer":
  items.append({
      "title": f"📍 場所: {place if place else '場所未設定'}",
      "subtitle": "Enter を押して場所を変更",
      "arg": place,
      "variables": {
          **base_vars,
          "zaim_action": "edit_place",
          "current_val": place,
      },
  })

# 【5】カテゴリ（編集可能・振替以外）
if mode != "transfer":
  cat_label = f"【収入】{cat_disp_name}" if mode == "income" else cat_disp_name
  items.append({
      "title": f"📂 カテゴリ: {cat_label}",
      "subtitle": "Enter を押してカテゴリを変更",
      "arg": cat_disp_name,
      "text": {"copy": cat_label, "largetype": cat_label},
      "variables": {
          **base_vars,
          "zaim_action": "select_genre",
          "current_val": cat_disp_name,
      },
  })

# 【6】口座情報（振替以外は編集可能）
if mode == "transfer":
  acc_label = f"振替: {from_acc} ➔ {to_acc}"
  items.append({
      "title": f"💳 口座: {acc_label}",
      "subtitle": "（振替の口座変更は非対応）",
      "valid": False,
      "text": {"copy": acc_label, "largetype": acc_label},
  })
else:
  acc_label = f"入金先: {to_acc}" if mode == "income" else f"出金元: {from_acc}"
  current_acc_name = to_acc if mode == "income" else from_acc

  items.append({
      "title": f"💳 口座: {acc_label}",
      "subtitle": "Enter を押して口座を変更",
      "arg": current_acc_name,
      "text": {"copy": current_acc_name, "largetype": current_acc_name},
      "variables": {
          **base_vars,
          "zaim_action": "select_account",
          "current_val": current_acc_name,
      },
  })

print(json.dumps({"items": items}, ensure_ascii=False))