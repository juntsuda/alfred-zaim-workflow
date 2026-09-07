#!/usr/bin/env python3
import json
import os
import sys
import unicodedata

# 共通API通信モジュールのインポート
from zaim_api import zaim_request

# ==============================================================================
# 1. パス & キャッシュ設定
# ==============================================================================
# alfred_workflow_data または キャッシュディレクトリの参照
data_dir = os.environ.get("alfred_workflow_data")
if not data_dir:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    data_dir = BASE_DIR

CACHE_FILE = os.path.join(data_dir, "zaim_master_cache.json")


# ==============================================================================
# 2. 補助関数 (NFC正規化)
# ==============================================================================
def normalize_text(text: str) -> str:
    """macOS特有のNFD(濁点分離)をNFCに変換し、トリムを行う"""
    if not text:
        return ""
    return unicodedata.normalize("NFC", text).strip()


# ==============================================================================
# 3. 個別処理（明細データの取得 & Alfred用JSON構築）
# ==============================================================================
# --- マスターデータ（カテゴリ・ジャンル・口座）の取得 ---
cat_map, genre_map, acc_map = {}, {}, {}
if os.path.exists(CACHE_FILE):
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            master = json.load(f)
            cat_map = master.get("categories", {})
            genre_map = master.get("genres", {})
            acc_map = master.get("accounts", {})
    except Exception:
        pass

# --- 引数の取得 & パース ---
raw_arg = (
    sys.argv[1].strip() if len(sys.argv) > 1 else os.environ.get("zaim_id", "")
)
raw_arg = normalize_text(raw_arg)
update_msg = ""

if ":" in raw_arg:
    target_id, item_name = raw_arg.split(":", 1)
    update_msg = f"✅ {item_name}を更新しました"
else:
    target_id = raw_arg

if not target_id:
    print(
        json.dumps(
            {
                "items": [
                    {
                        "title": "エラー: 対象の明細IDが指定されていません",
                        "valid": False,
                    }
                ]
            },
            ensure_ascii=False,
        )
    )
    sys.exit(0)

# --- ★ Zaim API から該当明細の取得（標準ライブラリ共通関数を使用） ★ ---
try:
    response_data = zaim_request(
        "GET", "https://api.zaim.net/v2/home/money", params={"id": target_id}
    )
except Exception as e:
    print(
        json.dumps(
            {
                "items": [
                    {
                        "title": "エラー: 明細データの取得に失敗しました",
                        "subtitle": str(e),
                        "valid": False,
                    }
                ]
            },
            ensure_ascii=False,
        )
    )
    sys.exit(0)

money_list = response_data.get("money", [])
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

# ------------------------------------------------------------------------------
# (以下、元の Alfred 用アイテムリスト構築ロジックはそのまま維持)
# ------------------------------------------------------------------------------
mode = target_item.get("mode", "payment")
comment = normalize_text(target_item.get("comment", ""))
place = normalize_text(target_item.get("place", ""))
amount = target_item.get("amount", 0)
date = target_item.get("date", "")

cat_id_str = str(target_item.get("category_id", ""))
genre_id_str = str(target_item.get("genre_id", ""))

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

cat_disp_name = genre_map.get(genre_id_str) or cat_map.get(
    cat_id_str, "カテゴリなし"
)

items = []

if update_msg:
    items.append(
        {
            "title": update_msg,
            "subtitle": "最新の明細情報を表示しています",
            "valid": False,
        }
    )

base_vars = {
    "zaim_id": target_id,
    "zaim_mode": mode,
    "current_amount": str(amount),
    "current_date": str(date),
}

# 【1】メモ（編集可能）
items.append(
    {
        "title": f"📝 メモ: {comment if comment else '(未設定)'}",
        "subtitle": "Enter を押してメモを変更",
        "arg": comment if comment else " ",  # ★ 空の場合は半角スペース1つを渡して arg 評価を通す
        "text": {
            "copy": comment or "",
            "largetype": comment or "(メモ未設定)",
        },
        "variables": {
            **base_vars,
            "zaim_action": "edit_comment",
            "current_val": comment,
        },
    }
)

items.append(
    {
        "title": f"💴 金額: ¥{amount:,}",
        "subtitle": "Enter を押して金額を変更",
        "arg": str(amount),
        "variables": {
            **base_vars,
            "zaim_action": "edit_amount",
            "current_val": str(amount),
        },
    }
)

items.append(
    {
        "title": f"📅 日付: {date}",
        "subtitle": "Enter を押して日付を変更",
        "arg": date,
        "variables": {
            **base_vars,
            "zaim_action": "edit_date",
            "current_val": date,
        },
    }
)

if mode != "transfer":
    items.append(
        {
            "title": f"📍 場所: {place if place else '場所未設定'}",
            "subtitle": "Enter を押して場所を変更",
            "arg": place,
            "variables": {
                **base_vars,
                "zaim_action": "edit_place",
                "current_val": place,
            },
        }
    )

if mode != "transfer":
    cat_label = (
        f"【収入】{cat_disp_name}" if mode == "income" else cat_disp_name
    )
    items.append(
        {
            "title": f"📂 カテゴリ: {cat_label}",
            "subtitle": "Enter を押してカテゴリを変更",
            "arg": cat_disp_name,
            "text": {"copy": cat_label, "largetype": cat_label},
            "variables": {
                **base_vars,
                "zaim_action": "select_genre",
                "current_val": cat_disp_name,
            },
        }
    )

if mode == "transfer":
    acc_label = f"振替: {from_acc} ➔ {to_acc}"
    items.append(
        {
            "title": f"💳 口座: {acc_label}",
            "subtitle": "（振替の口座変更は非対応）",
            "valid": False,
            "text": {"copy": acc_label, "largetype": acc_label},
        }
    )
else:
    acc_label = (
        f"入金先: {to_acc}" if mode == "income" else f"出金元: {from_acc}"
    )
    current_acc_name = to_acc if mode == "income" else from_acc

    items.append(
        {
            "title": f"💳 口座: {acc_label}",
            "subtitle": "Enter を押して口座を変更",
            "arg": current_acc_name,
            "text": {"copy": current_acc_name, "largetype": current_acc_name},
            "variables": {
                **base_vars,
                "zaim_action": "select_account",
                "current_val": current_acc_name,
            },
        }
    )

print(json.dumps({"items": items}, ensure_ascii=False))
