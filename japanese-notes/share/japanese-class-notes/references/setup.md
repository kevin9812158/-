# 第一次使用：環境設定

第一次用這個 skill 時，先照這份檢查。缺少的項目，告訴使用者怎麼補，或改用備案，不要硬做下去。

## 必要

| 項目 | 用途 | 檢查方式 |
|---|---|---|
| Python 3，加上 `python-docx`、`Pillow` | 產生 Word（`scripts/build_note.py`） | `python3 -c "import docx, PIL"` |
| 使用者的原版講義範本（PDF） | 撰寫邏輯與版面要比照範本 | 請使用者上傳；skill 不附範本 |
| 一堂課的逐字稿（.srt） | 筆記的內容來源 | 請使用者上傳 |

雲端版 Claude Code（claude.ai/code）的預設環境通常已經有 Python、python-docx、Pillow。本機的話，沒有就用 `pip install python-docx pillow` 安裝。

## 選用（沒有也能完成，只是少一些功能）

| 項目 | 沒有時怎麼辦 |
|---|---|
| LibreOffice（`soffice`） | 無法轉 PDF 預覽，只交 .docx，請使用者自己開 Word 檢查 |
| 原版字型：Yu Gothic UI、清松手寫體1、源石黑體 M | Word 會用替代字型。預覽時加 `--preview`，換成環境裡的 IPAGothic |
| 網路可連到いらすとや：www.irasutoya.com、blogger.googleusercontent.com、1.bp.blogspot.com～4.bp.blogspot.com | 插圖下載失敗時，詞卡會改放灰色圖名佔位。雲端環境要在環境設定的網路存取裡開放這些網域，被擋時用 `curl -sS "$HTTPS_PROXY/__agentproxy/status"` 查被擋的主機名 |
| JAPANESE UP 聲調 MCP | 聲調一律從 0 號音開始，全部靠審閱台人工點選 |
| 發布帶資料庫的 Artifact 頁面（Artifact、ArtifactData 工具） | 審閱台不能用，改用 `scripts/review_list.py` 在對話中貼對照表 |
| `japanese-pitch-reader` skill | 要判讀範本上的紅線時，照 `references/pitch.md` 的標記規則人工判讀 |

## JAPANESE UP 聲調 MCP 的設定

需要使用者自己有 jp.hikorin.com 的帳號。

1. 到 claude.ai 的「設定／自訂 → 連接器」，選「新增自訂連接器」：
   - 名稱：`JAPANESE UP！聲調查詢`
   - 網址：`https://jp.hikorin.com/mcp`
   - 驗證：立即登入
   - OAuth client：Register automatically（自動註冊）
   - Request headers 留空
2. 儲存後連接，在 jp.hikorin.com 的登入頁用自己的帳號登入，並同意授權。帳號是在那個網站的頁面上輸入，不是在 Claude 的設定裡。
3. **開一個新的工作階段**：連接器只在工作階段開始時載入。
4. 第一次使用前，先用 `getPronunciationCollaborationStatus` 確認同意狀態是 current。查詢內容會在伺服器保存 90 天。

註冊時如果出現「Couldn't register with …」，是伺服器拒絕自動註冊（例如回呼網址 `https://claude.ai/api/mcp/auth_callback` 不在白名單）。請使用者聯絡服務擁有者，或改用「Use your own OAuth client」並填入服務擁有者提供的 client ID。

## 聲調審閱台的設定

每個人用自己的一份頁面，資料互不相通。不要使用別人的審閱台網址：別人的頁面是私人的，打不開；就算打得開，資料也會混在一起。

1. 先用 Artifact 工具的 `action: "list"`，找標題為「聲調審閱台」的頁面。找到就沿用它的網址。
2. 沒有的話，發布 `assets/pitch-review.html` 建立一份：
   - `capabilities: {"db": {}}`
   - `icon: "checklist"`
   - 頁面只有使用者本人看得到。
3. 每一課是一個批次，寫入方式見 `references/pitch.md` 的「審閱台」。

## 範本對照

範本是使用者的老師或使用者自己的講義，風格可能和本 skill 歸納的不同。第一次拿到範本時：

1. 一頁一頁轉成 100–110 dpi 的圖片來看，不要整份讀。
2. 整理一張「哪一頁示範什麼」的對照表，給使用者確認。
3. 對照表與 `references/writing-rules.md`、`references/layout.md` 不一致的地方，**以使用者的範本為準**，並把差異告訴使用者。
