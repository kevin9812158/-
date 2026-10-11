"""精修切點（PoC）：為指定句子找出「切下來辨識剛好是這一句」的起訖時間。

用法：python3 refine_cuts.py note.json asr_full.jsonl full.wav 模型資料夾 聲紋模型.onnx centroids.npz 搜尋起秒 搜尋迄秒 編號… > refined.tsv
（編號＝audio_positions 表的 no；只處理這些句子）

步驟：
1. 找候選：在搜尋時段內，把筆記讀音和整段辨識結果做寬鬆比對（partial_ratio ≥ 60），每個命中都當候選。
2. 精修：每個候選前後各 2 秒內，取聲音最小的點（停頓、字與字之間）當候選切點，
   起點、終點各取最多 12 個，實際切下來辨識，算辨識讀音和目標讀音的相似度（整句 Levenshtein，不是部分比對）。
3. 每個候選取相似度最高的切法；相似度差 0.03 以內的切法挑最短的（避免多切進老師的中文解說，日文模型對中文不出字）。
4. 判斷說話者：切出片段的聲紋和 Haruki、老師的平均聲紋比 cosine，較高者且 ≥ 0.45 才標該人，否則標「其他」。
5. 每句在相似度 ≥ 0.85 的候選中，依 Haruki ＞ 老師 ＞ 其他、再依相似度挑一個（selected＝Y）；所有候選都列出。
只看「切下來辨識的文字」，不用模型的時間戳，避開時間戳不準的問題。
"""
import csv
import itertools
import json
import os
import sys

import numpy as np
import sherpa_onnx
import soundfile as sf
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import locate_audio as L  # noqa: E402

SR = 16000
HOP = 160
CAND_CUTOFF = 60
ACCEPT = 0.85
N_CUTS = 12


def kana_of(text):
    out = ""
    for w in L.KKS.convert(text):
        rd = L.OVERRIDE.get(w["orig"]) or "".join(L.LETTERS.get(c.upper(), c) for c in w["hira"])
        out += rd
    return "".join(c for c in L.hira(out) if L.KEEP.match(c))


def low_points(rms, t, lo, hi, n):
    """[lo, hi] 內音量的局部最低點（前後 50 ms 內最小），取最安靜的 n 個，彼此至少隔 80 ms。"""
    idx = [i for i in range(5, len(rms) - 5) if lo <= t[i] <= hi and rms[i] == rms[i - 5:i + 6].min()]
    idx.sort(key=lambda i: rms[i])
    out = []
    for i in idx:
        if all(abs(t[i] - t[j]) >= 0.08 for j in out):
            out.append(i)
        if len(out) >= n:
            break
    return [float(t[i]) for i in out]


def main(note_p, asr_p, wav_p, model, spk_model, cent_p, w0, w1, *nos):
    w0, w1 = float(w0), float(w1)
    ext = sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=spk_model, num_threads=4))
    cent = np.load(cent_p)
    rec = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=f"{model}/encoder-epoch-99-avg-1.int8.onnx", decoder=f"{model}/decoder-epoch-99-avg-1.onnx",
        joiner=f"{model}/joiner-epoch-99-avg-1.int8.onnx", tokens=f"{model}/tokens.txt",
        num_threads=4, sample_rate=SR, feature_dim=80)
    wav = sf.SoundFile(wav_p)

    def read(a, b):
        wav.seek(int(a * SR)); return wav.read(int((b - a) * SR), dtype="float32")

    def decode(a, b):
        s = rec.create_stream(); s.accept_waveform(SR, read(a, b)); rec.decode_stream(s)
        return s.result.text

    stream, times, _ = L.asr_stream(asr_p, wav_p)
    i0 = next(i for i, t in enumerate(times) if t[0] >= w0)
    i1 = next((i for i, t in enumerate(times) if t[0] > w1), len(times))
    hay0 = stream[i0:i1]

    lines = {str(no): (sec, text, q) for no, (sec, text, q) in enumerate(L.note_lines(json.load(open(note_p, encoding="utf-8"))), 1)}
    def speaker(a, b):
        s = ext.create_stream(); s.accept_waveform(SR, read(a, b)); s.input_finished()
        v = np.array(ext.compute(s)); v /= np.linalg.norm(v) + 1e-9
        sims = {k: float(v @ cent[k]) for k in ("haruki", "teacher")}
        k = max(sims, key=sims.get)
        return ({"haruki": "Haruki", "teacher": "老師"}[k] if sims[k] >= 0.45 else "其他"), sims

    RANK = {"Haruki": 0, "老師": 1, "其他": 2}
    print("no\ttext\tselected\tspeaker\tstart\tend\tsimilarity\tharuki_sim\tteacher_sim\trecognized")
    for k_no, no in enumerate(nos, 1):
        sec, text, q = lines[no]
        print(f"  [{k_no}/{len(nos)}] 第 {no} 句：{text}", file=sys.stderr, flush=True)
        # 1. 候選
        cands, masked = [], hay0
        while True:
            al = fuzz.partial_ratio_alignment(q, masked, score_cutoff=CAND_CUTOFF)
            if al is None or al.dest_end - al.dest_start < 0.5 * len(q):
                break
            a_i, b_i = i0 + al.dest_start, i0 + al.dest_end - 1
            cands.append((times[a_i][0], times[b_i][1]))
            masked = masked[:al.dest_start] + "＿" * (al.dest_end - al.dest_start) + masked[al.dest_end:]
        # 2. 精修：每個候選各自找最好的切法
        results = []
        for ca, cb in cands:
            ra, rb = max(0, ca - 2.0), cb + 2.0
            x = read(ra, rb)
            rms = np.sqrt(np.convolve(x ** 2, np.ones(HOP) / HOP, mode="valid")[::HOP] + 1e-12)
            t = ra + np.arange(len(rms)) * HOP / SR
            starts = low_points(rms, t, ca - 2.0, ca + 1.0, N_CUTS)
            ends = low_points(rms, t, cb - 1.0, cb + 2.0, N_CUTS)
            tried = []
            for a, b in itertools.product(starts, ends):
                if b - a < 0.3:
                    continue
                got = decode(a, b)
                tried.append((Levenshtein.normalized_similarity(q, kana_of(got)), a, b, got))
            if not tried:
                continue
            top = max(x[0] for x in tried)
            sim, a, b, got = min((x for x in tried if x[0] >= top - 0.03), key=lambda x: x[2] - x[1])
            spk, sims = speaker(a, b)
            results.append((sim, a, b, got, spk, sims))
        # 3. 去掉重疊的候選（同一次朗讀被找到兩次），留相似度高的
        results.sort(key=lambda r: -r[0])
        kept = []
        for r in results:
            if all(r[2] <= k[1] or r[1] >= k[2] for k in kept):
                kept.append(r)
        ok = [r for r in kept if r[0] >= ACCEPT]
        sel = min(ok, key=lambda r: (RANK[r[4]], -r[0])) if ok else None
        if not kept:
            print(f"{no}\t{text}\t\t\t\t\t0.00\t\t\t（沒有候選）")
        for r in sorted(kept, key=lambda r: r[1]):
            sim, a, b, got, spk, sims = r
            mark = "Y" if r is sel else ("" if sim >= ACCEPT else "相似度不足")
            print(f"{no}\t{text}\t{mark}\t{spk}\t{L.hms(a)}\t{L.hms(b)}\t{sim:.2f}\t{sims['haruki']:.2f}\t{sims['teacher']:.2f}\t{got}")
        sys.stdout.flush()


if __name__ == "__main__":
    main(*sys.argv[1:])
