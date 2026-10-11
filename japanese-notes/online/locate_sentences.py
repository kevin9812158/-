"""找出筆記每一行日文在側錄音軌裡的大約位置（只定位，不切分）。

用法：python3 locate_sentences.py note.json tr_main.json 側錄檔名 > sentence_positions.tsv

- tr_main.json：Plaud 原始轉錄（transaction），每段約 1 分鐘、帶起訖毫秒。
- 比對前兩邊都轉成簡體字形再去標點，抵銷 Plaud 把日文漢字轉成繁體的問題（届→屆、注文→註文…）。
- 每段逐字稿（接上下一段，處理跨段的句子）用模糊比對找出所有出現位置；
  段內時間依字數比例內插，所以位置是估計值，誤差約 ±10 秒；cut_start／cut_end 已前後各加 10 秒。
- 4 字以下的短詞只在該主題的時間範圍內找完全一致；in_section＝命中是否落在該主題範圍內（N 可能是複習或誤判）。
- 側錄檔名的時間＝音軌 0 秒，用來換算電腦時鐘。
"""
import json
import re
import sys
import datetime

import opencc
from rapidfuzz import fuzz

sys.path.insert(0, __file__.rsplit("/", 2)[0])
from mcp_apply import plain  # noqa: E402

T2S = opencc.OpenCC("t2s")
STRIP = re.compile(r"[\s、。，,．.？?！!「」『』（）()：:／/\-…〜~“”\"・→＋+A-Za-zＡ-Ｚａ-ｚ]")
MIN_LEN = 4        # 太短的詞到處都對得上，不列
THRESHOLD = 85     # partial_ratio 門檻
MAX_HITS = 12
PAD = 10           # 建議切分餘裕（秒）
# 各主題在音軌中的大約範圍（秒，取自 shots_map／摘要對齊）；短詞只在本主題範圍內找完全一致
SECTION_SPAN = {"上週複習": (900, 1350), "せっかく行ったのにお店が休みだった": (1350, 2550),
                "スマホを落としてしまった": (2550, 3420), "ネットで靴を買ったら…": (3420, 6620),
                "語法複習：能力形與被動形": (6620, 8330), "新聞：「ありえない所」から車衝突": (8330, 10580)}


def norm(s):
    return STRIP.sub("", T2S.convert(s))


def hms(sec):
    sec = max(0, int(round(sec)))
    return f"{sec // 3600}:{sec % 3600 // 60:02}:{sec % 60:02}"


def main(note_p, tr_p, rec_name):
    m = re.search(r"(\d{8})_(\d{6})(\d{3})", rec_name)
    t0 = datetime.datetime.strptime(m[1] + m[2], "%Y%m%d%H%M%S") + datetime.timedelta(milliseconds=int(m[3]))
    tr = json.load(open(tr_p, encoding="utf-8"))
    utt = [(u["start_time"] / 1000, u["end_time"] / 1000, norm(u["content"])) for u in tr]

    note = json.load(open(note_p, encoding="utf-8"))
    lines = []

    def walk(o, section):
        if isinstance(o, dict):
            if o.get("type") == "title":
                section[0] = o["text"]
            for k, v in o.items():
                if k in ("jp", "term_jp") and isinstance(v, str):
                    lines.append((section[0], plain(v)))
                else:
                    walk(v, section)
        elif isinstance(o, list):
            for x in o:
                walk(x, section)

    walk(note["blocks"], [""])
    seen, uniq = set(), []
    for sec, text in lines:
        # 動詞卡「閉まる・閉まります」、變化「作る→作れる」：各部分分開找
        for piece in re.split(r"[・→]", text):
            piece = piece.strip()
            if piece and piece not in seen:
                seen.add(piece); uniq.append((sec, piece))

    print("no\tsection\ttext\thits\toccurrence\taudio_start\taudio_end\tcut_start\tcut_end\tclock_start\tin_section\tscore\tmatched_transcript")
    for no, (sec, text) in enumerate(uniq, 1):
        q = norm(text)
        span = SECTION_SPAN.get(sec, (0, 1e9))
        short = len(q) < MIN_LEN
        if len(q) < 2:
            print(f"{no}\t{sec}\t{text}\t-\t\t\t\t\t\t\t\t\t（太短，不定位）"); continue
        hits = []
        for i, (s, e, body) in enumerate(utt):
            if short and not (span[0] - 60 <= s <= span[1]):
                continue
            # 本段＋下一段開頭，處理跨段；只記錄起點落在本段的命中
            nxt = utt[i + 1][2][: len(q) + 5] if i + 1 < len(utt) else ""
            hay = body + nxt
            masked = hay
            while True:
                al = fuzz.partial_ratio_alignment(q, masked, score_cutoff=100 if short else THRESHOLD)
                if al is None or al.dest_start >= len(body):
                    break
                rate = (e - s) / max(1, len(body))
                a = s + al.dest_start * rate
                b = s + al.dest_end * rate
                hits.append((a, b, al.score, hay[al.dest_start:al.dest_end]))
                masked = masked[:al.dest_start] + "＿" * (al.dest_end - al.dest_start) + masked[al.dest_end:]
        hits.sort()
        if not hits:
            print(f"{no}\t{sec}\t{text}\t0\t\t\t\t\t\t\t\t\t（逐字稿裡找不到）"); continue
        for k, (a, b, sc, snip) in enumerate(hits[:MAX_HITS], 1):
            clk = (t0 + datetime.timedelta(seconds=a)).strftime("%H:%M:%S")
            ins = "Y" if span[0] - 60 <= a <= span[1] + 60 else "N"
            print(f"{no}\t{sec}\t{text}\t{len(hits)}\t{k}\t{hms(a)}\t{hms(b)}\t{hms(a - PAD)}\t{hms(b + PAD)}\t{clk}\t{ins}\t{sc:.0f}\t{snip}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
