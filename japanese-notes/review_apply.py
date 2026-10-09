"""把「聲調審閱台」的審閱結果寫回 note.json。

用法：
  python3 review_apply.py note.json items.json reviews資料夾 輸出note.json > 報告.txt

- items.json：review_export.py 匯出的項目（每條有 source、segs[].units、segs[].after）。
- reviews資料夾：ArtifactData list（out_dir）存下的 <編號>.json，內容 {status, line:[{m, gap, br}], instruction}。
- 每個審閱台片段寫成 note.json 的一個語音片段，聲調寫成 `#m:`（m＝2，或 1 後面接 0 → 2）。
  片段各自畫線，和審閱台的顯示一致；GAP 片段照樣獨立成段（只影響語意，不併進前一段，避免多畫下降角）。
- 切在同一個單位（一個漢字或一組數字的ルビ）中間時：數字逐字拆開重配讀音；其他情況把分界移到單位結尾，並在報告中列出。
- instruction（其他問題）不自動處理，列在報告中由 Claude 逐條執行。
"""
import json
import os
import sys

from build_note import split_mora


def unit_text(base, ruby, gap):
    if ruby and not gap:
        return "{%s|%s}" % (base, ruby)
    return base  # 接續文字（例：は＝わ）照字面寫，讀音不另標


def morae_of(item):
    """攤平成拍，每拍記：所屬單位、在單位內的序號、單位資訊；片段後的標點記在最後一拍。"""
    out = []
    for si, seg in enumerate(item["segs"]):
        units = seg.get("units") or [{"n": 1, "base": k, "ruby": None, "gap": False} for k in seg["kana"]]
        for ui, u in enumerate(units):
            for j in range(u["n"]):
                out.append({"unit": (si, ui), "j": j, "u": u, "after": ""})
        out[-1]["after"] = seg.get("after", "")
    return out


def split_digits(u, cut):
    """數字單位在第 cut 拍切開：把每個數字配上讀音（2→にじゅう、5→ご 這種由讀音長度決定）。"""
    rm = split_mora(u["ruby"])
    left, right = "".join(rm[:cut]), "".join(rm[cut:])
    base = u["base"]
    if len(base) == 2 and base.isdigit():
        return [{"n": cut, "base": base[0], "ruby": left, "gap": u["gap"]},
                {"n": len(rm) - cut, "base": base[1], "ruby": right, "gap": u["gap"]}]
    return None


def rebuild(item, line):
    ms = morae_of(item)
    warn = []
    # 片段分界：br；切在單位中間時處理
    cuts = [i for i, x in enumerate(line) if i and x["br"]]
    pieces = []  # [(units_for_segment, marks, gaps, after)]
    seg_start = 0
    bounds = cuts + [len(ms)]
    starts = [0] + cuts
    # 先把每拍對應到「輸出單位」：遇到單位中間的分界時拆單位
    unit_of = {}
    for i, m in enumerate(ms):
        unit_of[i] = m["unit"]
    for c in cuts:
        if ms[c]["j"] != 0:  # 切在單位中間
            u = ms[c]["u"]
            sp = split_digits(u, ms[c]["j"]) if u.get("ruby") else None
            if sp:
                k = c - ms[c]["j"]
                for t in range(u["n"]):
                    part = 0 if t < ms[c]["j"] else 1
                    ms[k + t] = {**ms[k + t], "unit": ms[k + t]["unit"] + (part,), "u": sp[part], "j": t if part == 0 else t - ms[c]["j"]}
            else:
                warn.append(f"切在「{u['base']}」的讀音中間，分界移到單位結尾")
                # 移到單位結尾
                end = c
                while end < len(ms) and ms[end]["j"] != 0:
                    end += 1
                line[c]["br"] = False
                if end < len(ms):
                    line[end]["br"] = True
    cuts = [i for i, x in enumerate(line) if i and x["br"]]
    starts, ends = [0] + cuts, cuts + [len(ms)]
    segs_out = []
    for a, b in zip(starts, ends):
        text, seen, marks = "", [], []
        for i in range(a, b):
            key = ms[i]["unit"]
            if key not in seen:
                seen.append(key)
                u = ms[i]["u"]
                body_before = any(not line[t]["gap"] for t in range(a, i))
                if line[i]["gap"] and body_before:  # 片段裡的接續文字：+は=わ
                    text += "+" + u["base"] + ("=" + u["ruby"] if u.get("gap") and u.get("ruby") else "")
                else:
                    text += unit_text(u["base"], u.get("ruby"), u.get("gap"))
            m = line[i]["m"]
            nxt = line[i + 1]["m"] if i + 1 < b else None
            marks.append(2 if m == 2 or (m == 1 and nxt == 0) else m)
        segs_out.append((text, "".join(map(str, marks)), ms[b - 1]["after"]))
    out = []
    for text, mk, after in segs_out:
        out.append(f"{text}#m:{mk}")
        if after:
            out.append("!" + after)
    return "／".join(out), warn


def walk(x, fn):
    if isinstance(x, dict):
        for k, v in x.items():
            if k in ("jp", "term_jp") and isinstance(v, str):
                x[k] = fn(v)
            else:
                walk(v, fn)
    elif isinstance(x, list):
        for v in x:
            walk(v, fn)


if __name__ == "__main__":
    note_p, items_p, rev_dir, out_p = sys.argv[1:5]
    note = json.load(open(note_p, encoding="utf-8"))
    items = {it["order"]: it for it in json.load(open(items_p, encoding="utf-8"))}
    repl, report = {}, []
    for name in sorted(os.listdir(rev_dir), key=lambda n: int(n.split(".")[0])):
        doc = json.load(open(os.path.join(rev_dir, name), encoding="utf-8"))
        r = doc.get("data", doc)
        it = items[int(name.split(".")[0])]
        line = r.get("line")
        if line and len(line) == len(morae_of(it)):
            new, warn = rebuild(it, [dict(x) for x in line])
            if new != it["source"]:
                repl[it["source"]] = new
            report += [f"#{it['order']} {w}" for w in warn]
        if r.get("instruction"):
            report.append(f"#{it['order']} 其他問題：{r['instruction']}")
    walk(note["blocks"], lambda v: repl.get(v, v))
    json.dump(note, open(out_p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"改寫 {len(repl)} 行")
    for k, v in repl.items():
        print(f"  {k}\n→ {v}")
    for r in report:
        print(r)
