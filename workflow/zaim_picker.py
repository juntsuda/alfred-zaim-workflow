#!/usr/bin/env python3
import json
import os
import sys
import unicodedata

# ==============================================================================
# 1. パス & キャッシュ設定 (alfred_workflow_data 優先)
# ==============================================================================
data_dir = os.environ.get("alfred_workflow_data")
if not data_dir:
  BASE_DIR = os.path.dirname(os.path.abspath(__file__))
  data_dir = BASE_DIR

CACHE_FILE = os.path.join(data_dir, "zaim_master_cache.json")


def normalize_text(text: str) -> str:
  if not text:
    return ""
  return unicodedata.normalize("NFC", text).strip().lower()


# ==============================================================================
# 2. メイン処理 (絞り込みリスト構築)
# ==============================================================================
ZAIM_ACTION = os.environ.get("zaim_action")
current_val = normalize_text(os.environ.get("current_val", ""))

raw_query = normalize_text(sys.argv[1]) if len(sys.argv) > 1 else ""

if raw_query == current_val:
  query = ""
else:
  query = raw_query

base_vars = {
    "zaim_id": os.environ.get("zaim_id"),
    "zaim_mode": os.environ.get("zaim_mode", "payment"),
    "current_amount": os.environ.get("current_amount"),
    "current_date": os.environ.get("current_date"),
}

items = []

master_data = {}
if os.path.exists(CACHE_FILE):
  try:
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
      master_data = json.load(f)
  except Exception:
    pass

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
