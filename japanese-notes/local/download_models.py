"""下載本地流程需要的模型到 local/models/（已存在就跳過）。全部來自 k2-fsa/sherpa-onnx 的 GitHub releases。

- 日文語音辨識：sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01（約 700 MB，解壓後約 770 MB）
- 語音偵測：silero_vad.onnx
- 說話者聲紋：3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx
"""
import os
import sys
import tarfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(HERE, "models")
REL = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
ITEMS = [
    ("sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01", f"{REL}/asr-models/sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01.tar.bz2"),
    ("silero_vad.onnx", f"{REL}/asr-models/silero_vad.onnx"),
    ("3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx",
     f"{REL}/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"),
]


def progress(n, bs, total):
    if total > 0:
        pct = min(100, n * bs * 100 // total)
        sys.stdout.write(f"\r  {pct:3d}%"); sys.stdout.flush()


def main():
    os.makedirs(MODELS, exist_ok=True)
    for name, url in ITEMS:
        dst = os.path.join(MODELS, name)
        if os.path.exists(dst):
            print(f"已存在，跳過：{name}"); continue
        print(f"下載：{name}")
        tmp = os.path.join(MODELS, os.path.basename(url) + ".part")
        urllib.request.urlretrieve(url, tmp, progress); print()
        if url.endswith(".tar.bz2"):
            print("  解壓中…")
            with tarfile.open(tmp, "r:bz2") as t:
                t.extractall(MODELS)
            os.remove(tmp)
        else:
            os.replace(tmp, dst)
    print("模型準備完成：", MODELS)


if __name__ == "__main__":
    main()
