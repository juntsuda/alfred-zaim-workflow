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

CACHE_FILE = os.path.join(LOCAL_CACHE_DIR, "zaim_master_cache.json")


# ==============================================================================
# 2. 汎用・補助関数 (ヘルパー関数)
# ==============================================================================
def normalize_text(text: str) -> str:
  """macOS特有のNFD(濁点分離)をNFCに変換し、小文字化・トリムを行う"""
  if not text:
    return ""
  return unicodedata.normalize("NFC", text).strip().lower()


# ==============================================================================
# 3. 個別コード
# ==============================================================================
# --- 1. 環境変数と入力（アルフレッドからの検索クエリ）の取得 ---
ZAIM_ACTION = os.environ.get("zaim_action")
current_val = normalize_text(os.environ.get("current_val", ""))

raw_query = (
    normalize_text(sys.argv[1]) if len(sys.argv) > 1 else ""
)

# 前段(zaim-detail)から渡された初期選択名と同じ場合は、検索クエリを無視して全件表示する
if raw_query == current_val:
  query = ""
else:
  query = raw_query

# 共通変数をそのまま保持して zaim_update.py へ引き継ぐ
base_vars = {
    "zaim_id": os.environ.get("zaim_id"),
    "zaim_mode": os.environ.get("zaim_mode", "payment"),
    "current_amount": os.environ.get("current_amount"),
    "current_date": os.environ.get("current_date"),
}

items = []

# --- 2. 統合キャッシュファイル (zaim_master_cache.json) の読み込み ---
master_data = {}
if os.path.exists(CACHE_FILE):
  try:
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
      master_data = json.load(f)
  except Exception:
    pass

# --- 3. アクションに応じたリストの構築 ---

if ZAIM_ACTION == "select_genre":
  genres = master_data.get("genres", {})

  for g_id, g_name in genres.items():
    norm_g_name = normalize_text(g_name)
    if query and query not in norm_g_name:
      continue

    is_selected = norm_g_name == current_val
    title_text = f"✔ {g_name}" if is_selected else g_name
    sub_text = (
        "現在のカテゴリです" if is_selected else "Enter でこのカテゴリに決定"
    )

    item_data = {
        "title": title_text,
        "subtitle": sub_text,
        "arg": str(g_id),
        "variables": {
            **base_vars,
            "zaim_action": "edit_genre",
        },
    }

    # 選択中の項目はリストの先頭に、それ以外は後ろに追加
    if is_selected:
      items.insert(0, item_data)
    else:
      items.append(item_data)

elif ZAIM_ACTION == "select_account":
  accounts = master_data.get("accounts", {})

  for a_id, a_name in accounts.items():
    norm_a_name = normalize_text(a_name)
    if query and query not in norm_a_name:
      continue

    is_selected = norm_a_name == current_val
    title_text = f"✔ {a_name}" if is_selected else a_name
    sub_text = (
        "現在の口座です" if is_selected else "Enter でこの口座に決定"
    )

    item_data = {
        "title": title_text,
        "subtitle": sub_text,
        "arg": str(a_id),
        "variables": {
            **base_vars,
            "zaim_action": "edit_account",
        },
    }

    if is_selected:
      items.insert(0, item_data)
    else:
      items.append(item_data)

if not items:
  items.append({"title": "該当する項目が見つかりません", "valid": False})

print(json.dumps({"items": items}, ensure_ascii=False))