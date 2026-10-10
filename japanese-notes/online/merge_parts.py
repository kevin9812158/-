"""把 parts/*.json 依檔名順序合併成 note_20261006.json。"""
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
parts = sorted(f for f in os.listdir(os.path.join(here, 'parts')) if f.endswith('.json'))
note = {"header": {"left": "線上課 圖文練習", "right": "2026.10.06"}, "accent_default": 0, "blocks": [], "pending": [
    {"level": "高", "item": "全篇聲調", "basis": "這次不查 MCP，所有詞一律畫 0 號音；投影片上有老師標的聲調線，可作為之後核對來源", "action": "之後再決定是否替換"}]}
for f in parts:
    p = json.load(open(os.path.join(here, 'parts', f)))
    note["blocks"] += p["blocks"]
    note["pending"] += p.get("pending", [])
json.dump(note, open(os.path.join(here, 'note_20261006.json'), 'w'), ensure_ascii=False, indent=1)
print(len(parts), 'parts,', len(note["blocks"]), 'blocks,', len(note["pending"]), 'pending')
