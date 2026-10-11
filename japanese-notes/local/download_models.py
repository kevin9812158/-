"""下載本地流程需要的模型到 local/models/（已存在就跳過）。

- 日文語音辨識 ReazonSpeech：只抓流程實際用到的 4 個檔案（約 170 MB），
  優先從 HuggingFace 逐檔下載；失敗才退回 GitHub releases 的整包（713 MB，含用不到的完整精度版）。
- 語音偵測 silero_vad.onnx、說話者聲紋 3dspeaker：GitHub releases（小檔）。

速度：每個檔案分成多段、同時開多條連線下載（單一連線常被限速）。
斷線會自動重試，已下載的段落留在 models/*.part*，重新執行本程式會接著下載。
"""
import hashlib
import os
import shutil
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(HERE, "models")
REL = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
ASR_NAME = "sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01"
# 原始來源（sherpa 的整包就是從這裡轉來的）；第二個是鏡像站
ASR_HF = ["https://huggingface.co/reazon-research/reazonspeech-k2-v2/resolve/main",
          "https://hf-mirror.com/reazon-research/reazonspeech-k2-v2/resolve/main"]
ASR_TAR = f"{REL}/asr-models/{ASR_NAME}.tar.bz2"
ASR_FILES = ["encoder-epoch-99-avg-1.int8.onnx", "decoder-epoch-99-avg-1.onnx",
             "joiner-epoch-99-avg-1.int8.onnx", "tokens.txt"]
# 和雲端驗證時用的檔案（GitHub 整包）一致才採用，避免版本不同造成結果不同
ASR_MD5 = {"encoder-epoch-99-avg-1.int8.onnx": "b9e63f6db61d7d47cb0c075a588b9fac",
           "decoder-epoch-99-avg-1.onnx": "017a15baba345c6870da8a3e2226f5ff",
           "joiner-epoch-99-avg-1.int8.onnx": "8c6786c321d9b85f263ddcae6054c5e7",
           "tokens.txt": "14923ff1c613b1389df8c9d6c2e5cb42"}
SINGLE = [
    ("silero_vad.onnx", f"{REL}/asr-models/silero_vad.onnx"),
    ("3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx",
     f"{REL}/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"),
]
CONNS = 8
MIN_SEG = 8 << 20  # 小於 8 MB 的檔案不分段
RETRIES = 8
CHUNK = 1 << 20
SLOW_WINDOW = 15      # 秒
SLOW_BPS = 300_000    # 單一連線低於每秒 300 KB 就換一條
MAX_RECONNECT = 20    # 每段最多換幾次（整條線路都慢時就不再換）
stats = {"reconnect": 0}


class Failed(Exception):
    pass


def head(url):
    """回傳 (檔案大小, 是否支援分段)。用 Range: bytes=0-0 探測，比 HEAD 可靠（會跟著轉址）。"""
    req = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        if r.status == 206:
            return int(r.headers["Content-Range"].rsplit("/", 1)[1]), True
        return int(r.headers["Content-Length"]), False


def fetch_range(url, path, a, b, done, lock):
    """把 [a, b] 下載到 path（可續傳）；done 是共用的已下載位元組計數。"""
    need = b - a + 1
    attempt = swaps = 0
    while attempt < RETRIES:
        attempt += 1
        have = os.path.getsize(path) if os.path.exists(path) else 0
        if have > need:
            os.remove(path); have = 0
        if have == need:
            return
        try:
            req = urllib.request.Request(url, headers={"Range": f"bytes={a + have}-{b}"})
            with urllib.request.urlopen(req, timeout=60) as r, open(path, "ab") as f:
                if r.status != 206:
                    raise Failed("伺服器不支援分段")
                t0, n0, slow = time.time(), 0, False
                while True:
                    buf = r.read(CHUNK)
                    if not buf:
                        break
                    f.write(buf); n0 += len(buf)
                    with lock:
                        done[0] += len(buf)
                    # 同一條連線的速度整段不會變：被分到慢的節點就斷開重連（不算失敗次數）
                    if swaps < MAX_RECONNECT and time.time() - t0 >= SLOW_WINDOW:
                        if n0 / (time.time() - t0) < SLOW_BPS:
                            slow = True; break
                        t0, n0 = time.time(), 0
            if slow:
                with lock:
                    stats["reconnect"] += 1
                swaps += 1; attempt -= 1; continue
            if os.path.getsize(path) == need:
                return
        except Failed:
            raise
        except (urllib.error.URLError, OSError, ValueError):
            if attempt == RETRIES:
                raise
            time.sleep(min(30, 2 ** attempt))


