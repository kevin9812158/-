"""本地音檔切割工具（網頁介面）。

用法：把音檔（m4a／mp3／wav）和切點表（.tsv）放在同一個資料夾，在該資料夾執行
    python clip_tool.py            （或雙擊 開啟切割工具.bat）
瀏覽器會自動打開 http://127.0.0.1:8765 。只在本機運作，檔案不會上傳到任何地方。

需要：Python 3.8 以上、ffmpeg（指令列可以執行 ffmpeg）。不需要其他套件。

切點表（tab 分隔、第一列是欄名）至少要有 start、end 兩欄，時間格式 時:分:秒.毫秒（例 0:17:51.910）。
其他欄位會自動帶入：no（編號）、text（句子）、speaker（說話者）、usable（Y／N，有這欄時預設只勾 Y）。

匯出：切到資料夾裡的 exports/<切點表名稱>/，檔名「編號_說話者_句子.副檔名」，另附 清單.csv，也可以下載 zip。
切割一律重新編碼（不是只複製封包），起訖精確到毫秒。
"""
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8765
BASE = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.getcwd())
AUDIO_EXT = (".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg", ".mp4")
FMT = {"m4a": ["-c:a", "aac", "-b:a", "128k"], "mp3": ["-c:a", "libmp3lame", "-b:a", "128k"], "wav": ["-c:a", "pcm_s16le"]}


def safe_path(rel):
    """只允許工具資料夾底下的檔案。"""
    p = os.path.abspath(os.path.join(BASE, rel))
    if not (p == BASE or p.startswith(BASE + os.sep)):
        raise ValueError("路徑不在工具資料夾內")
    return p


def secs(t):
    t = str(t).strip()
    if not t:
        raise ValueError("時間是空的")
    parts = t.split(":")
    v = 0.0
    for x in parts:
        v = v * 60 + float(x)
    return v


def hms(v):
    ms = int(round(max(0.0, v) * 1000))
    return f"{ms // 3600000}:{ms % 3600000 // 60000:02}:{ms % 60000 // 1000:02}.{ms % 1000:03}"


def safe_name(s, n=30):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', "", s).strip()
    return s[:n] or "clip"


def list_files():
    audio, tables = [], []
    for root, dirs, files in os.walk(BASE):
        dirs[:] = [d for d in dirs if d != "exports" and not d.startswith(".")]
        if root.count(os.sep) - BASE.count(os.sep) > 2:
            continue
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), BASE)
            if f.lower().endswith(AUDIO_EXT):
                audio.append(rel)
            elif f.lower().endswith(".tsv"):
                tables.append(rel)
    return {"base": BASE, "audio": sorted(audio), "tables": sorted(tables)}


def read_table(rel):
    with open(safe_path(rel), encoding="utf-8-sig") as f:
        rd = csv.DictReader(f, delimiter="\t")
        rows = []
        for i, r in enumerate(rd, 1):
            if not (r.get("start") or "").strip() or not (r.get("end") or "").strip():
                continue
            rows.append({
                "no": (r.get("no") or str(i)).strip(),
                "text": (r.get("text") or "").strip(),
                "speaker": (r.get("speaker") or "").strip(),
                "start": r["start"].strip(),
                "end": r["end"].strip(),
                "checked": (r.get("usable", "Y") or "Y").strip().upper() != "N",
                "note": (r.get("note") or r.get("recognized") or "").strip(),
            })
    return rows


