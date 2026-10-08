"""日文課堂筆記 Word 產生器（實驗版）

讀取 note.json，產生仿原版講義版面的 .docx。
讀音用 Word 內建ルビ（w:ruby），照 JIS X 4051／W3C JLReq：熟語ルビ逐字對應、
ルビ字級＝親字 1/2、置中；日文段落開禁則處理。
聲調紅線和原版一樣是另外畫的線條圖形（DrawingML），位置由程式依字寬算出：
Yu Gothic UI 全形字 1.026em、數字 0.601em（取自原版 PDF）。在 Word 裡改字後線不會跟著動，
要改內容請改 note.json 重新產生。--preview 會換成本環境的 IPAGothic，只供 LibreOffice 預覽。

日文行的寫法（字串）：
  片段之間用「／」分隔。
  {漢字|讀音}  有讀音的漢字；熟語逐字寫（{割|わり}{引|びき}），熟字訓才整組寫（{今日|きょう}）。
  +助詞       接續文字（例：{割引|わりびき}+は），讀音不同時寫成 +は=わ。
  #n          該片段的聲調號數（省略時用 accent_default，null 表示待確認、不畫線）。
  !、 !。     標點（不畫線）。
  @A：        標籤（不畫線）。

區塊：title、tag、cards、bullets、defs、grid、sentences、note、pending，
欄位說明見 00_先讀我_知識總覽.md 第 7 節。
"""
import hashlib, json, os, re, sys, urllib.request
from docx import Document
from docx.shared import Pt, RGBColor, Emu
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ROW_HEIGHT_RULE, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# ---- 樣式（數值取自原版 PDF） ----
FONT_JP = "Yu Gothic UI"          # 原版：黑體 UI（日本語）
FONT_TITLE = "源石黑體 M"
FONT_ZH = "清松手寫體1"
FONT_HEAD = "Calibri"
SZ_JP, SZ_RUBY, SZ_ZH, SZ_HEAD = 14, 7, 12, 10  # ルビ＝親字 1/2（JLReq）
BLUE = RGBColor(0x00, 0x70, 0xC0)
GRAY = RGBColor(0x76, 0x71, 0x71)
ORANGE = RGBColor(0xC5, 0x5A, 0x11)
PITCH_RED = "FF7D80"
BORDER_GRAY = "E8E6E6"
HEAD_FILL = "DEEAF6"
TAG_FILL = "FFE699"
PRACTICE_FILL = "E7E6E6"  # 短句練習表頭（灰）
CONTENT_W = 487  # pt，A4 扣左右邊界 54pt
ILLUST_BOX = (100, 92)  # pt，詞卡插圖最大寬高（範本約 100pt，詞卡寬約 162pt）
IMG_CACHE = os.environ.get("NOTE_IMG_CACHE") or os.path.join(os.getcwd(), "images")  # 插圖快取（預設：執行時目錄下的 images/）

SMALL = set("ゃゅょぁぃぅぇぉゎャュョァィゥェォヮ")


# ---------- 小工具 ----------
def set_font(run, name, size, color=None, bold=False):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts"); rpr.insert(0, rf)
    for a in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rf.set(qn(a), name)
    if color is not None:
        run.font.color.rgb = color


def tight(par, align=None):
    pf = par.paragraph_format
    pf.space_before = Pt(0); pf.space_after = Pt(0); pf.line_spacing = 1.0
    if align is not None:
        par.alignment = align


def shade(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), fill)
    tcPr.append(shd)


def cell_borders(cell, **sides):
    """sides: top/right/bottom/left = (color, size_eighths) 或 None（無框線）"""
    tcPr = cell._tc.get_or_add_tcPr()
    b = tcPr.find(qn("w:tcBorders"))
    if b is None:
        b = OxmlElement("w:tcBorders"); tcPr.append(b)
    for side in ("top", "left", "bottom", "right"):
        if side not in sides:
            continue
        el = OxmlElement(f"w:{side}")
        v = sides[side]
        if v is None:
            el.set(qn("w:val"), "nil")
        else:
            el.set(qn("w:val"), "single"); el.set(qn("w:sz"), str(v[1]))
            el.set(qn("w:space"), "0"); el.set(qn("w:color"), v[0])
        b.append(el)


