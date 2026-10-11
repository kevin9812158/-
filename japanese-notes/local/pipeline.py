"""線上課音訊流程（本地版）的總入口。程式本體在 ../online/，這裡只負責路徑和步驟順序。

環境用 uv 管理（本資料夾的 .venv）：先 uv sync，再用 uv run pipeline.py …。

每一課一個資料夾：local/lessons/<課名>/，裡面放課堂音檔（m4a 等）。中間產物也存在同一個資料夾，已存在就跳過。

  uv run pipeline.py check                               檢查環境（套件、ffmpeg、模型）
  uv run pipeline.py prepare  <課資料夾>                  音檔轉成 16 kHz 單聲道 full.wav
  uv run pipeline.py asr      <課資料夾>                  整段日文辨識（帶時間戳）→ asr_full.jsonl（3 小時約 25 分鐘）
  uv run pipeline.py speakers <課資料夾> <Haruki錨點秒數…>  聲紋分群 → spk.npz、centroids.npz
  uv run pipeline.py locate   <課資料夾> <note.json>      粗定位 → audio_positions.tsv
  uv run pipeline.py refine   <課資料夾> <note.json> <搜尋起秒> <搜尋迄秒> <句子編號…>
                                                        實切精修＋依說話者收緊 → cuts.tsv（給切割工具用）
  uv run pipeline.py tool     <課資料夾>                  開啟切割工具網頁（試聽、微調、匯出）

錨點：確定是 Haruki 在念的時間點（逐字稿中老師說「Haruki，請念」之後那句），3～6 個。
句子編號：audio_positions.tsv 的 no 欄。
"""
import glob
import importlib
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ONLINE = os.path.normpath(os.path.join(HERE, "..", "online"))
TOOL = os.path.normpath(os.path.join(HERE, "..", "tools", "clip_tool", "clip_tool.py"))
MODELS = os.path.join(HERE, "models")
ASR_MODEL = os.path.join(MODELS, "sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01")
ASR_ENC = os.path.join(ASR_MODEL, "encoder-epoch-99-avg-1.int8.onnx")
VAD = os.path.join(MODELS, "silero_vad.onnx")
SPK = os.path.join(MODELS, "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx")
AUDIO_EXT = (".m4a", ".mp3", ".wav", ".aac", ".flac", ".mp4")
PY = sys.executable


ENV = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")  # Windows 預設 cp950，日文會出錯


def run(args, out=None):
    print("→", " ".join(os.path.basename(a) if os.path.isabs(a) else a for a in args), flush=True)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            subprocess.run(args, check=True, stdout=f, env=ENV)
    else:
        subprocess.run(args, check=True, env=ENV)


def script(name):
    return os.path.join(ONLINE, name)


def source_audio(lesson):
    cands = [f for f in glob.glob(os.path.join(lesson, "*")) if f.lower().endswith(AUDIO_EXT)
             and os.path.basename(f) != "full.wav"]
    if not cands:
        sys.exit(f"{lesson} 裡找不到課堂音檔（m4a／mp3／wav…）")
    if len(cands) > 1:
        sys.exit(f"{lesson} 裡有多個音檔，請只留一個：{[os.path.basename(c) for c in cands]}")
    return cands[0]


def check():
    ok = True
    for m in ("sherpa_onnx", "soundfile", "numpy", "scipy", "rapidfuzz", "pykakasi", "docx"):
        try:
            importlib.import_module(m)
        except ImportError:
            print(f"✗ 缺少套件 {m}（在本資料夾執行 uv sync）"); ok = False
    if shutil.which("ffmpeg") is None:
        print("✗ 找不到 ffmpeg（請自行安裝 ffmpeg 並加入 PATH）"); ok = False
    for p in (ASR_ENC, VAD, SPK):
        if not os.path.exists(p):
            print(f"✗ 缺少模型 {os.path.basename(p)}（執行 uv run download_models.py）"); ok = False
    print("✓ 環境就緒" if ok else "環境未完成，請照上面的提示處理")
    return ok


def prepare(lesson):
    wav = os.path.join(lesson, "full.wav")
    if os.path.exists(wav):
        print("已有 full.wav，跳過"); return wav
    run(["ffmpeg", "-v", "error", "-y", "-i", source_audio(lesson), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav])
    return wav


def duration(wav):
    import soundfile as sf
    return sf.info(wav).duration


def asr(lesson):
    wav = prepare(lesson)
    out = os.path.join(lesson, "asr_full.jsonl")
    if os.path.exists(out):
        print("已有 asr_full.jsonl，跳過"); return out
    run([PY, script("asr_timestamps.py"), ASR_MODEL, VAD, wav, "0", f"{duration(wav):.2f}", out])
    return out


def speakers(lesson, *anchors):
    wav, a = prepare(lesson), asr(lesson)
    spk, cen = os.path.join(lesson, "spk.npz"), os.path.join(lesson, "centroids.npz")
    if not os.path.exists(spk):
        run([PY, script("speaker_embed.py"), SPK, wav, a, spk])
    if not anchors:
        sys.exit("請給 Haruki 的錨點秒數（3～6 個）")
    run([PY, script("speaker_centroids.py"), spk, cen, *anchors])


def locate(lesson, note):
    wav, a = prepare(lesson), asr(lesson)
    rec = os.path.splitext(os.path.basename(source_audio(lesson)))[0]
    run([PY, script("locate_audio.py"), os.path.abspath(note), a, rec, wav], os.path.join(lesson, "audio_positions.tsv"))


def refine(lesson, note, w0, w1, *nos):
    wav, a = prepare(lesson), asr(lesson)
    cen = os.path.join(lesson, "centroids.npz")
    if not os.path.exists(cen):
        sys.exit("先執行 speakers 步驟（需要 Haruki 錨點）")
    cand = os.path.join(lesson, "candidates.tsv")
    run([PY, script("refine_cuts.py"), os.path.abspath(note), a, wav, ASR_MODEL, SPK, cen, w0, w1, *nos], cand)
    run([PY, script("trim_by_speaker.py"), cand, wav, ASR_MODEL, SPK, cen], os.path.join(lesson, "cuts.tsv"))
    print("完成：cuts.tsv（用 uv run pipeline.py tool <課資料夾> 試聽、微調、匯出）")


def tool(lesson):
    run([PY, TOOL, os.path.abspath(lesson)])


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("check", "prepare", "asr", "speakers", "locate", "refine", "tool"):
        print(__doc__); return
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "check":
        sys.exit(0 if check() else 1)
    lesson = os.path.abspath(args[0])
    {"prepare": prepare, "asr": asr, "speakers": speakers, "locate": locate, "refine": refine, "tool": tool}[cmd](lesson, *args[1:])


if __name__ == "__main__":
    main()