def ffmpeg_cut(audio, a, b, fmt, out):
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", audio, "-vn", "-ac", "1"]
    cmd += FMT[fmt] + ([out] if out != "pipe:1" else ["-f", {"m4a": "adts", "mp3": "mp3", "wav": "wav"}[fmt], "pipe:1"])
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace")[-500:])
    return r.stdout


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            if u.path == "/":
                return self.send(200, PAGE, "text/html; charset=utf-8")
            if u.path == "/api/files":
                return self.send(200, list_files())
            if u.path == "/api/table":
                return self.send(200, read_table(q["path"]))
            if u.path == "/api/clip":
                a, b = secs(q["start"]), secs(q["end"])
                pad = float(q.get("pad", 0) or 0)
                data = ffmpeg_cut(safe_path(q["audio"]), max(0, a - pad), b + pad, "mp3", "pipe:1")
                return self.send(200, data, "audio/mpeg")
            if u.path == "/api/zip":
                d = safe_path(q["dir"])
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                    for f in sorted(os.listdir(d)):
                        z.write(os.path.join(d, f), f)
                name = urllib.parse.quote(os.path.basename(d) + ".zip")
                return self.send(200, buf.getvalue(), "application/zip",
                                 {"Content-Disposition": f"attachment; filename*=UTF-8''{name}"})
            self.send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            self.send(400, {"error": str(e)})

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8"))
            if self.path == "/api/export":
                audio = safe_path(body["audio"])
                fmt = body.get("format", "m4a")
                pad = float(body.get("pad", 0) or 0)
                name = safe_name(os.path.splitext(os.path.basename(body.get("table", "clips")))[0], 60)
                out_dir = os.path.join(BASE, "exports", name)
                if os.path.isdir(out_dir):
                    shutil.rmtree(out_dir)
                os.makedirs(out_dir)
                manifest = []
                for r in body["rows"]:
                    a, b = max(0, secs(r["start"]) - pad), secs(r["end"]) + pad
                    if b <= a:
                        raise ValueError(f"第 {r['no']} 筆：終點不在起點之後")
                    no = r["no"].zfill(3) if r["no"].isdigit() else r["no"]
                    fn = f"{no}_{safe_name(r.get('speaker') or '未標')}_{safe_name(r.get('text') or '')}.{fmt}"
                    ffmpeg_cut(audio, a, b, fmt, os.path.join(out_dir, fn))
                    manifest.append([fn, r["no"], r.get("speaker", ""), r.get("text", ""), hms(a), hms(b), f"{b - a:.3f}"])
                with open(os.path.join(out_dir, "清單.csv"), "w", encoding="utf-8-sig", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["file", "no", "speaker", "text", "start", "end", "seconds"])
                    w.writerows(manifest)
                return self.send(200, {"dir": os.path.relpath(out_dir, BASE), "count": len(manifest)})
            if self.path == "/api/save":
                src = safe_path(body["table"])
                dst = os.path.splitext(src)[0] + "_edited.tsv"
                with open(dst, "w", encoding="utf-8", newline="") as f:
                    w = csv.writer(f, delimiter="\t", lineterminator="\n")
                    w.writerow(["no", "text", "speaker", "start", "end", "usable", "note"])
                    for r in body["rows"]:
                        w.writerow([r["no"], r["text"], r["speaker"], r["start"], r["end"], "Y" if r["checked"] else "N", r.get("note", "")])
                return self.send(200, {"saved": os.path.relpath(dst, BASE)})
            self.send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            self.send(400, {"error": str(e)})


PAGE = r"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>音檔切割工具</title>
<style>
:root{--bg:#fafaf8;--fg:#222;--muted:#666;--line:#ddd;--accent:#2b6cb0;--ok:#2f855a;--warn:#c05621;--card:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#1b1b1d;--fg:#eee;--muted:#aaa;--line:#3a3a3d;--accent:#63b3ed;--ok:#68d391;--warn:#f6ad55;--card:#242427}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,"Microsoft JhengHei","PingFang TC",sans-serif}
header{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;gap:16px;flex-wrap:wrap;align-items:end}
h1{font-size:18px;margin:0 16px 0 0}label{font-size:12px;color:var(--muted);display:block}
select,input{font:inherit;padding:4px 6px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg)}
button{font:inherit;padding:5px 12px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg);cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}button:disabled{opacity:.5;cursor:default}
main{padding:12px 20px 80px}table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid var(--line);padding:6px 6px;vertical-align:middle;text-align:left}
th{font-size:12px;color:var(--muted);font-weight:600}td.t{min-width:260px}td.tm input{width:118px;font-family:ui-monospace,Consolas,monospace}
.nudge button{padding:1px 6px;font-size:12px}.dur{font-family:ui-monospace,Consolas,monospace;color:var(--muted)}
.note{font-size:12px;color:var(--muted)}.sp{font-size:12px;padding:1px 6px;border-radius:10px;border:1px solid var(--line);white-space:nowrap}
#status{position:fixed;bottom:0;left:0;right:0;padding:10px 20px;background:var(--card);border-top:1px solid var(--line);font-size:14px}
.err{color:var(--warn)}.ok{color:var(--ok)}
</style></head><body>
<header>
 <h1>音檔切割工具</h1>
 <div><label>音檔</label><select id="audio"></select></div>
 <div><label>切點表</label><select id="table"></select></div>
 <div><label>試聽前後多留（秒）</label><input id="ppad" type="number" step="0.1" value="0" style="width:70px"></div>
 <div><label>匯出前後多留（秒）</label><input id="epad" type="number" step="0.1" value="0" style="width:70px"></div>
 <div><label>格式</label><select id="fmt"><option>m4a</option><option>mp3</option><option>wav</option></select></div>
 <button id="save">儲存修改的切點表</button>
 <button id="export" class="primary">切割並下載 zip</button>