def table_borders(table, color=None, sz=8):
    tblPr = table._tbl.tblPr
    old = tblPr.find(qn("w:tblBorders"))
    if old is not None:
        tblPr.remove(old)
    b = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{side}")
        if color is None:
            el.set(qn("w:val"), "nil")
        else:
            el.set(qn("w:val"), "single"); el.set(qn("w:sz"), str(sz))
            el.set(qn("w:space"), "0"); el.set(qn("w:color"), color)
        b.append(el)
    tblPr.append(b)


def fixed_layout(table, widths_pt, cell_margin_pt=None):
    table.autofit = False
    tblPr = table._tbl.tblPr
    lay = OxmlElement("w:tblLayout"); lay.set(qn("w:type"), "fixed"); tblPr.append(lay)
    if cell_margin_pt is not None:
        mar = OxmlElement("w:tblCellMar")
        for side in ("left", "right", "top", "bottom"):
            el = OxmlElement(f"w:{side}")
            el.set(qn("w:w"), str(int(cell_margin_pt.get(side, 0) * 20))); el.set(qn("w:type"), "dxa")
            mar.append(el)
        tblPr.append(mar)
    tw = tblPr.find(qn("w:tblW"))  # 明確指定總寬，避免 LibreOffice 依內容縮放
    if tw is None:
        tw = OxmlElement("w:tblW"); tblPr.append(tw)
    tw.set(qn("w:type"), "dxa"); tw.set(qn("w:w"), str(int(sum(widths_pt) * 20)))
    grid = table._tbl.tblGrid
    for gc, w in zip(grid.findall(qn("w:gridCol")), widths_pt):
        gc.set(qn("w:w"), str(int(w * 20)))
    for row in table.rows:
        for c, w in zip(row.cells, widths_pt):
            c.width = Pt(w)


def first_par(cell):
    p = cell.paragraphs[0]
    tight(p)
    return p


# ---------- 日文行解析與聲調 ----------
def split_mora(kana):
    out = []
    for ch in kana:
        if ch in SMALL and out:
            out[-1] += ch
        else:
            out.append(ch)
    return out


def parse_line(line, accent_default):
    items = []
    for raw in line.split("／"):
        raw = raw.strip()
        if not raw:
            continue
        if raw.startswith("!"):
            items.append({"kind": "punct", "text": raw[1:]}); continue
        if raw.startswith("@"):
            items.append({"kind": "label", "text": raw[1:]}); continue
        accent = accent_default
        m = re.search(r"#(null|\d+)$", raw)
        if m:
            accent = None if m.group(1) == "null" else int(m.group(1))
            raw = raw[: m.start()]
        body, *gaps = raw.split("+")
        parts = []  # (base, ruby or None)
        for tok in re.finditer(r"\{([^|}]+)\|([^}]+)\}|([^{]+)", body):
            if tok.group(1):
                parts.append((tok.group(1), tok.group(2)))
            else:
                for mo in split_mora(tok.group(3)):
                    parts.append((mo, None))
        gap_parts = []
        for g in gaps:
            shown, _, said = g.partition("=")
            gap_parts.append((shown, said or shown))
        items.append({"kind": "seg", "parts": parts, "gaps": gap_parts, "accent": accent})
    return items


def pitch_marks(n_body, n_gap, accent):
    """回傳 (body_marks, gap_marks)，每拍為 (high, drop)。accent=None → 全部不畫。"""
    if accent is None:
        return [(False, False)] * n_body, [(False, False)] * n_gap
    body = []
    for i in range(n_body):
        if accent == 0:
            body.append((i >= 1, False))
        elif accent == 1:
            body.append((i == 0, i == 0))
        else:
            body.append((1 <= i <= accent - 1, i == accent - 1))
    gap_high = accent == 0
    return body, [(gap_high, False)] * n_gap


# ---------- 字寬（取自原版 PDF 嵌入的 Yu Gothic UI：全形 1.026em、數字 0.601em） ----------
METRICS = {"cjk": 1.026, "digit": 0.601, "ascii": 0.6}
PREVIEW_FONT = "IPAGothic"  # --preview：換成此環境有的等寬字型，讓 LibreOffice 預覽的線位對得上
PREVIEW_METRICS = {"cjk": 1.0, "digit": 0.5, "ascii": 0.5}
TAB_X = 18        # pt，• 或標籤後的日文起點（用定位點固定，不受 • 字寬影響）
LINE_H = 25       # pt，日文行固定行高（含ルビ），讓紅線的垂直位置可預測
PITCH_Y = 1.0     # pt，紅線距行頂（ルビ上緣再往上一點）
PITCH_DROP = 6.5  # pt，下降處往下的長度（到ルビ底）
PITCH_W = 0.75    # pt，紅線粗細
_shape_id = [1000]


