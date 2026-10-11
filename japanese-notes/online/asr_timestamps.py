"""用 sherpa-onnx（ReazonSpeech zipformer，日文）對音軌做帶 token 時間戳的語音辨識。

用法：python3 asr_timestamps.py 模型資料夾 silero_vad.onnx full.wav 起秒 迄秒 輸出.jsonl
- 先用 silero VAD 切出說話片段（最長 15 秒），每段辨識後把 token 時間戳加上片段起點，換成音軌絕對時間。
- 每行輸出一段：{"start", "end", "text", "tokens": [...], "ts": [...]}（ts 是每個 token 的起點秒數）。
- 只處理 起秒～迄秒；音軌 0 秒＝側錄檔名時間。
"""
import json
import sys
import time

import numpy as np
import sherpa_onnx
import soundfile as sf

SR = 16000


def main(model_dir, vad_path, wav, t_from, t_to, out_path):
    t_from, t_to = float(t_from), float(t_to)
    rec = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=f"{model_dir}/encoder-epoch-99-avg-1.int8.onnx",
        decoder=f"{model_dir}/decoder-epoch-99-avg-1.onnx",
        joiner=f"{model_dir}/joiner-epoch-99-avg-1.int8.onnx",
        tokens=f"{model_dir}/tokens.txt",
        num_threads=4, sample_rate=SR, feature_dim=80, decoding_method="greedy_search")

    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = vad_path
    cfg.silero_vad.min_silence_duration = 0.25
    cfg.silero_vad.min_speech_duration = 0.2
    cfg.silero_vad.max_speech_duration = 15
    cfg.silero_vad.threshold = 0.4
    cfg.sample_rate = SR
    vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=60)

    audio, sr = sf.read(wav, dtype="float32", start=int(t_from * SR), stop=int(t_to * SR))
    assert sr == SR
    win = cfg.silero_vad.window_size
    out = open(out_path, "w", encoding="utf-8")
    t0, n = time.time(), 0

    def drain():
        nonlocal n
        while not vad.empty():
            seg = vad.front
            st = t_from + seg.start / SR
            s = rec.create_stream()
            s.accept_waveform(SR, np.asarray(seg.samples, dtype=np.float32))
            rec.decode_stream(s)
            r = s.result
            out.write(json.dumps({"start": round(st, 3), "end": round(st + len(seg.samples) / SR, 3),
                                  "text": r.text, "tokens": list(r.tokens),
                                  "ts": [round(st + x, 3) for x in r.timestamps]}, ensure_ascii=False) + "\n")
            n += 1
            vad.pop()

    for i in range(0, len(audio), win):
        vad.accept_waveform(audio[i:i + win])
        drain()
    vad.flush(); drain()
    out.close()
    dur = t_to - t_from
    print(f"{n} segments, {dur:.0f}s audio in {time.time() - t0:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main(*sys.argv[1:7])