</header>
<main><table><thead><tr><th><input type="checkbox" id="all"></th><th>#</th><th>說話者</th><th>句子</th><th>起點</th><th>終點</th><th>長度</th><th>試聽</th></tr></thead><tbody id="rows"></tbody></table></main>
<div id="status">工具資料夾：<span id="base"></span></div>
<audio id="player"></audio>
<script>
const $=s=>document.querySelector(s);let rows=[];
const secs=t=>String(t).trim().split(':').reduce((v,x)=>v*60+parseFloat(x),0);
const hms=v=>{let ms=Math.round(Math.max(0,v)*1000);const h=Math.floor(ms/3600000),m=Math.floor(ms%3600000/60000),s=Math.floor(ms%60000/1000);ms%=1000;return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}.${String(ms).padStart(3,'0')}`};
const status=(m,c='')=>{$('#status').innerHTML=`<span class="${c}">${m}</span>`};
async function api(u,opt){const r=await fetch(u,opt);const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);return j}
async function init(){const f=await api('/api/files');$('#base').textContent=f.base;
 $('#audio').innerHTML=f.audio.map(a=>`<option>${a}</option>`).join('')||'<option value="">（資料夾裡沒有音檔）</option>';
 $('#table').innerHTML=f.tables.map(a=>`<option>${a}</option>`).join('')||'<option value="">（資料夾裡沒有 .tsv）</option>';
 status(`工具資料夾：${f.base}`);if(f.tables.length)load();}
async function load(){try{rows=await api('/api/table?path='+encodeURIComponent($('#table').value));render();status(`載入 ${rows.length} 筆`,'ok')}catch(e){status(e.message,'err')}}
function render(){$('#rows').innerHTML=rows.map((r,i)=>`<tr>
 <td><input type="checkbox" data-i="${i}" class="ck" ${r.checked?'checked':''}></td><td>${r.no}</td>
 <td>${r.speaker?`<span class="sp">${r.speaker}</span>`:''}</td>
 <td class="t">${r.text}${r.note?`<div class="note">${r.note}</div>`:''}</td>
 <td class="tm"><input data-i="${i}" data-k="start" value="${r.start}"><div class="nudge"><button data-i="${i}" data-k="start" data-d="-0.1">−0.1</button><button data-i="${i}" data-k="start" data-d="0.1">+0.1</button></div></td>
 <td class="tm"><input data-i="${i}" data-k="end" value="${r.end}"><div class="nudge"><button data-i="${i}" data-k="end" data-d="-0.1">−0.1</button><button data-i="${i}" data-k="end" data-d="0.1">+0.1</button></div></td>
 <td class="dur">${(secs(r.end)-secs(r.start)).toFixed(2)}s</td>
 <td><button data-play="${i}">▶ 試聽</button></td></tr>`).join('')}
$('#rows').addEventListener('click',e=>{const b=e.target;
 if(b.dataset.play!==undefined){const r=rows[b.dataset.play];const p=$('#player');
  p.src=`/api/clip?audio=${encodeURIComponent($('#audio').value)}&start=${r.start}&end=${r.end}&pad=${$('#ppad').value||0}`;p.play();status(`試聽 #${r.no}　${r.start} – ${r.end}`);return}
 if(b.dataset.d){const r=rows[b.dataset.i];r[b.dataset.k]=hms(secs(r[b.dataset.k])+parseFloat(b.dataset.d));render()}
 if(b.classList.contains('ck'))rows[b.dataset.i].checked=b.checked});
$('#rows').addEventListener('change',e=>{const t=e.target;if(t.dataset.k){try{secs(t.value);rows[t.dataset.i][t.dataset.k]=t.value.trim();render()}catch{status('時間格式要像 0:17:51.910','err')}}});
$('#all').addEventListener('change',e=>{rows.forEach(r=>r.checked=e.target.checked);render()});
$('#table').addEventListener('change',load);
$('#save').onclick=async()=>{try{const j=await api('/api/save',{method:'POST',body:JSON.stringify({table:$('#table').value,rows})});status(`已儲存：${j.saved}`,'ok')}catch(e){status(e.message,'err')}};
$('#export').onclick=async()=>{const sel=rows.filter(r=>r.checked);if(!sel.length)return status('沒有勾選任何一筆','err');
 $('#export').disabled=true;status(`切割中…（${sel.length} 筆）`);
 try{const j=await api('/api/export',{method:'POST',body:JSON.stringify({audio:$('#audio').value,table:$('#table').value,rows:sel,format:$('#fmt').value,pad:$('#epad').value})});
  status(`完成 ${j.count} 筆，存在 ${j.dir}，開始下載 zip`,'ok');location.href='/api/zip?dir='+encodeURIComponent(j.dir)}
 catch(e){status(e.message,'err')}finally{$('#export').disabled=false}};
init().catch(e=>status(e.message,'err'));
</script></body></html>"""


def main():
    if shutil.which("ffmpeg") is None:
        print("找不到 ffmpeg。Windows 請先執行：winget install Gyan.FFmpeg，裝完重新開一個視窗再試。")
        input("按 Enter 結束")
        return
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    url = f"http://127.0.0.1:{PORT}"
    print(f"工具資料夾：{BASE}\n已開啟：{url}\n關閉這個視窗就會結束工具。")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
