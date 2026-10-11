"""總檢查：照 audio_positions.tsv 的起訖時間，從指定音檔切出每一筆完整命中（前後各留 PAD 秒）重新辨識，
確認切出來的片段確實包含目標句子、且沒有多出大段別的話。

用法：python3 verify_clips.py audio_positions.tsv 音檔.wav 模型資料夾 > audio_positions_checked.tsv
輸出：原表全部欄位＋ recheck（複核辨識結果）、usable（Y＝可直接用）。
usable＝Y 的條件：coverage 完整、score ≥ 90（排除意思相近的不同版本），且從音檔切「起點前 0.6 秒～終點後 0.6 秒」重新辨識後：
  - 目標的開頭 4 拍出現在結果的前 9 拍內（起點晚超過 1 秒會切掉開頭；早超過 1 秒前面會多出一段話）
  - 目標的結尾 4 拍出現在結果的後 9 拍內（終點同理）
  - 結果包含目標的大部分（partial_ratio ≥ 70；4 拍以下必須逐字包含）
  只看文字、不看時間戳，避開模型「每段第一個字標在片段開頭」的假象。
  靈敏度實測（2026.10.11，80 筆）：正確位置 72 筆通過；故意移動 ±1.2 秒後只有 12～13 筆通過（多為同句在附近重複念）。
"""
import csv
import sys

import pykakasi
import sherpa_onnx
import soundfile as sf
from rapidfuzz import fuzz

SR = 16000
PAD = 0.6
EDGE = 5          # 開頭／結尾在複核結果中最多可以離片段頭尾幾拍（PAD 0.6 秒約 4～5 拍）
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
        k = min(4, len(q))
        # 開頭 k 拍要出現在複核結果的前 EDGE+k 拍內、結尾 k 拍要出現在後 EDGE+k 拍內
        head = fuzz.partial_ratio_alignment(q[:k], got[:EDGE + k])
        tail = fuzz.partial_ratio_alignment(q[-k:], got[-(EDGE + k):])
        need = 100 if len(q) <= 4 else 75
        head_ok = head is not None and head.score >= need
        tail_ok = tail is not None and tail.score >= need
        body_ok = (q in got) if len(q) <= 4 else fuzz.partial_ratio(q, got) >= 70
        ok = head_ok and tail_ok and body_ok and float(r["score"]) >= 90
        w.writerow([r[k] for k in rd.fieldnames] + [s.result.text, "Y" if ok else "N"])


if __name__ == "__main__":
    main(*sys.argv[1:4])
