"""用帶時間戳的日文語音辨識結果，找出筆記每一行在音軌裡的朗讀位置（精度目標 1 秒內）。

用法：python3 locate_audio.py note.json asr_full.jsonl 側錄檔名 > audio_positions.tsv

- asr_full.jsonl：asr_timestamps.py 的輸出（每個 token 有起點秒數）。
- 兩邊都轉成平假名再比對：筆記用 note.json 的ルビ（最準），辨識結果用 pykakasi 轉讀音，
  每個讀音字元記住它來自哪個 token，命中後取第一個 token 的起點、最後一個 token 的終點當時間。
- 句子可能被 VAD 切成好幾段，所以每次比對都接上後面間隔 2 秒內的片段。
- coverage：「完整」＝句首到句尾都對上；「缺頭／缺尾」＝句首或句尾有 2 拍以上對不上（1 拍以內的差異視為完整），起點或終點可能偏移超過 1 秒，要人工確認。
- 4 拍以下的短詞只在該主題的時段內找完全一致，避免到處誤判。
"""
import datetime
import difflib
import json
import re
import sys

import pykakasi
from rapidfuzz import fuzz

sys.path.insert(0, __file__.rsplit("/", 2)[0])
from mcp_apply import line_morae, plain  # noqa: E402

THRESHOLD = 85
MIN_KANA = 5
MAX_GAP = 2.0
MAX_HITS = 20
SECTION_SPAN = {"上週複習": (900, 1350), "せっかく行ったのにお店が休みだった": (1350, 2550),
                "スマホを落としてしまった": (2550, 3420), "ネットで靴を買ったら…": (3420, 6620),
                "語法複習：能力形與被動形": (6620, 8330), "新聞：「ありえない所」から車衝突": (8330, 10580)}
OVERRIDE = {"今日": "きょう", "今日は": "きょうは", "一言": "ひとこと", "何か": "なにか"}
KEEP = re.compile(r"[ぁ-ゖー]")
KKS = pykakasi.kakasi()


def hira(s):
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def asr_stream(path):
    """回傳 (讀音字串, 每字元的 (起點, 終點), 每字元所屬片段)。"""
    chars, times, segids = [], [], []
    for sid, line in enumerate(open(path, encoding="utf-8")):
        seg = json.loads(line)
        toks, ts = seg["tokens"], seg["ts"]
        if not toks:
            continue
        # 每個文字字元對應的 token 時間
        cstart, cend = [], []
        for i, tok in enumerate(toks):
            a = ts[i]
            b = ts[i + 1] if i + 1 < len(ts) else seg["end"]
            b = min(b, a + 0.6)
            for _ in tok:
                cstart.append(a); cend.append(b)
        text = "".join(toks)
        pos = 0
        for w in KKS.convert(text):
            orig = w["orig"]
            rd = OVERRIDE.get(orig, w["hira"])
            span = range(pos, min(pos + len(orig), len(cstart)))
            if span:
                a, b = cstart[span[0]], cend[span[-1]]
                rk = [c for c in hira(rd) if KEEP.match(c)]
                for j, c in enumerate(rk):
                    # 讀音字元依比例分配到 orig 的時間範圍
                    f0, f1 = j / len(rk), (j + 1) / len(rk)
                    chars.append(c); times.append((a + (b - a) * f0, a + (b - a) * f1)); segids.append(sid)
            pos += len(orig)
    return "".join(chars), times, segids


def note_lines(note):
    out = []

    def walk(o, sec):
        if isinstance(o, dict):
            if o.get("type") == "title":
                sec[0] = o["text"]
            for k, v in o.items():
                if k in ("jp", "term_jp") and isinstance(v, str):
                    out.append((sec[0], v))
                else:
                    walk(v, sec)
        elif isinstance(o, list):
            for x in o:
                walk(x, sec)
    walk(note["blocks"], [""])
    seen, uniq = set(), []
    for sec, line in out:
        # 「閉まる・閉まります」「作る→作れる」：依標點片段拆開各自找
        parts, cur = [], []
        for seg in line.split("／"):
            if seg in ("!・", "!→"):
                parts.append("／".join(cur)); cur = []
            else:
                cur.append(seg)
        parts.append("／".join(cur))
        for p in parts:
            text = plain(p)
            if text and text not in seen:
                seen.add(text)
                kana = "".join(hira("".join(s)) for s in line_morae(p))
                kana = "".join(c for c in kana if KEEP.match(c))
                uniq.append((sec, text, kana))
    return uniq


