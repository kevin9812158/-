---
name: japanese-class-notes
description: 把日語課的帶時間戳逐字稿（.srt，中文為主夾日文、語音辨識品質差）整理成和使用者原版講義同樣撰寫邏輯、同樣版面的可編輯 Word 筆記（.docx）：詞卡配いらすとや插圖、Word 內建ルビ、聲調紅線、主題表、短句練習、文末待確認清單。只要使用者上傳日文課逐字稿、提到「課堂筆記」「講義」「L33 單字」「把這堂課整理成筆記」「做成跟之前一樣的筆記」，或要繼續某一課的筆記、調整筆記版面或插圖，就使用本 skill，即使沒有明說 Word 或 docx。
---

# 日文課堂筆記

模型負責內容，`scripts/build_note.py` 負責版面。成品要長得像使用者的原版講義，不能自創格式。

## 和使用者合作的方式

- 全程繁體中文，口吻自然，不用「結論／建議」這類公式化標題。
- 資料不足就請使用者補充，不要自己編。逐字稿辨識不出來的內容，不要硬猜。
- 使用者在意成本：沒有經過同意，不要開子代理，也不要一次做大量處理。範本 PDF 一次只看一頁（轉成 100–110 dpi 的圖片），不要整份讀。
- 版面調整一次改一頁，改完給使用者看預覽，確認後再改下一頁。

## 三階段流程（每階段做完就停下來等確認，不要自己跳到下一階段）

1. **整理（階段 1）**：只列出要收進筆記的項目清單，不寫內容。每一項標出：
   - 類型：課外補充／單字／文型／例文／會話／小文章／練習
   - 逐字稿時間範圍
   - 一句話主題

   另外列出不收錄的段落（閒聊、雜音），並先說明你做了哪些取捨判斷，讓使用者可以修改。
2. **撰寫（階段 2）**：照確認過的清單寫內容，形式比照範本：詞卡、主題表、短句＋一行中文。辨識錯字依上下文還原；正文只寫還原後的日文，原本的辨識結果和更正一律放進待確認清單。開始寫之前先讀 `references/writing-rules.md`。
3. **組版（階段 3）**：
   1. 把內容寫成 note.json。格式見 `references/note-json.md`，範例見 `assets/example_note_L33.json`。
   2. 找插圖，規則見 `references/illustrations.md`。
   3. 產生 Word：`python3 scripts/build_note.py note.json out.docx`。
   4. 產生預覽：`python3 scripts/build_note.py note.json preview.docx --preview`，再用 `soffice --headless --convert-to pdf preview.docx` 轉成 PDF，看圖逐頁檢查。
   5. 對照 `references/layout.md` 的密度標準：一般頁要排滿，只有大段落結束時才可以留白。

   交付時同時給 .docx 和 PDF 預覽。Claude App 的檔案預覽不會解析 .docx，只給 .docx 的話，使用者會看到亂碼。

## 為什麼要這樣分工

使用者要的是「複習用講義」，不是「課堂紀錄」。所以：
- 正文不放時間戳，不敘述課堂經過。
- 同一個主題的零散片段要併成一張表。
- 課堂上的操作（兩兩對話、換算遊戲）不收，只收句子本身。

不確定的內容一律放在文末待確認清單，正文保持乾淨。使用者會根據這份清單回頭聽錄音、補資料。清單依風險分流：所有項目都保留，每條標【高／中／低】和依據來源，高風險排最前面先審。規則見 `references/writing-rules.md`。

## 聲調

聲調資料來自使用者的 JAPANESE UP 聲調 MCP。使用前先確認同意狀態，少量查詢，原始 JSON 照實保留，不要自行補齊未知的聲調。

- 單字的結果可以直接用；句子目前還有片語層級的缺口（助詞、複合詞），詳見 `references/pitch.md`。
- 用 `scripts/mcp_apply.py` 把 MCP 的逐拍 marks 寫進 note.json（`#m:`）。讀音和 MCP 對不上的行維持 0 號音，並列【高】。
- 拿到 MCP 結果後，用 `scripts/mcp_pending.py` 依 MCP 的品質欄位產生待確認項目。只依 needsReview、warnings、accent、status 判斷，不要自己判斷。
- 沒有警告不代表正確，要保留抽樣比對範本的步驟。
- 審閱後的修正要經使用者逐筆同意，才能送回 MCP。
- 還沒取得聲調的詞，畫成 0 號音，並列一條【高】。

要判讀原版講義上的紅線時，用 `japanese-pitch-reader` skill。

## 參考檔（需要時再讀）

- `references/writing-rules.md`：撰寫邏輯與取捨習慣（從範本歸納），以及常犯的錯。
- `references/layout.md`：版面規格、每頁密度標準、ルビ（JIS X 4051／W3C JLReq）與紅線的做法、版面陷阱。
- `references/note-json.md`：note.json 的日文行寫法與各種區塊。
- `references/illustrations.md`：插圖來源、規約、搜尋與下載方法。
- `references/pitch.md`：聲調標記、拆句規則、對照資料，以及 MCP 的欄位、轉換方式、檢查與回饋流程。