def char_w(ch, size):
    if ch.isascii():
        return size * (METRICS["digit"] if ch.isdigit() else 0.3 if ch == " " else METRICS["ascii"])
    return size * METRICS["cjk"]


def text_w(s, size):
    return sum(char_w(c, size) for c in s)


def layout_line(items, x0):
    """依字寬排出整行：回傳 runs（("text", s) 或 ("ruby", base, ruby)）、
    morae（每拍 (片段序號, x1, x2, high, drop)，x 為ルビ或假名本身的位置）與行尾 x。
    ルビ照 JLReq：モノルビ／熟語ルビ置中；ルビ比親字長時，親字兩側加空（ルビ從片段起點開始）。"""
    x, runs, morae = x0, [], []
    for k, it in enumerate(items):
        if it["kind"] in ("punct", "label"):
            runs.append(("text", it["text"])); x += text_w(it["text"], SZ_JP)
            continue
        seq = []
        for base, ruby in it["parts"]:
            if ruby:
                bw, rw = text_w(base, SZ_JP), text_w(ruby, SZ_RUBY)
                rx = x + (max(bw, rw) - rw) / 2
                for mo in split_mora(ruby):
                    w = text_w(mo, SZ_RUBY); seq.append((rx, rx + w)); rx += w
                runs.append(("ruby", base, ruby)); x += max(bw, rw)
            else:
                w = text_w(base, SZ_JP); seq.append((x, x + w)); runs.append(("text", base)); x += w
        n_body = len(seq)
        for shown, _said in it["gaps"]:
            for mo in split_mora(shown):
                w = text_w(mo, SZ_JP); seq.append((x, x + w)); runs.append(("text", mo)); x += w
        bm, gm = pitch_marks(n_body, len(seq) - n_body, it["accent"])
        for (x1, x2), (hi, dr) in zip(seq, bm + gm):
            morae.append((k, x1, x2, hi, dr))
    return runs, morae, x


def pitch_segments(morae):
    """把同一片段內連續的高音拍連成一條線；回傳 (x1, x2, drop)。"""
    segs, cur = [], None
    for k, x1, x2, hi, dr in morae:
        if hi and cur and cur[0] == k and not cur[3]:
            cur = [k, cur[1], x2, dr]
        else:
            if cur:
                segs.append(tuple(cur[1:]))
            cur = [k, x1, x2, dr] if hi else None
    if cur:
        segs.append(tuple(cur[1:]))
    return segs


def measure_line(line, accent_default, bullet=False):
    """日文行的寬度（pt），不含中文。"""
    return layout_line(parse_line(line, accent_default), TAB_X if bullet else 0)[2]


NS_DRAW = ('xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
           'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
           'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"')


def pitch_shape(x1, x2, drop):
    """一條聲調紅線（DrawingML 圖形），水平位置相對於行首字元、垂直位置相對於行頂。"""
    from docx.oxml import parse_xml
    E = 12700
    _shape_id[0] += 1
    sid = _shape_id[0]
    w, h = int((x2 - x1) * E), int(PITCH_DROP * E) if drop else 0
    if drop:
        geom = (f'<a:custGeom><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/><a:rect l="0" t="0" r="r" b="b"/>'
                f'<a:pathLst><a:path w="{w}" h="{h}" fill="none"><a:moveTo><a:pt x="0" y="0"/></a:moveTo>'
                f'<a:lnTo><a:pt x="{w}" y="0"/></a:lnTo><a:lnTo><a:pt x="{w}" y="{h}"/></a:lnTo>'
                f'</a:path></a:pathLst></a:custGeom>')
    else:
        geom = '<a:prstGeom prst="line"><a:avLst/></a:prstGeom>'
    xml = (f'<w:drawing {NS_DRAW} xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f'<wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="{sid}" '
           f'behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">'
           f'<wp:simplePos x="0" y="0"/>'
           f'<wp:positionH relativeFrom="character"><wp:posOffset>{int(x1 * E)}</wp:posOffset></wp:positionH>'
           f'<wp:positionV relativeFrom="line"><wp:posOffset>{int(PITCH_Y * E)}</wp:posOffset></wp:positionV>'
           f'<wp:extent cx="{w}" cy="{h}"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>'
           f'<wp:docPr id="{sid}" name="pitch {sid}"/><wp:cNvGraphicFramePr/>'
           f'<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
           f'<wps:wsp><wps:cNvSpPr/><wps:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'
           f'{geom}<a:noFill/><a:ln w="{int(PITCH_W * E)}"><a:solidFill><a:srgbClr val="{PITCH_RED}"/></a:solidFill></a:ln>'
           f'</wps:spPr><wps:bodyPr/></wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing>')
    return parse_xml(xml)


