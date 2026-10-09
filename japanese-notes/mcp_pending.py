"""把 JAPANESE UP 聲調 MCP（analyzeJapanesePronunciation）的原始 JSON 轉成待確認清單項目。

用法：
  python3 mcp_pending.py 結果1.json [結果2.json ...] [--ref 已知資料.json] > pending_mcp.json

輸入：每個檔案是一筆 MCP 原始回傳（或多筆組成的陣列），不要先改寫內容。
--ref：已知聲調（範本紅線或已核對資料），格式 {"勤める": 3, "ガチョウ肉": 2}。
輸出：note.json pending.lines 可直接使用的項目陣列 [{level, item, basis, action}]。

分流依據只用 MCP 回傳的欄位（needsReview、warnings、accent、status、reviewStatus）與對照資料：
- 高：有 warnings、accent 為 null、needsReview 為 true；與範本或已知資料不一致；同一詞（含漢字或片假名）在不同查詢的 marks 不一致。
- 低：沒有警告且 needsReview 為 false。伺服器有把握，但仍是預測（predicted／unreviewed），照樣列出。
依規則補上的部分（例如句中助詞的高低）由撰寫者另外列為高風險，不在此判斷。
"""
import json
import sys


def load_results(paths):
    out = []
    for p in paths:
        data = json.load(open(p, encoding="utf-8"))
        out.extend(data if isinstance(data, list) else [data])
    return out


def word_tokens(res):
    return [t for t in res.get("tokens", []) if t.get("kind") == "word"]


def fmt_tokens(res):
    return "、".join(f"{t['surface']} {t['marks']}" + (f"（{t['accent']}號）" if t.get("accent") is not None else "")
                     for t in word_tokens(res))


def analyze(results, ref):
    items, seen = [], {}
    for res in results:
        text, words = res["text"], word_tokens(res)
        reasons = []
        if res.get("needsReview"):
            reasons.append("needsReview")
        warns = sorted({w for t in res.get("tokens", []) for w in t.get("warnings", [])} | set(res.get("warnings", [])))
        if warns:
            reasons.append("warnings：" + "、".join(warns))
        nulls = [t["surface"] for t in words if t.get("accent") is None]
        if nulls:
            reasons.append("accent null：" + "、".join(nulls))
        if text in ref:
            got = words[0].get("accent") if len(words) == 1 else None
            if got != ref[text]:
                reasons.append(f"與已知資料不一致：已知 {ref[text]} 號，MCP 回傳 {fmt_tokens(res)}")
        state = f"{res.get('reviewStatus', '?')}／{','.join(sorted({t.get('status', '?') for t in words}))}"
        if reasons:
            items.append({"level": "高", "item": text,
                          "basis": "MCP：" + "；".join(reasons) + f"（{fmt_tokens(res)}；{state}）",
                          "action": "請核對"})
        else:
            items.append({"level": "低", "item": text,
                          "basis": f"MCP 無警告、needsReview: false，仍是預測（{fmt_tokens(res)}；{state}）",
                          "action": "抽樣核對"})
        for t in words:
            if not all("ぁ" <= c <= "ゖ" for c in t["surface"]):  # 只比對含漢字／片假名的詞，助詞與詞尾本來就隨前後文變
                seen.setdefault(t["surface"], []).append((text, t["marks"]))
    for surface, uses in seen.items():
        if len({tuple(m) for _, m in uses}) > 1:
            detail = "；".join(f"{src} {m}" for src, m in uses)
            items.append({"level": "高", "item": surface,
                          "basis": f"同一詞在不同查詢的 marks 不一致（未必帶警告）：{detail}",
                          "action": "請核對"})
    return items


if __name__ == "__main__":
    args, ref = sys.argv[1:], {}
    if "--ref" in args:
        i = args.index("--ref")
        ref = json.load(open(args[i + 1], encoding="utf-8"))
        del args[i:i + 2]
    json.dump(analyze(load_results(args), ref), sys.stdout, ensure_ascii=False, indent=2)
    print()
