#!/usr/bin/env python3
import json
import os
import sys
import unicodedata

# ==============================================================================
# 1. パス & 定数定義
# ==============================================================================
data_dir = os.environ.get("alfred_workflow_data")
if not data_dir:
  data_dir = os.path.dirname(os.path.abspath(__file__))
os.makedirs(data_dir, exist_ok=True)

cache_dir = os.environ.get("alfred_workflow_cache")
if not cache_dir:
  cache_dir = data_dir
os.makedirs(cache_dir, exist_ok=True)

CACHE_FILE = os.path.join(cache_dir, "zaim_master_cache.json")
CACHE_MONEY_FILE = os.path.join(cache_dir, "zaim_money_cache.json")


def normalize_text(text: str) -> str:
  if not text:
    return ""
  return unicodedata.normalize("NFC", text).strip().lower()


# ==============================================================================
# 2. メイン処理 (環境変数 & クエリ解析)
# ==============================================================================
ZAIM_ACTION = os.environ.get("zaim_action", "")
current_val = normalize_text(os.environ.get("current_val", ""))

# 生の入力引数を取得
raw_input = sys.argv[1] if len(sys.argv) > 1 else ""
norm_input = normalize_text(raw_input)

# 初期値と同じテキストが渡ってきた場合は「検索クエリなし」とみなす
if norm_input == current_val:
  query = ""
else:
  query = norm_input

base_vars = {
    "zaim_id": os.environ.get("zaim_id", ""),
    "zaim_mode": os.environ.get("zaim_mode", "payment"),
    "current_amount": os.environ.get("current_amount", ""),
    "current_date": os.environ.get("current_date", ""),
}

items = []

# マスターデータの読み込み
master_data = {}
if os.path.exists(CACHE_FILE):
  try:
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
      master_data = json.load(f)
  except Exception:
    pass

# ==============================================================================
# 3. アクション別 リスト構築
# ==============================================================================

# ------------------------------------------------------------------------------
# 【A】カテゴリ (ジャンル) 選択
# ------------------------------------------------------------------------------
if ZAIM_ACTION == "select_genre":
  genres = master_data.get("genres", {})

  for g_id, g_name in genres.items():
    norm_g_name = normalize_text(g_name)

    if query and query not in norm_g_name:
      continue

    is_selected = norm_g_name == current_val
    title_text = f"✔ {g_name}" if is_selected else g_name
    sub_text = "現在のカテゴリです" if is_selected else "Enter でこのカテゴリに決定"

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

# ------------------------------------------------------------------------------
# 【B】口座 選択
# ------------------------------------------------------------------------------
elif ZAIM_ACTION == "select_account":
  accounts = master_data.get("accounts", {})

  for a_id, a_name in accounts.items():
    norm_a_name = normalize_text(a_name)

    if query and query not in norm_a_name:
      continue

    is_selected = norm_a_name == current_val
    title_text = f"✔ {a_name}" if is_selected else a_name
    sub_text = "現在の口座です" if is_selected else "Enter でこの口座に決定"

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

# ------------------------------------------------------------------------------
# 【C】場所 (店舗名) 選択 & 手打ち
# ------------------------------------------------------------------------------
elif ZAIM_ACTION == "select_place":
  user_typed = raw_input.strip()

  recent_places = []
  seen = set()

  if os.path.exists(CACHE_MONEY_FILE):
    try:
      with open(CACHE_MONEY_FILE, "r", encoding="utf-8") as f:
        money_data = json.load(f)

        if isinstance(money_data, dict):
          money_data = money_data.get("money", [])

        for record in money_data:
          raw_p = record.get("place", "")
          p_name = ""

          if isinstance(raw_p, str):
            p_name = raw_p.strip()
          elif isinstance(raw_p, dict):
            p_name = raw_p.get("name", "").strip()

          if not p_name and record.get("place_uid"):
            p_name = str(record.get("place_uid")).strip()

          if p_name and p_name not in seen:
            seen.add(p_name)
            recent_places.append(p_name)
    except Exception:
      pass

  if user_typed:
    items.append({
        "title": f"「{user_typed}」に決定（直接入力）",
        "subtitle": "Enter でこの場所名に更新します",
        "arg": user_typed,
        "variables": {
            **base_vars,
            "zaim_action": "edit_place",
        },
    })
    items.insert(0, items.pop())
  elif current_val:
    items.append({
        "title": "場所を未設定（クリア）にする",
        "subtitle": "Enter で場所名を消去します",
        "arg": " ",
        "variables": {
            **base_vars,
            "zaim_action": "edit_place",
        },
    })

  for p_name in recent_places:
    norm_p_name = normalize_text(p_name)

    if query and query not in norm_p_name:
      continue

    if user_typed and norm_p_name == normalize_text(user_typed):
      continue

    is_selected = norm_p_name == current_val
    title_text = f"✔ {p_name}" if is_selected else p_name
    sub_text = (
        "現在の場所です" if is_selected else "最近の実績から選択 (Enter で決定)"
    )

    item_data = {
        "title": title_text,
        "subtitle": sub_text,
        "arg": p_name,
        "variables": {
            **base_vars,
            "zaim_action": "edit_place",
        },
    }

    if is_selected:
      items.insert(1 if user_typed else 0, item_data)
    else:
      items.append(item_data)