PPR_ORDER = ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl", "numPr",
             "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap",
             "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd",
             "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc"]


def ppr_set(p, tag, val=None):
    """依 schema 順序在 pPr 插入（或覆寫）一個開關元素。"""
    pPr = p._p.get_or_add_pPr()
    old = pPr.find(qn(f"w:{tag}"))
    if old is not None:
        pPr.remove(old)
    el = OxmlElement(f"w:{tag}")
    if val is not None:
        el.set(qn("w:val"), val)
    later = PPR_ORDER[PPR_ORDER.index(tag) + 1:]
    for child in pPr:
        if child.tag.split("}")[1] in later:
            child.addprevious(el); return
    pPr.append(el)


def ja_paragraph(p):
    """日文段落設定：禁則處理開、取消中日／英數間自動加空（讓字位可預測）、不對齊格線、固定行高。"""
    from docx.enum.text import WD_LINE_SPACING
    tight(p)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    p.paragraph_format.line_spacing = Pt(LINE_H)
    ppr_set(p, "kinsoku")
    ppr_set(p, "autoSpaceDE", "0")
    ppr_set(p, "autoSpaceDN", "0")
    ppr_set(p, "snapToGrid", "0")


def ruby_run(p, base, ruby):
    """Word 內建ルビ：ルビ字級＝親字 1/2，置中（JLReq モノルビ／熟語ルビ）。"""
    from docx.text.run import Run
    r = OxmlElement("w:r")
    rb = OxmlElement("w:ruby")
    pr = OxmlElement("w:rubyPr")
    for tag, val in (("rubyAlign", "center"), ("hps", str(SZ_RUBY * 2)), ("hpsRaise", str(SZ_JP * 2 - 2)),
                     ("hpsBaseText", str(SZ_JP * 2)), ("lid", "ja-JP")):
        el = OxmlElement(f"w:{tag}"); el.set(qn("w:val"), val); pr.append(el)
    rb.append(pr)
    for holder, text, size in (("w:rt", ruby, SZ_RUBY), ("w:rubyBase", base, SZ_JP)):
        h = OxmlElement(holder)
        inner = OxmlElement("w:r"); h.append(inner)
        run = Run(inner, p); run.text = text; set_font(run, FONT_JP, size)
        rb.append(h)
    r.append(rb)
    p._p.append(r)


def target_par(container):
    """cell 中若最後一段是空的就沿用，否則新增段落。"""
    if hasattr(container, "_tc"):
        last = container.paragraphs[-1]
        if not last._p.xpath("./w:r|./w:hyperlink"):
            return last
    return container.add_paragraph()


def zh_runs(p, zh, arrow=None):
    """藍色中文；arrow 為橘色的語感補充（例：「→口語：朋友間常用」）。"""
    if zh:
        r = p.add_run(zh); set_font(r, FONT_ZH, SZ_ZH, BLUE)
    if arrow:
        r = p.add_run(("　" if zh else "") + "→ " + arrow); set_font(r, FONT_ZH, SZ_ZH, ORANGE)


