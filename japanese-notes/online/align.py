"""線上課：截圖（電腦時鐘）對應逐字稿與摘要段落。

用法：python3 align.py <截圖資料夾> <tr_main.json> <summary_aligned.json> <側錄檔名> > shots_map.tsv
- 側錄檔名例：PassFab20261006_183938033_1，檔名時間＝錄影開始＝逐字稿 0 秒。
- tr_main.json：Plaud 原始轉錄（transaction）陣列。
- summary_aligned.json：摘要段落依內容對到原始轉錄後的結果（含 utt 索引）。
"""
import json, os, re, sys, datetime

shots_dir, tr_path, sum_path, rec_name = sys.argv[1:5]
m = re.search(r'(\d{8})_(\d{6})(\d{3})', rec_name)
t0 = datetime.datetime.strptime(m[1] + m[2], '%Y%m%d%H%M%S') + datetime.timedelta(milliseconds=int(m[3]))

tr = json.load(open(tr_path))
segs = json.load(open(sum_path))['map']
end_audio = tr[-1]['end_time'] / 1000

shots = []
for f in sorted(os.listdir(shots_dir)):
    mm = re.match(r'(\d{8})_(\d{6})_(\d{6})_', f)
    if not mm:
        continue
    t = datetime.datetime.strptime(mm[1] + mm[2], '%Y%m%d%H%M%S') + datetime.timedelta(microseconds=int(mm[3]))
    shots.append((f, (t - t0).total_seconds()))

seg_start = [tr[s['utt']]['start_time'] / 1000 for s in segs]

def hms(sec):
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02}:{sec % 60:02}"

print('no\tclock\taudio_from\taudio_to\tsegments\tfile')
for i, (f, a) in enumerate(shots):
    b = shots[i + 1][1] if i + 1 < len(shots) else end_audio
    # 和這張截圖停留期間重疊的摘要段落（段落範圍＝本段起點到下一段起點）
    hit = []
    for k, s in enumerate(segs):
        s0 = seg_start[k]
        s1 = seg_start[k + 1] if k + 1 < len(segs) else end_audio
        if s0 < b and s1 > a:
            hit.append(str(s['i']))
    clock = (t0 + datetime.timedelta(seconds=a)).strftime('%H:%M:%S')
    print(f"{i + 1}\t{clock}\t{hms(a)}\t{hms(b)}\t{','.join(hit)}\t{f}")
