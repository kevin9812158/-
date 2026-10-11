"""驗證 locate_audio.py 的起點精度：拿「前面有停頓」的命中，比較辨識給的起點和聲音能量實際開口的時間。

用法：python3 check_onset.py audio_positions.tsv full.wav [樣本數]
- 只取 coverage＝完整、且起點前 0.4 秒內幾乎無聲的命中（才量得到開口點）。
- 開口點：10 ms 一格的 RMS，從起點前 0.6 秒往後找，第一個連續 3 格超過「前段靜音 RMS×4」的位置。
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


def main(tsv, wav, n=200):
    rows = [r for r in csv.DictReader(open(tsv, encoding="utf-8"), delimiter="\t")
            if r.get("start") and r.get("coverage") == "完整"]
    step = max(1, len(rows) // int(n))
    diffs = []
    with sf.SoundFile(wav) as f:
        for r in rows[::step]:
            st = ts(r["start"])
            a = max(0, st - 1.0)
            f.seek(int(a * SR))
            x = f.read(int(1.6 * SR), dtype="float32")
            rms = np.sqrt(np.convolve(x ** 2, np.ones(HOP) / HOP, mode="valid")[::HOP] + 1e-12)
            t = a + np.arange(len(rms)) * HOP / SR
            pre = rms[(t >= st - 1.0) & (t < st - 0.6)]
            if len(pre) < 10:
                continue
            floor = np.percentile(pre, 50)
            if floor > 0.01:          # 前面不是停頓，量不到開口點
                continue
            thr = floor * 4
            idx = np.where(t >= st - 0.6)[0]
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
