"""把 JAPANESE UP 聲調 MCP 的逐拍 marks 套進 note.json 的日文行。

用法：
  python3 mcp_apply.py note.json mcp結果.json 輸出note.json 不一致清單.json

- mcp結果.json：analyzeJapanesePronunciation 的原始回傳陣列（每行一筆，text 為該行的純文字）。
- 只在「筆記讀音和 MCP 讀音逐拍一致」時套用，寫成每個語音片段的 #m:0112；
  不一致（例：何＝なん／MCP なに、一割＝いち／MCP ひと）或沒查到的行維持原樣（0 號音），
  記在不一致清單，供待確認清單列為【高】。
- 不自行補齊或改寫 MCP 的值：助詞等 MCP 回傳的 0 照樣畫成低。
"""
import json
import re
import sys

from build_note import parse_line, split_mora

VOWELS = set("あいうえお")


def hira(s):
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def plain(line):
    out = []
    for seg in line.split("／"):
        seg = seg.strip()
        if seg.startswith(("!", "@")):
            out.append(seg[1:]); continue
        seg = re.sub(r"#\S+$", "", seg)
        body, *gaps = seg.split("+")
        body = re.sub(r"\{([^|}]+)\|[^}]+\}", r"\1", body)
        out.append(body + "".join(g.split("=")[0] for g in gaps))
    return "".join(out)


def line_morae(line):
    """每個語音片段的拍（假名）：[[拍, ...], ...]；標點、標籤不算片段。"""
    segs = []
    for it in parse_line(line, 0):
        if it["kind"] != "seg":
            continue
        mo = []
        for base, ruby in it["parts"]:
            mo += split_mora(ruby) if ruby else [base]
        for shown, _said in it["gaps"]:
            mo += split_mora(shown)
        segs.append([hira(m) for m in mo])
    return segs


def same(a, b):
    return a == b or ("ー" in (a, b) and (a + b).replace("ー", "") in VOWELS)


def apply_line(line, res):
    """回傳 (新行或 None, 筆記讀音, MCP 讀音)。"""
    segs = line_morae(line)
    ours = [m for s in segs for m in s]
    words = [t for t in res["tokens"] if t.get("kind") == "word"]
    theirs = [hira(m) for t in words for m in t["moras"]]
    marks = [m for t in words for m in t["marks"]]
    r_ours, r_theirs = "".join(ours), "".join(theirs)
    if len(ours) != len(theirs) or not all(same(a, b) for a, b in zip(ours, theirs)):
        return None, r_ours, r_theirs
    out, i, k = [], 0, 0
    for raw in line.split("／"):
        s = raw.strip()
        if not s or s.startswith(("!", "@")):
            out.append(raw); continue
        s = re.sub(r"#\S+$", "", s)
        n = len(segs[k]); k += 1
        out.append(s + "#m:" + "".join(str(m) for m in marks[i:i + n])); i += n
    return "／".join(out), r_ours, r_theirs


def walk(x, fn):
    if isinstance(x, dict):
        for key, v in x.items():
            if key in ("jp", "term_jp") and isinstance(v, str):
                x[key] = fn(v)
            else:
                walk(v, fn)
    elif isinstance(x, list):
        for v in x:
            walk(v, fn)


if __name__ == "__main__":
    note_p, mcp_p, out_p, mis_p = sys.argv[1:5]
    note = json.load(open(note_p, encoding="utf-8"))
    results = {r["text"]: r for r in json.load(open(mcp_p, encoding="utf-8"))}
    mismatches, applied = [], 0

    def fn(line):
        global applied
        text = plain(line)
        res = results.get(text)
        if res is None:
            mismatches.append({"text": text, "reason": "沒有 MCP 結果"}); return line
        new, ours, theirs = apply_line(line, res)
        if new is None:
            mismatches.append({"text": text, "reason": f"讀音不一致：筆記 {ours}／MCP {theirs}"}); return line
        applied += 1
        return new

    walk(note["blocks"], fn)
    json.dump(note, open(out_p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(mismatches, open(mis_p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"套用 {applied} 行，未套用 {len(mismatches)} 行", file=sys.stderr)