def add_jp_line(container, line, accent_default, bullet=False, trailing_zh=None, arrow=None, avail_w=None):
    """加入一行日文：Word 內建ルビ＋DrawingML 聲調紅線。
    bullet 為 True（•）或字串標籤（"2."、"A："，"補" 會加框）；日文從定位點 TAB_X 開始。
    trailing_zh 接在日文後（定位點）；給 avail_w 且放不下時改放下一行。"""
    items = parse_line(line, accent_default)
    x0 = TAB_X if bullet else 0
    runs, morae, x_end = layout_line(items, x0)
    p = target_par(container)
    ja_paragraph(p)
    anchor = p.add_run()
    for x1, x2, drop in pitch_segments(morae):
        anchor._r.append(pitch_shape(x1, x2, drop))
    if bullet:
        btxt = bullet if isinstance(bullet, str) else "•"
        r = p.add_run(btxt); set_font(r, FONT_JP, SZ_JP)
        if btxt == "補":
            bdr = OxmlElement("w:bdr")
            for a_, v in (("w:val", "single"), ("w:sz", "4"), ("w:space", "0"), ("w:color", "000000")):
                bdr.set(qn(a_), v)
            r._element.get_or_add_rPr().append(bdr)
        p.paragraph_format.tab_stops.add_tab_stop(Pt(TAB_X))
        r = p.add_run("\t"); set_font(r, FONT_JP, SZ_JP)
    for kind, *rest in runs:
        if kind == "ruby":
            ruby_run(p, *rest)
        else:
            r = p.add_run(rest[0]); set_font(r, FONT_JP, SZ_JP)
    if trailing_zh or arrow:
        zh_w = SZ_ZH * (len(trailing_zh or "") + (len(arrow) + 3 if arrow else 0))
        if avail_w is not None and x_end + 14 + zh_w > avail_w:
            q = container.add_paragraph(); tight(q)
            q.paragraph_format.left_indent = Pt(x0)
            q.paragraph_format.space_after = Pt(3)
            zh_runs(q, trailing_zh, arrow)
        else:
            p.paragraph_format.tab_stops.add_tab_stop(Pt(x_end + 14))
            r = p.add_run("\t"); set_font(r, FONT_JP, SZ_JP)
            zh_runs(p, trailing_zh, arrow)
    return p


# ---------- 區塊 ----------
def add_title(doc, text):
    p = doc.add_paragraph(); tight(p, WD_ALIGN_PARAGRAPH.CENTER)
    p.paragraph_format.space_before = Pt(10)
    r = p.add_run(text); set_font(r, FONT_TITLE, 18, bold=True)


def add_tag(doc, text):
    p = doc.add_paragraph(); tight(p, WD_ALIGN_PARAGRAPH.CENTER)
    p.paragraph_format.space_before = Pt(4); p.paragraph_format.space_after = Pt(6)
    r = p.add_run(f" {text} "); set_font(r, FONT_TITLE, 16, bold=True)
    rpr = r._element.get_or_add_rPr()
    shd = OxmlElement("w:shd"); shd.set(qn("w:val"), "clear"); shd.set(qn("w:fill"), TAG_FILL)
    rpr.append(shd)


def outer_table(doc, rows, widths):
    t = doc.add_table(rows=rows, cols=len(widths))
    table_borders(t, BORDER_GRAY, 12)
    fixed_layout(t, widths, {"left": 5, "right": 5, "top": 1, "bottom": 1})
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    for row in t.rows:  # 列不跨頁拆開
        trPr = row._tr.get_or_add_trPr()
        cs = OxmlElement("w:cantSplit"); trPr.append(cs)
    return t


def keep_rows_together(t, upto):
    """第 0..upto-1 列的段落設 keepNext，讓這些列和下一列留在同一頁。"""
    for row in t.rows[:upto]:
        for c in row.cells:
            for p in c.paragraphs:
                p.paragraph_format.keep_with_next = True


def header_row(t, text, fill=HEAD_FILL):
    cell = t.cell(0, 0).merge(t.cell(0, len(t.columns) - 1))
    shade(cell, fill)
    p = first_par(cell); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(text); set_font(r, FONT_JP, 12)


def spacer(doc, pt=8):
    p = doc.add_paragraph(); tight(p)
    p.paragraph_format.line_spacing = Pt(pt)