def fetch(url, dst):
    """下載 url 到 dst。分段平行下載，完成且大小正確才改名成 dst。"""
    total, ranged = head(url)
    tmp = dst + ".part"
    if not ranged:  # 少見：伺服器不支援 Range，單線從頭下載
        with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, CHUNK)
        if os.path.getsize(tmp) != total:
            raise Failed("大小不符")
        os.replace(tmp, dst); return
    n = max(1, min(CONNS, total // MIN_SEG))
    step = -(-total // n)
    segs = [(i * step, min(total, (i + 1) * step) - 1, f"{tmp}{i}") for i in range(n)]
    done, lock, errs = [sum(os.path.getsize(p) for _, _, p in segs if os.path.exists(p))], threading.Lock(), []
    start, base = time.time(), done[0]

    def work(a, b, p):
        try:
            fetch_range(url, p, a, b, done, lock)
        except Exception as e:  # noqa: BLE001
            errs.append(e)

    th = [threading.Thread(target=work, args=s, daemon=True) for s in segs]
    for t in th:
        t.start()
    while any(t.is_alive() for t in th):
        time.sleep(0.5)
        sp = (done[0] - base) / max(0.1, time.time() - start) / 1e6
        sys.stdout.write(f"\r  {done[0] * 100 // total:3d}%  {done[0] / 1e6:.0f} / {total / 1e6:.0f} MB  {sp:.1f} MB/s  換線 {stats['reconnect']} 次   ")
        sys.stdout.flush()
    print()
    if errs:
        raise Failed(f"{errs[0]}（已下載的部分保留，重新執行會接著下載）")
    with open(tmp, "wb") as out:
        for _, _, p in segs:
            with open(p, "rb") as f:
                shutil.copyfileobj(f, out, CHUNK)
    if os.path.getsize(tmp) != total:
        raise Failed("合併後大小不符")
    for _, _, p in segs:
        os.remove(p)
    os.replace(tmp, dst)


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for buf in iter(lambda: f.read(CHUNK), b""):
            h.update(buf)
    return h.hexdigest()


def get_asr():
    d = os.path.join(MODELS, ASR_NAME)
    if all(os.path.exists(os.path.join(d, f)) for f in ASR_FILES):
        print(f"已存在，跳過：{ASR_NAME}"); return
    os.makedirs(d, exist_ok=True)
    for base in ASR_HF:
        host = base.split("/")[2]
        try:
            for f in ASR_FILES[::-1]:  # 小檔先下載：版本不同時，在 tokens.txt 就會發現，不必白下載大檔
                p = os.path.join(d, f)
                if os.path.exists(p):
                    continue
                print(f"下載（{host}）：{f}")
                fetch(f"{base}/{f}", p)
                if md5(p) != ASR_MD5[f]:
                    os.remove(p)
                    raise Failed(f"{f} 的內容和驗證過的版本不同")
            return
        except (Failed, urllib.error.URLError, OSError, ValueError) as e:
            print(f"\n  {host} 下載失敗：{e}")
    print("  改用 GitHub 整包（713 MB）")
    tar = os.path.join(MODELS, os.path.basename(ASR_TAR))
    if not os.path.exists(tar):
        print(f"下載（GitHub）：{os.path.basename(ASR_TAR)}")
        fetch(ASR_TAR, tar)
    print("  解壓中…")
    try:
        with tarfile.open(tar, "r:bz2") as t:
            t.extractall(MODELS, members=[m for m in t.getmembers() if os.path.basename(m.name) in ASR_FILES])
    except (tarfile.TarError, EOFError, OSError) as e:
        sys.exit(f"解壓失敗：{e}\n檔案可能損壞，請刪除 {tar} 後重新執行。")
    os.remove(tar)


def main():
    os.makedirs(MODELS, exist_ok=True)
    try:
        get_asr()
        for name, url in SINGLE:
            dst = os.path.join(MODELS, name)
            if os.path.exists(dst):
                print(f"已存在，跳過：{name}"); continue
            print(f"下載：{name}")
            fetch(url, dst)
    except (Failed, urllib.error.URLError, OSError, ValueError) as e:
        sys.exit(f"\n下載失敗：{e}\n網路穩定後重新執行本程式，會從斷點接著下載。")
    # 舊版程式留下的單檔續傳暫存（整包 tar 的 .part），已用不到
    old = os.path.join(MODELS, os.path.basename(ASR_TAR) + ".part")
    if os.path.exists(old):
        os.remove(old); print("已刪除舊的暫存：", os.path.basename(old))
    print("模型準備完成：", MODELS)


if __name__ == "__main__":
    main()
