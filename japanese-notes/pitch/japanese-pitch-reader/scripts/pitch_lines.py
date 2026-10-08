#!/usr/bin/env python3
"""pitch_lines.py - 日文講義紅線聲調擷取，PDF（向量線條）與圖片（像素偵測）都能用。

用法：
  python3 pitch_lines.py extract FILE [--page N] [--dpi 300] [--crops DIR]
      FILE 可為 .pdf 或 png/jpg。PDF 先讀向量紅線，沒有向量紅線的頁面自動改用像素偵測。
  python3 pitch_lines.py classify "L H H┐ L"
      依一個詞的每拍標記判定 型（號數）與完整高低。標記：L=低，H=高，H┐=高且其後下降，?=不明。

圖片模式的驗證狀態：紅線（線與下降角）的位置偵測已在第 1 頁驗證，與 PDF 向量座標 48/48 吻合、誤差 < 1pt；
但「紅線對應到哪幾個字格」仍是實驗性質，字格切分可能多切或少切，必須對照 --crops 產生的小圖人工確認。

輸出的每一行是一串「拍」，格式 `假名:標記`，由左到右。詞的邊界由人或模型決定，
再用 classify 對該詞的標記判定。不明就回報 待確認，不猜。
"""
import sys, json, argparse
import numpy as np

SMALL = set('ゃゅょぁぃぅぇぉゎャュョァィゥェォヮ')


def is_kana(c):
    return '぀' <= c <= 'ヿ'


def is_red_rgb01(col):
    r, g, b = col
    return r > 0.9 and 0.35 < g < 0.65 and 0.35 < b < 0.65


# ---------------------------------------------------------------- 紅線聲調判定
def classify(marks):
    """marks: 每拍標記清單，如 ['L','H','H┐','L']。回傳 dict。"""
    n = len(marks)
    if n == 0 or any(m == '?' for m in marks):
        return dict(status='待確認', reason='有不明的拍')
    drops = [i for i, m in enumerate(marks) if m.endswith('┐')]
    highs = [i for i, m in enumerate(marks) if m.startswith('H')]
    if len(drops) > 1:
        return dict(status='待確認', reason='出現多個下降角')
    if drops:
        k = drops[0] + 1
        if any(i > drops[0] for i in highs):
            return dict(status='待確認', reason='下降角之後仍有高音')
        contour = ['H'] + ['L'] * (n - 1) if k == 1 else ['L'] + ['H'] * (k - 1) + ['L'] * (n - k)
        kind = '頭高型' if k == 1 else ('尾高型' if k == n else '中高型')
        return dict(status='ok', kind=kind, number=k, contour=''.join(contour),
                    text='%s（%d）' % (kind, k))
    if highs:
        if highs[0] == 0:
            return dict(status='待確認', reason='第一拍高但沒有下降角')
        if highs[0] == 1 and highs == list(range(1, n)):
            return dict(status='ok', kind='平板型', number=0, contour='L' + 'H' * (n - 1),
                        text='平板型（0）')
        return dict(status='待確認', reason='高音線沒有從第二拍連續到詞末')
    return dict(status='待確認', reason='沒有任何紅線')


def marks_text(morae):
    return ' '.join('%s:%s' % (m['mora'], m['mark']) for m in morae)