def block_cards(doc, b, acc):
    """詞卡：每列 per_row 格（預設 3；動詞等較長的詞用 2）。
    card 可帶 label（課本編號 "2." 或 "補"），中文放不下時自動換到下一行。"""
    per_row = b.get("per_row", 3)
    w = CONTENT_W / per_row
    cards = b["cards"]
    nrows = (len(cards) + per_row - 1) // per_row
    t = outer_table(doc, nrows, [w] * per_row)
    for idx, card in enumerate(cards):
        cell = t.cell(idx // per_row, idx % per_row)
        first_par(cell)
        add_jp_line(cell, card["jp"], acc, bullet=card.get("label") or False,
                    trailing_zh=card.get("zh"), arrow=card.get("arrow"), avail_w=w - 10)
        add_illust(cell, card.get("illust"))
    spacer(doc)


def block_bullets(doc, b, acc):
    """表格外的例句（範本：詞卡下方的 • 例句）。"""
    for row in b["rows"]:
        add_jp_line(doc, row["jp"], acc, bullet=row.get("bullet", True),
                    trailing_zh=row.get("zh"), arrow=row.get("arrow"), avail_w=CONTENT_W)
    spacer(doc)


def add_hyperlink(par, url, text, size=9):
    part = par.part
    rid = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                         is_external=True)
    h = OxmlElement("w:hyperlink"); h.set(qn("r:id"), rid)
    r = OxmlElement("w:r"); rpr = OxmlElement("w:rPr")
    fonts = OxmlElement("w:rFonts")
    for a in ("w:ascii", "w:hAnsi", "w:eastAsia"):
        fonts.set(qn(a), FONT_JP)
    col = OxmlElement("w:color"); col.set(qn("w:val"), "0563C1")
    u = OxmlElement("w:u"); u.set(qn("w:val"), "single")
    sz = OxmlElement("w:sz"); sz.set(qn("w:val"), str(size * 2))
    for el in (fonts, col, u, sz):
        rpr.append(el)
    t = OxmlElement("w:t"); t.text = text; t.set(qn("xml:space"), "preserve")
    r.append(rpr); r.append(t); h.append(r); par._p.append(h)


def fetch_image(src):
    """src 為本機路徑或網址；網址會下載到 images/ 快取。失敗回傳 None。"""
    if not re.match(r"https?://", src):
        return src if os.path.exists(src) else None
    name = os.path.basename(src.split("?")[0]) or "img"
    path = os.path.join(IMG_CACHE, hashlib.md5(src.encode()).hexdigest()[:8] + "_" + name)
    if os.path.exists(path):
        return path
    try:
        os.makedirs(IMG_CACHE, exist_ok=True)
        req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
        with open(path, "wb") as f:
            f.write(data)
        return path
    except Exception as e:
        print(f"警告：插圖下載失敗，改用佔位框：{src}（{e}）", file=sys.stderr)
        return None


def add_illust(cell, ill):
    """插圖。ill 可為：None（不放圖）、字串（只有關鍵字）、
    dict(source, title, url[, image])：已選定的圖。有 image（網址或本機路徑）時嵌入圖片，
    依 ILLUST_BOX 等比縮放置中；不放出處（使用者指定，いらすとや 規約也不要求）。
    沒有 image 或下載失敗時，放灰色的圖名佔位。"""
    if not ill:
        return
    p = cell.add_paragraph(); tight(p, WD_ALIGN_PARAGRAPH.CENTER)
    p.paragraph_format.space_before = Pt(4); p.paragraph_format.space_after = Pt(4)
    img = fetch_image(ill["image"]) if isinstance(ill, dict) and ill.get("image") else None
    if img:
        from PIL import Image
        with Image.open(img) as im:
            w, h = im.size
        k = min(ILLUST_BOX[0] / w, ILLUST_BOX[1] / h)
        p.add_run().add_picture(img, width=Pt(w * k), height=Pt(h * k))
        return
    name = ill if isinstance(ill, str) else ill.get("title", "")
    p.paragraph_format.space_before = Pt(36); p.paragraph_format.space_after = Pt(36)
    r = p.add_run(f"[插圖：{name}]"); set_font(r, FONT_JP, 9, GRAY)


def block_sentences(doc, b, acc):
    left = CONTENT_W * 0.72
    rows = b["rows"]
    t = outer_table(doc, len(rows) + 1, [left, CONTENT_W - left])
    header_row(t, b["header"], PRACTICE_FILL if b.get("practice") else HEAD_FILL)
    for i, row in enumerate(rows, start=1):
        lc, rc = t.cell(i, 0), t.cell(i, 1)
        first_par(lc)
        add_jp_line(lc, row["jp"], acc, bullet=row.get("bullet", True))
        rc.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        zh_runs(first_par(rc), row["zh"], row.get("arrow"))
    keep_rows_together(t, 1)
    spacer(doc)


def defs_term(lc, row, acc):
    """主題表左欄：詞（或中文詞名）＋下方中文與語感。"""
    shade(lc, HEAD_FILL)
    first_par(lc)
    if "term_jp" in row:
        add_jp_line(lc, row["term_jp"], acc)
    else:
        p = lc.paragraphs[0]; r = p.add_run(row["term_zh"]); set_font(r, FONT_JP, 12)
    if row.get("term_sub"):
        p = lc.add_paragraph(); tight(p); zh_runs(p, row["term_sub"])
    if row.get("arrow"):
        p = lc.add_paragraph(); tight(p); zh_runs(p, None, row["arrow"])


