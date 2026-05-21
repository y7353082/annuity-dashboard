#!/usr/bin/env python3
"""Embed converted JSON data into the HTML page for auto-loading."""
import json
import glob


def main():
    # Read all converted JSON files
    all_quarters = {}
    for filepath in sorted(glob.glob('annuity_data_*_converted.json')):
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        quarter = data['quarter']
        all_quarters[quarter] = data.get('data', {})

    # Generate JS object
    js_data = json.dumps(all_quarters, ensure_ascii=False, indent=2)

    # Read HTML
    with open('annuity-collector.html', 'r', encoding='utf-8') as f:
        html = f.read()

    # Find the marker right before "// ==================== Init ===================="
    marker = '// ==================== Init ===================='
    insert_code = f'''
// ==================== 预加载数据 ====================
// 从excel_preview.json转换的博时基金历史数据
const PRELOADED_QUARTER_DATA = {js_data};

function loadPreloadedData() {{
  Object.entries(PRELOADED_QUARTER_DATA).forEach(([quarter, instData]) => {{
    const storageKey = `annuity_data_${{quarter}}`;
    // Only load if localStorage doesn't have this quarter yet
    const existing = localStorage.getItem(storageKey);
    if (!existing) {{
      localStorage.setItem(storageKey, JSON.stringify(instData));
      console.log(`预加载数据: ${{quarter}}`);
    }}
  }});
}}

'''

    if marker in html:
        html = html.replace(marker, insert_code + marker)
        print(f"Inserted preload data for {len(all_quarters)} quarters into HTML.")
    else:
        print("ERROR: Could not find insertion marker in HTML.")
        return

    # Also update the init section to call loadPreloadedData before renderTable
    old_init = '''// Init
renderTable();'''
    new_init = '''// Init
loadPreloadedData();
renderTable();'''

    if old_init in html:
        html = html.replace(old_init, new_init)
        print("Updated init to call loadPreloadedData().")
    else:
        print("WARNING: Could not find init block to update.")

    # Write back
    with open('annuity-collector.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print("\nDone! Refresh the page to see the data.")


if __name__ == '__main__':
    main()
