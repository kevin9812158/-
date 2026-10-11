"""從聲紋分群找出 Haruki 和老師的平均聲紋。

用法：python3 speaker_centroids.py spk.npz 輸出.npz 錨點秒數…
- 錨點：確定是 Haruki 在念的片段起點（逐字稿中老師說「Haruki，請念」之後的那句）。
- 以 cosine 距離 0.6 做階層分群：含錨點的那群＝Haruki；總時長最長、且不含錨點的那群＝老師。
"""
import sys
from collections import Counter

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage


def main(spk, out, *anchors):
    d = np.load(spk); st, en, E = d["starts"], d["ends"], d["emb"]
    H = [int(np.argmin(abs(st - float(t)))) for t in anchors]
    lab = fcluster(linkage(E, "average", metric="cosine"), 0.6, "distance")
    hk = Counter(lab[i] for i in H).most_common(1)[0][0]
    dur = Counter()
    for i, k in enumerate(lab):
        dur[k] += en[i] - st[i]
    teacher = next(k for k, _ in dur.most_common() if k != hk)
    c = {}
    for name, k in (("haruki", hk), ("teacher", teacher)):
        v = E[lab == k].mean(0); c[name] = v / np.linalg.norm(v)
        print(name, "segments", int((lab == k).sum()), "seconds", int(dur[k]), file=sys.stderr)
    np.savez(out, **c)


if __name__ == "__main__":
    main(*sys.argv[1:])
