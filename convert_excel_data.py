#!/usr/bin/env python3
"""Convert excel_preview.json to annuity-collector page format."""
import json
from collections import defaultdict

# Mapping from Chinese names to page keys
PLAN_MAP = {
    '单一计划': 'single',
    '集合计划': 'pooled',
    '其他计划': 'other',
}
TYPE_MAP = {
    '固定收益类': 'fixed',
    '含权益类': 'equity',
}


def convert_time(time_str):
    """Convert '2022年1季度' to '2022Q1'."""
    parts = time_str.replace('年', ' ').replace('季度', '').split()
    year = parts[0]
    quarter = parts[1]
    return f"{year}Q{quarter}"


def main():
    with open('excel_preview.json', 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Group by quarter, then by institution, then by category
    # Structure: {quarter: {inst_name: {cat_key: {count, nav, return}}}}
    quarters = defaultdict(lambda: defaultdict(dict))

    for row in data['rows']:
        time_str, inst_name, plan, type_name, count, nav, ret = row
        quarter = convert_time(time_str)

        plan_key = PLAN_MAP.get(plan)
        type_key = TYPE_MAP.get(type_name)
        if not plan_key or not type_key:
            continue

        cat_key = f"{plan_key}_{type_key}"
        quarters[quarter][inst_name][cat_key] = {
            "count": str(count),
            "nav": str(nav),
            "return": str(ret),
        }

    # Save each quarter as a separate JSON file
    for quarter, inst_data in sorted(quarters.items()):
        output = {
            "quarter": quarter,
            "exportDate": "2026-05-20T00:00:00",
            "source": "excel_preview",
            "data": dict(inst_data),
        }
        filename = f"annuity_data_{quarter}_converted.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"Saved: {filename} ({len(inst_data)} institutions)")

    # Also create a merged file with all quarters for bulk import
    print("\n--- Conversion Summary ---")
    for quarter in sorted(quarters.keys()):
        inst_data = quarters[quarter]
        total_cats = sum(len(cats) for cats in inst_data.values())
        print(f"  {quarter}: {len(inst_data)} institutions, {total_cats} records")


if __name__ == '__main__':
    main()