# ------------------------------------------------------------------------------
# 【D】金額 選択 & 小数点考慮の税率計算 (四捨五入・切り捨て・切り上げ)
# ------------------------------------------------------------------------------
elif ZAIM_ACTION == "select_amount":
  import math

  # 1. ユーザーが今入力・変更している値
  clean_input = "".join([c for c in raw_input if c.isdigit()])
  input_amount = int(clean_input) if clean_input else 0

  # 2. もともとの値（変更前の値）の取得
  orig_clean = "".join([c for c in str(current_val) if c.isdigit()]) if current_val else ""
  if not orig_clean:
    orig_clean = "".join([c for c in os.environ.get("current_amount", "") if c.isdigit()])
  original_amount = int(orig_clean) if orig_clean else 0

  # A. 入力値ベースの候補
  if input_amount > 0:
    # そのままの金額
    items.append({
        "title": f"¥{input_amount:,} で確定（そのまま）",
        "subtitle": "Enter でこの金額に更新します",
        "arg": str(input_amount),
        "variables": {
            **base_vars,
            "zaim_action": "edit_amount",
        },
    })

    # 10% 計算
    exact_10 = input_amount * 1.1
    v10_floor = math.floor(exact_10)
    v10_ceil = math.ceil(exact_10)
    v10_round = round(exact_10)

    # 8% 計算
    exact_08 = input_amount * 1.08
    v08_floor = math.floor(exact_08)
    v08_ceil = math.ceil(exact_08)
    v08_round = round(exact_08)

    # 小数点があるかどうかで表示を切り替える
    has_decimal_10 = (exact_10 != v10_floor)
    has_decimal_08 = (exact_08 != v08_floor)

    calc_options = []

    # 10% の候補（小数点がある場合は厳密値も提示）
    if has_decimal_10:
      calc_options.append((
          f"¥{v10_round:,} (10% 税込・四捨五入 [原価×1.1 = {exact_10:.2f}円])",
          v10_round,
      ))
      calc_options.append((
          f"¥{v10_floor:,} (10% 税込・切り捨て)",
          v10_floor,
      ))
      calc_options.append((
          f"¥{v10_ceil:,} (10% 税込・切り上げ)",
          v10_ceil,
      ))
    else:
      calc_options.append((
          f"¥{v10_floor:,} (10% 税込)",
          v10_floor,
      ))

    # 8% の候補
    if has_decimal_08:
      calc_options.append((
          f"¥{v08_round:,} (8% 税込・四捨五入 [原価×1.08 = {exact_08:.2f}円])",
          v08_round,
      ))
      calc_options.append((
          f"¥{v08_floor:,} (8% 税込・切り捨て)",
          v08_floor,
      ))
      calc_options.append((
          f"¥{v08_ceil:,} (8% 税込・切り上げ)",
          v08_ceil,
      ))
    else:
      calc_options.append((
          f"¥{v08_floor:,} (8% 税込)",
          v08_floor,
      ))

    for title_str, val in calc_options:
      items.append({
          "title": title_str,
          "subtitle": "Tab でこの金額を候補にセット (Enterで決定)",
          "arg": str(val),
          "autocomplete": str(val),
          "variables": {
              **base_vars,
              "zaim_action": "edit_amount",
          },
      })

  # B. もともとの値に戻す項目
  if original_amount > 0 and original_amount != input_amount:
    items.append({
        "title": f"↩️ ¥{original_amount:,} （もともとの値に戻す）",
        "subtitle": "Tab または Enter で元の金額に戻します",
        "arg": str(original_amount),
        "autocomplete": str(original_amount),
        "variables": {
            **base_vars,
            "zaim_action": "edit_amount",
        },
    })

  if not items:
    items.append({
        "title": "金額を入力してください",
        "subtitle": "例: 1050 と入力すると小数点を含む税率計算が表示されます",
        "valid": False,
    })

print(json.dumps({"items": items}, ensure_ascii=False))