def block_defs(doc, b, acc):
    """主題表。row 有 examples（[{jp, zh, arrow}]）時用三欄：詞｜例句｜中文，
    每個例句一列、左欄跨列合併、同一詞內不畫橫線（範本：擬聲擬態語）；
    否則用兩欄：詞｜中文（zh）或日文清單（jp_list）。"""
    rows = b["rows"]
    if any("examples" in r for r in rows):
        left, right = CONTENT_W * 0.26, CONTENT_W * 0.24
        mid = CONTENT_W - left - right
        n = sum(max(1, len(r.get("examples", []))) for r in rows)
        t = outer_table(doc, n + 1, [left, mid, right])
        header_row(t, b["header"])
        i = 1
        for row in rows:
            exs = row.get("examples") or [{}]
            lc = t.cell(i, 0)
            if len(exs) > 1:
                lc = lc.merge(t.cell(i + len(exs) - 1, 0))
            lc.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            defs_term(lc, row, acc)
            for k, ex in enumerate(exs):
                mc, rc = t.cell(i + k, 1), t.cell(i + k, 2)
                cell_borders(mc, right=None); cell_borders(rc, left=None)
                if k > 0:
                    cell_borders(mc, top=None); cell_borders(rc, top=None)
                if k < len(exs) - 1:
                    cell_borders(mc, bottom=None); cell_borders(rc, bottom=None)
                if not ex:
                    continue
                w = measure_line(ex["jp"], acc, bullet=True)
                first_par(mc)
                if w > mid - 10:  # 例句太長：例句跨到中文欄，中文放下一行
                    mc = mc.merge(rc)
                    add_jp_line(mc, ex["jp"], acc, bullet=True, trailing_zh=ex.get("zh"),
                                arrow=ex.get("arrow"), avail_w=0)
                else:
                    add_jp_line(mc, ex["jp"], acc, bullet=True)
                    rc.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                    zh_runs(first_par(rc), ex.get("zh"), ex.get("arrow"))
            i += len(exs)
        keep_rows_together(t, 1)
        spacer(doc)
        return
    left = CONTENT_W * 0.28
    t = outer_table(doc, len(rows) + 1, [left, CONTENT_W - left])
    header_row(t, b["header"])
    for i, row in enumerate(rows, start=1):
        lc, rc = t.cell(i, 0), t.cell(i, 1)
        defs_term(lc, row, acc)
        if "zh" in row:
            rc.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            zh_runs(first_par(rc), row["zh"])
        if "jp_list" in row:
            first_par(rc)
            for line in row["jp_list"]:
                add_jp_line(rc, line, acc, bullet=True)
    spacer(doc)


def block_grid(doc, b, acc):
    """對照表：表頭＋欄名列＋資料列。儲存格可為 {"jp": ...}、{"zh": ...} 或字串（當中文）。"""
    ncol = len(b["columns"])
    ratio = b.get("widths") or [1] * ncol
    widths = [CONTENT_W * r / sum(ratio) for r in ratio]
    t = outer_table(doc, len(b["rows"]) + 2, widths)
    header_row(t, b["header"])
    for j, name in enumerate(b["columns"]):
        c = t.cell(1, j); shade(c, HEAD_FILL)
        p = first_par(c); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(name); set_font(r, FONT_JP, 12)
    for i, row in enumerate(b["rows"], start=2):
        for j, val in enumerate(row):
            c = t.cell(i, j); c.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            first_par(c)
            if isinstance(val, dict) and "jp" in val:
                add_jp_line(c, val["jp"], acc, avail_w=widths[j] - 10)
            else:
                text = val["zh"] if isinstance(val, dict) else val
                p = c.paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                zh_runs(p, text)
    keep_rows_together(t, len(t.rows) - 1)  # 對照表整張不拆頁
    spacer(doc)


def block_note(doc, b, acc):
    p = doc.add_paragraph(); tight(p)
    p.paragraph_format.space_after = Pt(8)
    r = p.add_run("＊　" + b["text"]); set_font(r, FONT_ZH, SZ_ZH, ORANGE)


RISK_ORDER = {"高": 0, "中": 1, "低": 2}