# ---------------------------------------------------------------- PDF 向量模式
def pdf_red_segments(page):
    segs = []
    for d in page.get_drawings():
        col = d.get('color')
        if not col or not is_red_rgb01(col):
            continue
        pts = []
        for it in d['items']:
            if it[0] == 'l':
                pts += [it[1], it[2]]
        if not pts:
            continue
        xs = [p.x for p in pts]
        ys = [p.y for p in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        if y1 - y0 < 1.0:
            segs.append(dict(kind='line', x0=x0, x1=x1, y=y0))
        else:
            segs.append(dict(kind='angle', x0=x0, x1=x1, y=y0, y1=y1))
    return segs


def pdf_chars(page):
    out = []
    raw = page.get_text('rawdict')
    for b in raw['blocks']:
        for l in b.get('lines', []):
            for s in l['spans']:
                for c in s['chars']:
                    if c['c'].strip() == '':
                        continue
                    x0, y0, x1, y1 = c['bbox']
                    out.append(dict(c=c['c'], x0=x0, y0=y0, x1=x1, y1=y1, size=s['size']))
    return out


def is_kanji(c):
    return '一' <= c <= '鿿' or c in '々〆'


def build_streams(chars):
    """把文字層字元整理成『讀音串』：主列假名 + 漢字上方的注音，漢字無注音則保留漢字並標記。"""
    # 去除重複繪製的同一字元
    seen, uniq = set(), []
    for c in chars:
        key = (c['c'], round(c['x0'], 0), round(c['y0'], 0))
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    chars = uniq

    kanji = [c for c in chars if is_kanji(c['c']) and c['size'] >= 9]
    ruby, main = [], []
    for c in chars:
        cx = (c['x0'] + c['x1']) / 2
        is_ruby = False
        if is_kana(c['c']) and c['size'] <= 9:
            for k in kanji:
                if k['size'] >= 1.4 * c['size'] and 0 <= k['y0'] - c['y0'] <= 16 and k['x0'] - 14 <= cx <= k['x1'] + 14:
                    is_ruby = True
                    break
        (ruby if is_ruby else main).append(c)

    rows = []
    for c in sorted(main, key=lambda c: c['y0']):
        cy = (c['y0'] + c['y1']) / 2
        for r in rows:
            if abs(r['cy'] - cy) < 4:
                r['chars'].append(c)
                break
        else:
            rows.append(dict(cy=cy, chars=[c]))
    streams_raw = []
    for r in rows:
        cs = sorted(r['chars'], key=lambda c: c['x0'])
        cur = [cs[0]]
        for c in cs[1:]:
            if c['x0'] - cur[-1]['x1'] > 1.8 * max(c['size'], cur[-1]['size']):
                streams_raw.append(cur)
                cur = [c]
            else:
                cur.append(c)
        streams_raw.append(cur)

    result = []
    for cs in streams_raw:
        # 連續漢字成一個 run；其餘字元各自一個單位
        units = []
        for c in cs:
            if is_kanji(c['c']):
                if units and units[-1]['type'] == 'kanji' and c['x0'] - units[-1]['chars'][-1]['x1'] < 1.5 * c['size']:
                    units[-1]['chars'].append(c)
                else:
                    units.append(dict(type='kanji', chars=[c], ruby=[]))
            elif is_kana(c['c']):
                units.append(dict(type='kana', chars=[c]))
            else:
                units.append(dict(type='punct', chars=[c]))
        runs = [u for u in units if u['type'] == 'kanji']
        for r in ruby:
            rc = (r['x0'] + r['x1']) / 2
            best, bd = None, 1e9
            for u in runs:
                k0, k1 = u['chars'][0], u['chars'][-1]
                if not (0 <= k0['y0'] - r['y0'] <= 16):
                    continue
                d = 0 if k0['x0'] <= rc <= k1['x1'] else min(abs(rc - k0['x0']), abs(rc - k1['x1']))
                if d < bd:
                    best, bd = u, d
            if best is not None and bd <= 14:
                best['ruby'].append(r)
        toks = []
        for u in units:
            if u['type'] == 'kana':
                toks.append(dict(u['chars'][0], src='main'))
            elif u['type'] == 'kanji':
                if u['ruby']:
                    for r in sorted(u['ruby'], key=lambda r: r['x0']):
                        toks.append(dict(r, src='ruby'))
                else:
                    ch = u['chars']
                    toks.append(dict(c=''.join(k['c'] for k in ch), x0=ch[0]['x0'], x1=ch[-1]['x1'],
                                     y0=ch[0]['y0'], y1=ch[0]['y1'], size=ch[0]['size'], src='kanji_no_ruby'))
            else:
                toks.append(dict(u['chars'][0], src='punct'))
        result.append(toks)
    return result


def assign_marks(streams, segs, all_chars):
    """依紅線把每個 token 標成 L / H / H┐，再合併小假名成『拍』。"""
    def first_below(seg_x0, seg_x1, seg_y, tok):
        # 紅線之下、此 token 上方（同 x）若還有其他文字，代表這條線屬於更近的那一列
        for c in all_chars:
            if c is tok:
                continue
            ov = min(c['x1'], tok['x1']) - max(c['x0'], tok['x0'])
            if ov > 0.4 * (tok['x1'] - tok['x0']) and seg_y - 2 <= c['y0'] < tok['y0'] - 1.5 and c['size'] < tok['size'] + 0.1:
                return False
        return True

    out = []
    for toks in streams:
        flags = []
        for t in toks:
            high = drop = False
            for s in segs:
                if not (s['y'] - 4 <= t['y0'] <= s['y'] + 24):
                    continue
                if s['kind'] == 'line':
                    ov = min(s['x1'], t['x1']) - max(s['x0'], t['x0'])
                    if ov > 0.4 * (t['x1'] - t['x0']) and first_below(s['x0'], s['x1'], s['y'], t):
                        high = True
                else:
                    ov = min(s['x1'], t['x1']) - max(s['x0'], t['x0'])
                    if ov > 0.25 * (t['x1'] - t['x0']) and first_below(s['x0'], s['x1'], s['y'], t):
                        high = True
                        drop = True
            flags.append((high, drop))
        morae = []
        for t, (h, d) in zip(toks, flags):
            if t['src'] == 'punct':
                morae.append(dict(mora=t['c'], mark='|', x0=t['x0'], x1=t['x1'], note='標點／邊界'))
                continue
            if t['src'] == 'kanji_no_ruby':
                morae.append(dict(mora=t['c'], mark='?', x0=t['x0'], x1=t['x1'], note='漢字無注音'))
                continue
            if t['c'] in SMALL and morae and morae[-1].get('mark') not in ('?', '|'):
                m = morae[-1]
                m['mora'] += t['c']
                m['x1'] = t['x1']
                m['_h'] = m['_h'] or h
                m['_d'] = m['_d'] or d
                continue
            morae.append(dict(mora=t['c'], x0=t['x0'], x1=t['x1'], _h=h, _d=d))
        for m in morae:
            if m.get('mark') in ('?', '|'):
                continue
            m['mark'] = ('H┐' if m['_d'] else 'H') if m['_h'] else 'L'
            m.pop('_h', None)
            m.pop('_d', None)
        out.append(morae)
    return out


# ---------------------------------------------------------------- 圖片像素模式
def img_red_segments(rgb, scale):
    from scipy import ndimage as ndi
    r, g, b = rgb[..., 0].astype(int), rgb[..., 1].astype(int), rgb[..., 2].astype(int)
    core = (r > 235) & (g > 95) & (g < 150) & (b > 95) & (b < 150) & (abs(g - b) < 25)
    # 抗鋸齒邊緣顏色較淡：只保留與核心像素相鄰的淺粉紅像素
    soft = (r > 225) & (g > 95) & (g < 215) & (b > 95) & (b < 215) & (abs(g - b) < 25) & (r - g > 30)
    mask = core | (soft & ndi.binary_dilation(core, iterations=2))
    lab, n = ndi.label(mask, structure=np.ones((3, 3)))
    segs = []
    for i, sl in enumerate(ndi.find_objects(lab), 1):
        ys, xs = sl
        h, w = ys.stop - ys.start, xs.stop - xs.start
        if (lab[sl] == i).sum() < 6:
            continue
        if h <= 2.6 * scale and w >= 4 * scale:
            segs.append(dict(kind='line', x0=xs.start, x1=xs.stop, y=ys.start, y1=ys.stop))
        elif h >= 3 * scale and w >= 2.5 * scale:
            segs.append(dict(kind='angle', x0=xs.start, x1=xs.stop, y=ys.start, y1=ys.stop))
    return segs


def img_cells(rgb, seg, scale):
    """紅線下方最近一列文字的字格（以暗色筆畫連通區域，依 x 合併）。回傳 [(x0,x1)]。"""
    from scipy import ndimage as ndi
    H, W, _ = rgb.shape
    pad = int(14 * scale)
    xa, xb = max(0, int(seg['x0'] - pad)), min(W, int(seg['x1'] + pad))
    ya, yb = int(seg['y']) + 1, min(H, int(seg['y'] + 26 * scale))
    sub = rgb[ya:yb, xa:xb].astype(int)
    dark = (sub[..., 0] < 120) & (sub[..., 1] < 120) & (sub[..., 2] < 120)
    lab, n = ndi.label(dark, structure=np.ones((3, 3)))
    boxes = []
    for sl in ndi.find_objects(lab):
        ys, xs = sl
        if (ys.stop - ys.start) * (xs.stop - xs.start) < (1.2 * scale) ** 2:
            continue
        boxes.append([xs.start + xa, xs.stop + xa, ys.start + ya, ys.stop + ya])
    if not boxes:
        return []
    top = min(b[2] for b in boxes)
    row = [b for b in boxes if b[2] - top < 6 * scale]
    row.sort()
    cells = []
    for b in row:
        if cells and b[0] <= cells[-1][1] + 0.4 * scale:
            cells[-1][1] = max(cells[-1][1], b[1])
            cells[-1][2] = min(cells[-1][2], b[2])
            cells[-1][3] = max(cells[-1][3], b[3])
        else:
            cells.append(list(b))
    return cells


def img_extract(rgb, scale, crops_dir=None, tag='p'):
    from PIL import Image
    segs = img_red_segments(rgb, scale)
    # 把同一列、水平相鄰的線與下降角串成一組
    segs.sort(key=lambda s: (round(s['y'] / (6 * scale)), s['x0']))
    groups = []
    for s in segs:
        for g in groups:
            if abs(g[-1]['y'] - s['y']) < 4 * scale and s['x0'] - g[-1]['x1'] < 20 * scale:
                g.append(s)
                break
        else:
            groups.append([s])
    results = []
    for gi, g in enumerate(groups):
        x0 = min(s['x0'] for s in g)
        x1 = max(s['x1'] for s in g)
        cells = []
        for s in g:
            for c in img_cells(rgb, s, scale):
                if not any(abs(c[0] - e[0]) < 1.5 * scale and abs(c[1] - e[1]) < 1.5 * scale for e in cells):
                    cells.append(c)
        cells.sort()
        marks = []
        for c in cells:
            cx = (c[0] + c[1]) / 2
            mark = 'L'
            for s in g:
                if s['kind'] == 'line' and s['x0'] - 1 <= cx <= s['x1'] + 1:
                    mark = 'H'
                if s['kind'] == 'angle' and s['x0'] - 1 <= cx <= s['x1'] + 1.5 * scale:
                    mark = 'H┐'
            marks.append(dict(mora='□', mark=mark, x0=float(c[0]), x1=float(c[1])))
        item = dict(index=gi, bbox_px=[int(x0), int(min(s['y'] for s in g)), int(x1), int(max(s['y1'] for s in g))],
                    morae=marks, note='圖片模式：假名需對照 crop 圖補上（□ 為待補）；下降角若在最後一格之後請人工確認')
        if crops_dir:
            import os
            os.makedirs(crops_dir, exist_ok=True)
            H, W, _ = rgb.shape
            bx0, by0 = max(0, int(x0 - 20 * scale)), max(0, int(min(s['y'] for s in g) - 6 * scale))
            bx1, by1 = min(W, int(x1 + 30 * scale)), min(H, int(by0 + 40 * scale))
            im = Image.fromarray(rgb[by0:by1, bx0:bx1])
            im = im.resize((im.width * 2, im.height * 2))
            path = os.path.join(crops_dir, '%s_%03d.png' % (tag, gi))
            im.save(path)
            item['crop'] = path
        results.append(item)
    return results


# ---------------------------------------------------------------- 主程式
def run_extract(args):
    path = args.file
    out = []
    if path.lower().endswith('.pdf'):
        import pymupdf
        doc = pymupdf.open(path)
        pages = [args.page - 1] if args.page else range(len(doc))
        for pi in pages:
            page = doc[pi]
            segs = pdf_red_segments(page)
            if segs:
                chars = pdf_chars(page)
                streams = build_streams(chars)
                lines = assign_marks(streams, segs, chars)
                lines = [l for l in lines if any(m['mark'] not in ('L', '|', '?') for m in l)]
                out.append(dict(page=pi + 1, mode='pdf-vector', segments=len(segs),
                                lines=[dict(text=marks_text(l), morae=l) for l in lines]))
            else:
                pix = page.get_pixmap(dpi=args.dpi)
                rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3]
                res = img_extract(rgb, args.dpi / 72.0, args.crops, 'p%d' % (pi + 1))
                out.append(dict(page=pi + 1, mode='pdf-raster', groups=res))
    else:
        from PIL import Image
        rgb = np.asarray(Image.open(path).convert('RGB'))
        res = img_extract(rgb, args.dpi / 72.0, args.crops, 'img')
        out.append(dict(page=1, mode='image', groups=res))
    print(json.dumps(out, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    e = sub.add_parser('extract')
    e.add_argument('file')
    e.add_argument('--page', type=int)
    e.add_argument('--dpi', type=int, default=300)
    e.add_argument('--crops')
    c = sub.add_parser('classify')
    c.add_argument('marks')
    args = ap.parse_args()
    if args.cmd == 'extract':
        run_extract(args)
    else:
        print(json.dumps(classify(args.marks.split()), ensure_ascii=False))


if __name__ == '__main__':
    main()
