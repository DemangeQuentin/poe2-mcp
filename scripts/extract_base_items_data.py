#!/usr/bin/env python3
"""
Extract base item types from baseitemtypes.datc64 + itemclasses.datc64.

Fixes #205: the packaged/distributed MCP has never shipped base-item data —
no extraction step existed for this table at all, and the dormant raw-.datc64
fallback in fresh_data_provider.py (`_extract_base_items`) pointed at a stale
path and only read 2 of the fields needed, so it never actually ran (a Priority-1
`complete_models/` load always short-circuits before it, on every install).

Column layout for baseitemtypes.datc64 was reverse-engineered against known
item names/classes and cross-validated against the PoB2 clone's Bases/*.lua
files (reconciliation oracle only, per CLAUDE.md role discipline — no PoB
values are copied into the output, only used to confirm which byte offsets
are correct):

  offset 0  (int64 ptr)  -> Id           e.g. "Metadata/Items/.../Axe1"
  offset 8  (int32)      -> ItemClass FK (row index into itemclasses.datc64)
  offset 32 (int64 ptr)  -> Name         e.g. "Dull Hatchet"

Validated at 4612 extracted rows, 92.8% exact string match against 1767 PoB
oracle entries; nearly all remaining diffs are PoB collapsing granular GGG
classes (LifeFlask/ManaFlask/UtilityFlask) into coarser display buckets
(Flask/Charm) for its own UI, not extraction errors.

Only id/name/item_class are extracted here (the minimum needed to make
list_all_base_items / inspect_base_item return real data). Width/height,
drop level, requirements, and weapon/armour stats are tracked as follow-up
work, not blocking this fix.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.data.fresh_data_provider import Datc64Parser  # noqa: E402

BASE_DIR = Path(__file__).parent.parent
GAME_BALANCE = BASE_DIR / "data" / "extracted" / "Data" / "balance"
OUTPUT_PATH = BASE_DIR / "data" / "game" / "base_items" / "base_items.json"


def load_item_classes(path: Path) -> dict:
    """Row index -> {id, name} from itemclasses.datc64 (id@0, display name@8)."""
    parser = Datc64Parser(path)
    classes = {}
    for i in range(parser.row_count):
        row = parser.read_row(i)
        class_id = parser.read_string(parser.read_int64(row, 0))
        display_name = parser.read_string(parser.read_int64(row, 8))
        classes[i] = {"id": class_id, "name": display_name or class_id}
    return classes


def extract_base_items(base_path: Path, classes: dict) -> tuple:
    """Id -> item record from baseitemtypes.datc64.

    Rows whose name is flagged "[DNT]" (game data's own "Do Not
    Translate"/"not visible to players" marker for internal-only rows, e.g.
    scaled Incursion currency variants) are excluded — they'd otherwise show
    up as confusing garbage in list_all_base_items for real players.

    Returns (items, excluded_dnt_count).
    """
    parser = Datc64Parser(base_path)
    items = {}
    excluded_dnt = 0
    for i in range(parser.row_count):
        row = parser.read_row(i)
        item_id = parser.read_string(parser.read_int64(row, 0))
        if not item_id:
            continue
        name = parser.read_string(parser.read_int64(row, 32))
        if name.startswith("[DNT]"):
            excluded_dnt += 1
            continue
        class_idx = parser.read_int32(row, 8)
        cls = classes.get(class_idx, {"id": "", "name": ""})
        items[item_id] = {
            "id": item_id,
            "row_index": i,
            "name": name if name else item_id,
            "item_class": cls["id"],
            "item_class_name": cls["name"],
        }
    return items, excluded_dnt


def main() -> int:
    classes_path = GAME_BALANCE / "itemclasses.datc64"
    base_path = GAME_BALANCE / "baseitemtypes.datc64"
    if not classes_path.is_file() or not base_path.is_file():
        print(f"ERROR: extracted data not found under {GAME_BALANCE}")
        print("Run the extraction pipeline first (see CLAUDE.md Data Lifecycle).")
        return 1

    classes = load_item_classes(classes_path)
    items, excluded_dnt = extract_base_items(base_path, classes)

    if not items:
        print("ERROR: extracted 0 base items — refusing to write an empty canonical file.")
        return 1

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": {
            "source": "baseitemtypes.datc64 + itemclasses.datc64 (.datc64 extraction, #205)",
            "total_base_items": len(items),
            "total_item_classes": len(classes),
            "excluded_dnt_rows": excluded_dnt,
        },
        "base_items": items,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"Wrote {len(items)} base items ({len(classes)} item classes, "
        f"{excluded_dnt} DNT rows excluded) to {OUTPUT_PATH}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
