"""下載本地流程需要的模型到 local/models/（已存在就跳過）。全部來自 k2-fsa/sherpa-onnx 的 GitHub releases。

- 日文語音辨識：sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01（約 700 MB，解壓後約 770 MB）
- 語音偵測：silero_vad.onnx
- 說話者聲紋：3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx

大檔下載中途斷線很常見：未完成的部分留在 models/*.part，會自動續傳（HTTP Range）並重試；
重新執行本程式也會從斷點接著下載。確認大小和伺服器一致後才解壓／改名。
"""
import os
import sys
import tarfile
import time
import urllib.error
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
RETRIES = 8
CHUNK = 1 << 20


def total_size(url):
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=60) as r:
        return int(r.headers["Content-Length"])


def fetch(url, tmp):
    """下載到 tmp，斷線就從已下載的位置續傳；回傳時檔案大小一定等於伺服器上的大小。"""
    total = None
    for attempt in range(1, RETRIES + 1):
        try:
            if total is None:
                total = total_size(url)
            have = os.path.getsize(tmp) if os.path.exists(tmp) else 0
            if have > total:  # 不明來源的殘檔，重新下載
                os.remove(tmp); have = 0
            if have == total:
                return
            if have:
                print(f"  從 {have * 100 // total}% 續傳")
            req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"})
            with urllib.request.urlopen(req, timeout=60) as r:
                if have and r.status != 206:  # 伺服器不支援續傳，只能從頭來
                    have = 0
                with open(tmp, "ab" if have else "wb") as f:
                    while True:
                        buf = r.read(CHUNK)
                        if not buf:
                            break
                        f.write(buf); have += len(buf)
                        sys.stdout.write(f"\r  {have * 100 // total:3d}%  {have / 1e6:.0f} / {total / 1e6:.0f} MB")
                        sys.stdout.flush()
            print()
            if have == total:
                return
            raise IOError(f"只收到 {have} / {total} bytes")
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"\n  連線中斷（第 {attempt} 次）：{e}")
            if attempt == RETRIES:
                sys.exit(f"下載失敗。已下載的部分保留在 {tmp}，網路穩定後重新執行本程式會接著下載。")
            time.sleep(min(60, 2 ** attempt))


def main():
    os.makedirs(MODELS, exist_ok=True)
    for name, url in ITEMS:
        dst = os.path.join(MODELS, name)
        if os.path.exists(dst):
            print(f"已存在，跳過：{name}"); continue
        print(f"下載：{name}")
        tmp = os.path.join(MODELS, os.path.basename(url) + ".part")
        fetch(url, tmp)
        if url.endswith(".tar.bz2"):
            print("  解壓中…")
            try:
                with tarfile.open(tmp, "r:bz2") as t:
                    t.extractall(MODELS)
            except (tarfile.TarError, EOFError, OSError) as e:
                sys.exit(f"解壓失敗：{e}\n檔案可能損壞，請刪除 {tmp} 和 {dst}（若有）後重新執行。")
            os.remove(tmp)
        else:
            os.replace(tmp, dst)
    print("模型準備完成：", MODELS)


if __name__ == "__main__":
    main()
