"""用說話者把切點收緊：在已選的切法內，每 0.2 秒算 1 秒窗的聲紋，
找出「朗讀者」（Haruki 或老師）連續講話的範圍，切點收緊到該範圍兩側最近的停頓，再重新辨識確認。

用法：python3 trim_by_speaker.py refined.tsv full.wav 模型資料夾 聲紋模型.onnx centroids.npz > trimmed.tsv
- 朗讀者：片段中 Haruki 窗數 ≥ 30% 就當 Haruki（老師的中文解說常佔多數，Haruki 只念那一句）；否則老師。
- 收緊後重新辨識，相似度掉超過 0.1 就保留原切法並標記。
"""
import csv
import os
import sys

import numpy as np
import sherpa_onnx
import soundfile as sf
from rapidfuzz.distance import Levenshtein

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import locate_audio as L  # noqa: E402
from refine_cuts import kana_of, low_points  # noqa: E402

SR = 16000
HOP = 160


def ts(s):
    h, m, r = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(r)


def main(tsv, wav_p, model, spk_model, cent_p):
    rec = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=f"{model}/encoder-epoch-99-avg-1.int8.onnx", decoder=f"{model}/decoder-epoch-99-avg-1.onnx",
        joiner=f"{model}/joiner-epoch-99-avg-1.int8.onnx", tokens=f"{model}/tokens.txt",
        num_threads=4, sample_rate=SR, feature_dim=80)
    ext = sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=spk_model, num_threads=4))
    cent = np.load(cent_p)
    wav = sf.SoundFile(wav_p)

    def read(a, b):
        wav.seek(int(a * SR)); return wav.read(int((b - a) * SR), dtype="float32")

    def emb(x):
        s = ext.create_stream(); s.accept_waveform(SR, x); s.input_finished()
        v = np.array(ext.compute(s)); return v / (np.linalg.norm(v) + 1e-9)

    def decode(a, b):
        s = rec.create_stream(); s.accept_waveform(SR, read(a, b)); rec.decode_stream(s)
        return s.result.text

    rd = csv.DictReader(open(tsv, encoding="utf-8"), delimiter="\t")
    w = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    w.writerow(["no", "text", "speaker", "start", "end", "seconds", "similarity", "recognized", "note"])
    for r in rd:
        if r["selected"] != "Y":
            continue
        a, b = ts(r["start"]), ts(r["end"])
        q = kana_of(r["text"])
        # 每 0.2 秒、1 秒窗的說話者
        t, lab = [], []
        x = a
        while x + 1.0 <= b + 1e-6:
            v = emb(read(x, x + 1.0))
            sh, st_ = float(v @ cent["haruki"]), float(v @ cent["teacher"])
            lab.append("H" if sh > st_ and sh >= 0.45 else ("T" if st_ >= 0.45 else "O")); t.append(x)
            x += 0.2
        if not lab:
            w.writerow([r["no"], r["text"], r["speaker"], r["start"], r["end"], f"{b - a:.1f}", r["similarity"], r["recognized"], "片段太短，未收緊"]); continue
        who = "H" if lab.count("H") >= 0.3 * len(lab) else "T"
        idx = [i for i, l in enumerate(lab) if l == who]
        # 最長的連續段（容許中間 2 格雜訊）
        runs, cur = [], [idx[0]]
        for i in idx[1:]:
            if i - cur[-1] <= 3:
                cur.append(i)
            else:
                runs.append(cur); cur = [i]
        runs.append(cur)
        run = max(runs, key=len)
        ra, rb = t[run[0]], t[run[-1]] + 1.0
        # 收緊到範圍兩側最近的停頓（往外最多 0.4 秒）
        seg = read(a, b)
        rms = np.sqrt(np.convolve(seg ** 2, np.ones(HOP) / HOP, mode="valid")[::HOP] + 1e-12)
        tt = a + np.arange(len(rms)) * HOP / SR
        sa = low_points(rms, tt, max(a, ra - 0.4), ra + 0.2, 1) or [ra]
        sb = low_points(rms, tt, rb - 0.2, min(b, rb + 0.4), 1) or [rb]
        na, nb = max(a, sa[0]), min(b, sb[0])
        got = decode(na, nb)
        sim = Levenshtein.normalized_similarity(q, kana_of(got))
        name = {"H": "Haruki", "T": "老師"}[who]
        if sim >= float(r["similarity"]) - 0.1:
            w.writerow([r["no"], r["text"], name, L.hms(na), L.hms(nb), f"{nb - na:.1f}", f"{sim:.2f}", got, f"由 {b - a:.1f} 秒收緊"])
        else:
            w.writerow([r["no"], r["text"], r["speaker"], r["start"], r["end"], f"{b - a:.1f}", r["similarity"], r["recognized"],
                        f"收緊後相似度降到 {sim:.2f}（{got}），保留原切法"])


if __name__ == "__main__":
    main(*sys.argv[1:6])
