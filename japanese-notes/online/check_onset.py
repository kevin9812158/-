"""驗證 locate_audio.py 的起點精度：拿「前面有停頓」的命中，比較辨識給的起點和聲音能量實際開口的時間。

用法：python3 check_onset.py audio_positions.tsv full.wav asr_full.jsonl
- 只取 coverage＝完整、且起點剛好是 VAD 說話片段第一個字的命中（前面確定是停頓，量得到開口點）。
- 開口點：10 ms 一格的 RMS；靜音基準取片段起點前 1.5～0.3 秒的中位數，
  從片段起點前 0.3 秒往後找第一個連續 3 格超過基準×4 的位置（最多找到辨識起點後 0.5 秒）。
- 輸出每筆的差值（辨識起點－開口點），以及絕對值的中位數、90 百分位、最大值、超過 1 秒的筆數。
"""
import csv
import sys

import numpy as np
import soundfile as sf

SR = 16000
HOP = 160


def ts(s):
    h, m, rest = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def main(tsv, wav, asr):
    import json
    first_tok = {}
    for line in open(asr, encoding="utf-8"):
        seg = json.loads(line)
        if seg["ts"]:
            first_tok[round(seg["ts"][0], 3)] = seg["start"]
    rows = [r for r in csv.DictReader(open(tsv, encoding="utf-8"), delimiter="\t")
            if r.get("start") and r.get("coverage") == "完整" and round(ts(r["start"]), 3) in first_tok]
    diffs = []
    with sf.SoundFile(wav) as f:
        for r in rows:
            st = ts(r["start"])
            vs = first_tok[round(st, 3)]
            a = max(0, vs - 1.5)
            f.seek(int(a * SR))
            x = f.read(int((st - a + 0.6) * SR), dtype="float32")
            rms = np.sqrt(np.convolve(x ** 2, np.ones(HOP) / HOP, mode="valid")[::HOP] + 1e-12)
            t = a + np.arange(len(rms)) * HOP / SR
            pre = rms[(t >= vs - 1.5) & (t < vs - 0.3)]
            if len(pre) < 10:
                continue
            floor = np.percentile(pre, 50)
            thr = floor * 4
            idx = np.where((t >= vs - 0.3) & (t <= st + 0.5))[0]
            onset = None
            for i in idx[:-3]:
                if (rms[i:i + 3] > thr).all():
                    onset = t[i]; break
            if onset is None:
                continue
            diffs.append((st - onset, r["no"], r["text"], r["start"]))
    d = np.array([x[0] for x in diffs])
    ad = np.abs(d)
    print(f"樣本 {len(d)} 筆；|差值| 中位數 {np.median(ad) * 1000:.0f} ms、90 百分位 {np.percentile(ad, 90) * 1000:.0f} ms、"
          f"最大 {ad.max() * 1000:.0f} ms；平均差值（辨識－開口）{d.mean() * 1000:+.0f} ms；超過 1000 ms：{(ad > 1).sum()} 筆")
    for x in sorted(diffs, key=lambda x: -abs(x[0]))[:10]:
        print(f"  {x[0] * 1000:+.0f} ms\t#{x[1]} {x[2]}\t{x[3]}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