def pending_entry(line):
    """待確認清單的一條 → (風險等級, 內容)。
    line 可為 dict(level, item, basis, action) 或字串；字串可用「【高】…」開頭標等級。
    未標等級的當「中」並提出警告（規則：每一條都要標風險等級與依據）。"""
    if isinstance(line, dict):
        level = line.get("level", "中")
        text = "｜".join(x for x in (line.get("item"), line.get("basis"), line.get("action")) if x)
    else:
        m = re.match(r"【([高中低])】\s*", line)
        level, text = (m.group(1), line[m.end():]) if m else ("中", line)
        if not m:
            print(f"警告：待確認項目未標風險等級，暫列為中：{line[:30]}…", file=sys.stderr)
    if level not in RISK_ORDER:
        raise ValueError(f"未知的風險等級：{level}")
    return level, text


def block_pending(doc, b, acc):
    """待確認清單：所有項目都保留，依風險 高→中→低 排序（同等級維持原順序），高風險先審。"""
    p = doc.add_paragraph(); p.add_run().add_break(WD_BREAK.PAGE)
    p = doc.add_paragraph(); tight(p)
    r = p.add_run(b["title"]); set_font(r, FONT_JP, 12, GRAY, bold=True)
    r = p.add_run("　依風險排序：高 → 中 → 低"); set_font(r, FONT_JP, 9, GRAY)
    entries = sorted((pending_entry(x) for x in b["lines"]), key=lambda e: RISK_ORDER[e[0]])
    for level, text in entries:
        p = doc.add_paragraph(); tight(p); p.paragraph_format.space_after = Pt(3)
        r = p.add_run(f"【{level}】"); set_font(r, FONT_JP, 10, ORANGE if level == "高" else GRAY, bold=level == "高")
        r = p.add_run(text); set_font(r, FONT_JP, 10, GRAY)


BLOCKS = {"cards": block_cards, "bullets": block_bullets, "grid": block_grid,
          "sentences": block_sentences, "defs": block_defs,
          "note": block_note, "pending": block_pending,
          "title": lambda d, b, a: add_title(d, b["text"]),
          "tag": lambda d, b, a: add_tag(d, b["text"])}


def page_setup(doc, head_left, head_right):
    s = doc.sections[0]
    s.page_width, s.page_height = Pt(595.3), Pt(841.9)
    s.left_margin = s.right_margin = Pt(54)
    s.top_margin = Pt(64); s.bottom_margin = Pt(60)
    s.header_distance = Pt(40); s.footer_distance = Pt(50)
    hp = s.header.paragraphs[0]; tight(hp)
    from docx.enum.text import WD_TAB_ALIGNMENT
    ts = hp.paragraph_format.tab_stops
    for pos in (Pt(234), Pt(468)):  # 清掉頁首樣式內建的置中／靠右定位點
        ts.add_tab_stop(pos, WD_TAB_ALIGNMENT.CLEAR)
    ts.add_tab_stop(Pt(CONTENT_W), WD_TAB_ALIGNMENT.RIGHT)
    r = hp.add_run(f"{head_left}\t{head_right}"); set_font(r, FONT_HEAD, SZ_HEAD, GRAY)
    fp = s.footer.paragraphs[0]; tight(fp, WD_ALIGN_PARAGRAPH.CENTER)
    r = fp.add_run(); set_font(r, FONT_HEAD, SZ_HEAD, GRAY)
    for tag, text in (("begin", None), (None, "PAGE"), ("end", None)):
        if tag:
            el = OxmlElement("w:fldChar"); el.set(qn("w:fldCharType"), tag)
        else:
            el = OxmlElement("w:instrText"); el.set(qn("xml:space"), "preserve"); el.text = text
        r._element.append(el)


def build(src, dst):
    note = json.load(open(src, encoding="utf-8"))
    doc = Document()
    # 預設段落樣式歸零，避免 Normal 的段後距
    st = doc.styles["Normal"]; st.paragraph_format.space_after = Pt(0)
    page_setup(doc, note["header"]["left"], note["header"]["right"])
    acc = note.get("accent_default", 0)
    for b in note["blocks"]:
        BLOCKS[b["type"]](doc, b, acc)
    doc.save(dst)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--preview" in sys.argv:  # 只給 LibreOffice 預覽用：換成此環境有的字型與其字寬
        FONT_JP = PREVIEW_FONT; METRICS.update(PREVIEW_METRICS)
    build(args[0], args[1])
