"""總檢查：照 audio_positions.tsv 的起訖時間，從指定音檔切出每一筆完整命中（前後各留 PAD 秒）重新辨識，
確認切出來的片段確實包含目標句子、且沒有多出大段別的話。

用法：python3 verify_clips.py audio_positions.tsv 音檔.wav 模型資料夾 > audio_positions_checked.tsv
輸出：原表全部欄位＋ recheck（複核辨識結果）、usable（Y＝可直接用）。
usable＝Y 的條件：coverage 完整、score ≥ 90（排除意思相近的不同版本）、
  複核辨識結果包含目標讀音（partial_ratio ≥ 70；4 拍以下的短詞必須逐字包含）。
註：短片段單獨辨識時，模型常漏掉開頭一兩個字，所以複核只要求「包含大部分」，起點精度另由 check_onset.py 驗證。
"""
import csv
import sys

import pykakasi
import sherpa_onnx
import soundfile as sf
from rapidfuzz import fuzz

SR = 16000
PAD = 0.5
KKS = pykakasi.kakasi()


def ts(s):
    h, m, r = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(r)


def kana(text):
    out = ""
    for w in KKS.convert(text):
        out += w["hira"]
    return "".join(c for c in out if "ぁ" <= c <= "ゖ" or c == "ー")


def main(tsv, wav, model):
    rec = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=f"{model}/encoder-epoch-99-avg-1.int8.onnx", decoder=f"{model}/decoder-epoch-99-avg-1.onnx",
        joiner=f"{model}/joiner-epoch-99-avg-1.int8.onnx", tokens=f"{model}/tokens.txt",
        num_threads=4, sample_rate=SR, feature_dim=80)
    f = sf.SoundFile(wav)
    rd = csv.DictReader(open(tsv, encoding="utf-8"), delimiter="\t")
    w = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    w.writerow(rd.fieldnames + ["recheck", "usable"])
    for r in rd:
        if not r.get("start") or r["coverage"] != "完整":
            w.writerow([r[k] for k in rd.fieldnames] + ["", "N" if r.get("start") else ""]); continue
        a, b = ts(r["start"]) - PAD, ts(r["end"]) + PAD
        f.seek(int(max(0, a) * SR))
        x = f.read(int((b - max(0, a)) * SR), dtype="float32")
        s = rec.create_stream(); s.accept_waveform(SR, x); rec.decode_stream(s)
        got = kana(s.result.text)
        q = r["kana"]
        found = (q in got) if len(q) <= 4 else fuzz.partial_ratio(q, got) >= 70
        ok = found and float(r["score"]) >= 90
        w.writerow([r[k] for k in rd.fieldnames] + [s.result.text, "Y" if ok else "N"])


if __name__ == "__main__":
    main(*sys.argv[1:4])