def hms(sec):
    ms = int(round(sec * 1000))
    return f"{ms // 3600000}:{ms % 3600000 // 60000:02}:{ms % 60000 // 1000:02}.{ms % 1000:03}"


def main(note_p, asr_p, rec_name):
    m = re.search(r"(\d{8})_(\d{6})(\d{3})", rec_name)
    t0 = datetime.datetime.strptime(m[1] + m[2], "%Y%m%d%H%M%S") + datetime.timedelta(milliseconds=int(m[3]))
    stream, times, segids = asr_stream(asr_p)
    # 片段邊界：每個片段的第一個字元位置
    seg_first = {}
    for i, s in enumerate(segids):
        seg_first.setdefault(s, i)
    order = sorted(seg_first)

    print("no\tsection\ttext\tkana\thits\toccurrence\tstart\tend\tclock_start\tin_section\tscore\tcoverage\tasr_kana")
    for no, (sec, text, q) in enumerate(note_lines(json.load(open(note_p, encoding="utf-8"))), 1):
        span = SECTION_SPAN.get(sec, (0, 1e9))
        short = len(q) < MIN_KANA
        if len(q) < 2:
            print(f"{no}\t{sec}\t{text}\t{q}\t-\t\t\t\t\t\t\t（記號行，不定位）"); continue
        hits = []
        for oi, sid in enumerate(order):
            i0 = seg_first[sid]
            if short and not (span[0] - 60 <= times[i0][0] <= span[1] + 60):
                continue
            # 接上後面間隔 MAX_GAP 秒內的片段
            j = oi
            end_i = seg_first[order[j + 1]] if j + 1 < len(order) else len(stream)
            while j + 1 < len(order) and end_i - i0 < len(q) * 2 + 10:
                nxt = seg_first[order[j + 1]]
                if times[nxt][0] - times[nxt - 1][1] > MAX_GAP:
                    break
                j += 1
                end_i = seg_first[order[j + 1]] if j + 1 < len(order) else len(stream)
            own_end = seg_first[order[oi + 1]] if oi + 1 < len(order) else len(stream)
            hay = stream[i0:end_i]
            masked = hay
            while True:
                al = fuzz.partial_ratio_alignment(q, masked, score_cutoff=100 if short else THRESHOLD)
                if al is None or i0 + al.dest_start >= own_end:
                    break
                snip = hay[al.dest_start:al.dest_end]
                # 用逐字對齊找出句首、句尾實際對上的字，時間取那兩個字（去掉多抓的前後字）
                blocks = [b for b in difflib.SequenceMatcher(None, q, snip, autojunk=False).get_matching_blocks() if b.size]
                if not blocks:
                    break
                qa, sa = blocks[0].a, blocks[0].b
                qb, sb = blocks[-1].a + blocks[-1].size, blocks[-1].b + blocks[-1].size
                miss = ("頭" if qa > 1 else "") + ("尾" if len(q) - qb > 1 else "")
                cov = "完整" if not miss else "缺" + miss
                a_i, b_i = i0 + al.dest_start + sa, i0 + al.dest_start + sb - 1
                hits.append((times[a_i][0], times[b_i][1], al.score, snip[sa:sb], cov))
                masked = masked[:al.dest_start] + "＿" * (al.dest_end - al.dest_start) + masked[al.dest_end:]
        hits.sort()
        # 前後片段重疊抓到的同一次朗讀：時間重疊就只留分數高的
        merged = []
        for h in hits:
            if merged and h[0] < merged[-1][1]:
                if (h[2], h[4] == "完整") > (merged[-1][2], merged[-1][4] == "完整"):
                    merged[-1] = h
                continue
            merged.append(h)
        hits = merged
        if not hits:
            print(f"{no}\t{sec}\t{text}\t{q}\t0\t\t\t\t\t\t\t（音軌裡找不到）"); continue
        for k, (a, b, sc, snip, cov) in enumerate(hits[:MAX_HITS], 1):
            clk = (t0 + datetime.timedelta(seconds=a)).strftime("%H:%M:%S")
            ins = "Y" if span[0] - 60 <= a <= span[1] + 60 else "N"
            print(f"{no}\t{sec}\t{text}\t{q}\t{len(hits)}\t{k}\t{hms(a)}\t{hms(b)}\t{clk}\t{ins}\t{sc:.0f}\t{cov}\t{snip}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
