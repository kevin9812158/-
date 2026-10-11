"""為每個 VAD 說話片段算聲紋（sherpa-onnx 3D-Speaker ERes2Net），供挑選 Haruki／老師的朗讀。

用法：python3 speaker_embed.py 聲紋模型.onnx full.wav asr_full.jsonl 輸出.npz
- 只算長度 ≥ 0.8 秒的片段；輸出 starts、ends、emb（已正規化）。
"""
import json
import sys

import numpy as np
import sherpa_onnx
import soundfile as sf

SR = 16000


def main(model, wav_p, asr_p, out):
    cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=model, num_threads=4)
    ext = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
    wav = sf.SoundFile(wav_p)
    st, en, em = [], [], []
    for line in open(asr_p, encoding="utf-8"):
        g = json.loads(line)
        if g["end"] - g["start"] < 0.8:
            continue
        wav.seek(int(g["start"] * SR)); x = wav.read(int((g["end"] - g["start"]) * SR), dtype="float32")
        s = ext.create_stream(); s.accept_waveform(SR, x); s.input_finished()
        v = np.array(ext.compute(s)); v /= np.linalg.norm(v) + 1e-9
        st.append(g["start"]); en.append(g["end"]); em.append(v)
    np.savez(out, starts=np.array(st), ends=np.array(en), emb=np.array(em))
    print(len(st), "segments", file=sys.stderr)


if __name__ == "__main__":
    main(*sys.argv[1:5])
