"""把審閱項目匯出成「聲調審閱台」頁面的資料（每條一筆），供寫入 Artifact 的 db。

用法：python3 scripts/review_export.py note.json mcp結果.json > items.json
每筆：{order, risk, jp, zh, basis, mcpReading, source（note.json 原行）, segs:[{kana, marks, fromMcp, units, after（片段後的標點）}]}
"""
import json
import sys

from mcp_apply import hira, line_morae, plain
from review_list import collect, seg_marks
from build_note import parse_line, split_mora


def seg_units(line):
    """每個語音片段的組成單位（同一個漢字的ルビ是一個單位，不能從中間切）與片段後面的標點。
    單位：{n: 拍數, base: 字面, ruby: 讀音或 null, gap: 是否為接續文字}。"""
    units, afters = [], []
    for it in parse_line(line, 0):
        if it["kind"] != "seg":
            if afters:
                afters[-1] += it["text"]
            continue
        us = [{"n": len(split_mora(r)) if r else 1, "base": b, "ruby": r, "gap": False} for b, r in it["parts"]]
        us += [{"n": len(split_mora(shown)), "base": shown, "ruby": said if said != shown else None, "gap": True}
               for shown, said in it["gaps"]]
        units.append(us)
        afters.append("")
    return units, afters


def export(note_p, mcp_p):
    note = json.load(open(note_p, encoding="utf-8"))
    results = {r["text"]: r for r in json.load(open(mcp_p, encoding="utf-8"))}
    items = []
    for jp, zh in collect(note):
        text = plain(jp)
        segs = line_morae(jp)
        sm = seg_marks(jp)
        res = results.get(text)
        from_mcp = all(ok for _, ok in sm)
        theirs = "".join(hira(m) for t in (res or {}).get("tokens", []) if t.get("kind") == "word" for m in t["moras"])
        if res is None:
            rank, basis = 0, "沒有 MCP 結果，暫畫 0 號"
        elif not from_mcp:
            rank, basis = 0, f"讀音和 MCP 不一致（MCP 讀 {theirs}），暫畫 0 號"
        else:
            warns = sorted({w for t in res["tokens"] for w in t.get("warnings", [])})
            nulls = [t["surface"] for t in res["tokens"] if t.get("kind") == "word" and t.get("accent") is None]
            if res.get("needsReview") or warns or nulls:
                bits = (["MCP 標 worker_needs_review"] if "worker_needs_review" in warns else []) + \
                       (["號數未解：" + "、".join(nulls)] if nulls else [])
                rank, basis = 1, "；".join(bits) or "needsReview"
            else:
                rank, basis = 2, "MCP 無警告（仍是預測）"
        units, afters = seg_units(jp)
        items.append({"rank": rank, "risk": "低" if rank == 2 else "高", "jp": text, "zh": zh, "basis": basis,
                      "mcpReading": theirs, "source": jp,
                      "segs": [{"kana": k, "marks": m, "fromMcp": ok, "units": u, "after": a}
                               for k, (m, ok), u, a in zip(segs, sm, units, afters)]})
    items.sort(key=lambda x: x["rank"])
    for i, it in enumerate(items, 1):
        it["order"] = i
        del it["rank"]
    return items


if __name__ == "__main__":
    json.dump(export(*sys.argv[1:3]), sys.stdout, ensure_ascii=False)
