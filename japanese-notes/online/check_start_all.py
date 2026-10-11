"""全面時間一致性檢查：對每一筆 usable＝Y 的命中，從起點前 1.5 秒切到終點後 0.5 秒重新辨識（帶時間戳），
比較目標「第二個字」在這次辨識和原本整段辨識中的時間。
（模型常把每段輸入的第一個字標在輸入的最開頭，所以不比第一個字；第一個字＝片段起點的情況由 check_onset.py 用能量驗證。）

用法：python3 check_start_all.py audio_positions_checked.tsv 音檔.wav 模型資料夾 asr_full.jsonl 原始音檔.wav
"""
import csv
import sys

import numpy as np
import pykakasi
import sherpa_onnx
import soundfile as sf
from rapidfuzz import fuzz

SR = 16000
KKS = pykakasi.kakasi()


def ts(s):
    h, m, r = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(r)


def main(tsv, wav, model, asr_p, main_wav):
    sys.path.insert(0, __file__.rsplit("/", 2)[0] + "/online")
    import bisect
    import locate_audio as L
    mstream, mtimes, _ = L.asr_stream(asr_p, main_wav)
    mstarts = [t[0] for t in mtimes]
    rec = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=f"{model}/encoder-epoch-99-avg-1.int8.onnx", decoder=f"{model}/decoder-epoch-99-avg-1.onnx",
        joiner=f"{model}/joiner-epoch-99-avg-1.int8.onnx", tokens=f"{model}/tokens.txt",
        num_threads=4, sample_rate=SR, feature_dim=80)
    f = sf.SoundFile(wav)
    diffs, worst = [], []
    for r in csv.DictReader(open(tsv, encoding="utf-8"), delimiter="\t"):
        if r.get("usable") != "Y":
            continue
        st, en = ts(r["start"]), ts(r["end"])
        a = max(0, st - 1.5)
        f.seek(int(a * SR)); x = f.read(int((en + 0.5 - a) * SR), dtype="float32")
        s = rec.create_stream(); s.accept_waveform(SR, x); rec.decode_stream(s)
        toks, tt = list(s.result.tokens), list(s.result.timestamps)
        if len(toks) < 2:
            continue
        # 每個文字字元：所屬 token 的起點、終點、token 編號
        cs, ce, ci = [], [], []
        for i, tok in enumerate(toks):
            e = tt[i + 1] if i + 1 < len(tt) else tt[i] + 0.3
            for _ in tok:
                cs.append(tt[i]); ce.append(min(e, tt[i] + 0.6)); ci.append(i)
        text = "".join(toks)
        chars, times, tokidx = [], [], []
        pos = 0
        for w in KKS.convert(text):
            o = w["orig"]; rd = "ひと" if o == "人" else w["hira"]
            rk = [c for c in rd if "ぁ" <= c <= "ゖ" or c == "ー"]
            sp = range(pos, min(pos + len(o), len(cs)))
            if sp and rk:
                t0, t1 = cs[sp[0]], ce[sp[-1]]
                for j, c in enumerate(rk):
                    chars.append(c); times.append(t0 + (t1 - t0) * j / len(rk))
                    tokidx.append(ci[sp[0] + min(len(sp) - 1, j * len(sp) // len(rk))])
            pos += len(o)
        hay = "".join(chars)
        q = r["kana"]
        al = fuzz.partial_ratio_alignment(q, hay)
        if al is None or al.score < 80 or not times:
            continue
        # 取目標裡第一個「不是片段第一個 token」的字，比較它在兩次辨識中的時間
        k = next((j for j in range(al.dest_start, min(al.dest_end, len(times))) if tokidx[j] >= 1), None)
        if k is None:
            continue
        off = k - al.dest_start            # 這個字是目標讀音的第幾個字
        t_clip = a + times[k]
        i = bisect.bisect_left(mstarts, st - 1e-3)
        if i + off >= len(mtimes):
            continue
        t_main = mtimes[i + off][0]
        d = t_main - t_clip
        diffs.append(d); worst.append((abs(d), d, r["no"], r["text"], r["start"]))
    d = np.array(diffs); ad = np.abs(d)
    print(f"第二個字時間一致性 {len(d)} 筆：|差值| 中位數 {np.median(ad) * 1000:.0f} ms、90% {np.percentile(ad, 90) * 1000:.0f} ms、"
          f"99% {np.percentile(ad, 99) * 1000:.0f} ms、最大 {ad.max() * 1000:.0f} ms；超過 1000 ms：{(ad > 1).sum()} 筆")
    for w in sorted(worst, reverse=True)[:10]:
        print(f"  {w[1] * 1000:+.0f} ms  #{w[2]} {w[3]}  {w[4]}")


if __name__ == "__main__":
    main(*sys.argv[1:6])
