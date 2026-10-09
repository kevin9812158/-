"""產生聲調審閱對照表（Markdown），貼在對話裡讓使用者逐條選填。

用法：
  python3 scripts/review_list.py note.json mcp結果.json > review.md

每一條：編號｜風險｜日文｜讀音（依語音片段，用｜分隔）｜中文｜目前聲調｜依據。
- 目前聲調同時給兩種寫法：每個片段的 [N] 號數，以及 NHK 辭典式的下降標記（＼ 寫在下降前的那一拍後面，沒有 ＼ 表示不下降）。
- 依風險排序：讀音和 MCP 不一致 → MCP 有警告／accent null → 其餘（MCP 無警告，仍是預測）。

使用者回覆時可以用：
  3：2 號／3 [2]／3 わりびき＼ は
  也可以只改某個片段：「5 的 はじまります 改成 4 號」。
"""
import json
import sys

from build_note import parse_line, split_mora
from mcp_apply import hira, line_morae, plain, walk


def seg_number(marks):
    """片段 marks → 號數（第幾拍後下降；0＝不下降）。全低回傳 None。"""
    if not any(m >= 1 for m in marks):
        return None
    for i, m in enumerate(marks):
        if m >= 1 and i + 1 < len(marks) and marks[i + 1] == 0:
            return i + 1
    return 0


def nhk(kana, marks):
    out = ""
    for i, (k, m) in enumerate(zip(kana, marks)):
        out += k
        if m >= 1 and i + 1 < len(marks) and marks[i + 1] == 0:
            out += "＼"
    return out


def seg_marks(line):
    """每個語音片段的 marks（有 #m: 用它，否則依號數推算）。"""
    res = []
    for it in parse_line(line, 0):
        if it["kind"] != "seg":
            continue
        n = sum(len(split_mora(r)) if r else 1 for _, r in it["parts"]) + sum(len(split_mora(s)) for s, _ in it["gaps"])
        if it.get("marks") and len(it["marks"]) == n:
            res.append((it["marks"], True))
        else:
            a = it["accent"] or 0
            res.append(([0 if (i == 0 and a != 1) or (a and i >= a) else 1 for i in range(n)], False))
    return res


def collect(note):
    """(日文行, 中文) 依出現順序，去重。"""
    rows = []

    def add(jp, zh):
        if jp not in [r[0] for r in rows]:
            rows.append((jp, zh))

    def visit(x):
        if isinstance(x, dict):
            if x.get("type") == "grid":
                for row in x["rows"]:
                    zh = row[0] if isinstance(row[0], str) else ""
                    for c in row:
                        if isinstance(c, dict) and "jp" in c:
                            add(c["jp"], zh)
                return
            if "term_jp" in x:
                add(x["term_jp"], x.get("term_sub", ""))
            if "jp" in x:
                add(x["jp"], x.get("zh", ""))
            for v in x.values():
                visit(v)
        elif isinstance(x, list):
            for v in x:
                visit(v)

    visit(note["blocks"])
    return rows


def main(note_p, mcp_p):
    note = json.load(open(note_p, encoding="utf-8"))
    results = {r["text"]: r for r in json.load(open(mcp_p, encoding="utf-8"))}
    items = []
    for jp, zh in collect(note):
        text = plain(jp)
        segs = line_morae(jp)
        sm = seg_marks(jp)
        reading = "｜".join("".join(s) for s in segs)
        nums = " ".join(f"[{seg_number(m) if seg_number(m) is not None else '?'}]" for m, _ in sm)
        accent = "｜".join(nhk(s, m) for s, (m, _) in zip(segs, sm))
        from_mcp = all(ok for _, ok in sm)
        res = results.get(text)
        if res is None:
            rank, basis = 0, "沒有 MCP 結果，暫畫 0 號"
        elif not from_mcp:
            theirs = "".join(hira(m) for t in res["tokens"] if t.get("kind") == "word" for m in t["moras"])
            rank, basis = 0, f"讀音和 MCP 不一致（MCP：{theirs}），暫畫 0 號"
        else:
            warns = sorted({w for t in res["tokens"] for w in t.get("warnings", [])})
            nulls = [t["surface"] for t in res["tokens"] if t.get("kind") == "word" and t.get("accent") is None]
            if res.get("needsReview") or warns or nulls:
                bits = []
                if "worker_needs_review" in warns:
                    bits.append("MCP 標 worker_needs_review")
                if nulls:
                    bits.append("號數未解：" + "、".join(nulls))
                rank, basis = 1, "；".join(bits) or "needsReview"
            else:
                rank, basis = 2, "MCP 無警告（仍是預測）"
        items.append((rank, text, reading, zh, nums, accent, basis))
    items.sort(key=lambda x: x[0])
    label = {0: "高", 1: "高", 2: "低"}
    print("| # | 風險 | 日文 | 讀音 | 中文 | 目前聲調 | 依據 |")
    print("|---|---|---|---|---|---|---|")
    for i, (rank, text, reading, zh, nums, accent, basis) in enumerate(items, 1):
        print(f"| {i} | {label[rank]} | {text} | {reading} | {zh} | {nums}<br>{accent} | {basis} |")


if __name__ == "__main__":
    main(*sys.argv[1:3])
