# 線上課音訊流程（本地）— 給在使用者電腦上執行的 Claude

先讀 `../實驗_線上課流程_交接.md` 最後幾節（音訊定位、更正、PoC），了解為什麼是現在這套做法。

## 使用者偏好
- 繁體中文、口吻自然；成本敏感，大量處理前先說明時間。
- 誤差超過 1000 ms 就是嚴重錯誤；位置一律要「實際切下來辨識」驗證，不能只看模型時間戳。
- 有聲書素材優先用 Haruki，其次老師；句首的「はい」「えー」等回應詞要切掉。
- 只做長句（10 拍以上）；單字、短片語不找。
- 課堂錄音、辨識結果、模型都不進 git（`lessons/`、`models/` 已在 .gitignore）。

## 環境
- 安裝：雙擊 `setup_windows.bat`（Python、ffmpeg、套件、模型）。檢查：`python pipeline.py check`。
- 程式本體在 `../online/`，`pipeline.py` 只管路徑和順序；切割工具在 `../tools/clip_tool/`。

## 一課的流程
1. `lessons/<課名>/` 放課堂音檔（只放一個）。筆記內容 note.json 在 `../online/`（或該課的位置）。
2. `python pipeline.py asr lessons/<課名>`（3 小時約 25 分鐘；結果存檔，之後不重跑）
3. 找 Haruki 錨點：逐字稿（Plaud MCP）裡老師說「Haruki，請念」之後那句的時間，3～6 個，
   用 asr_full.jsonl 確認那幾秒的辨識內容是 Haruki 念的句子。
   `python pipeline.py speakers lessons/<課名> 秒數1 秒數2 …`
4. `python pipeline.py locate lessons/<課名> <note.json>` → audio_positions.tsv（粗定位，找出句子編號與大約時段）
5. `python pipeline.py refine lessons/<課名> <note.json> <時段起秒> <時段迄秒> <句子編號…>` → cuts.tsv
6. 驗收：照 cuts.tsv 從原始音檔用 ffmpeg 切下來重新辨識，確認剛好是那一句；有疑問的列給使用者。
7. `python pipeline.py tool lessons/<課名>` 打開切割工具，讓使用者試聽、微調、匯出。

## 10/06 這一課（已在雲端做過，可用來驗證本地環境）
- 音檔：`PassFab20261006_183938033_1.m4a`（使用者 Drive 也有）。note：`../online/note_20261006.json`。
- Haruki 錨點：1072.312 1075.288 4056.5 8909.0 9659.5 9761.0
- 第 1 頁 PoC：`refine … 900 1350 6 7 9 11 13`，預期結果見 `../online/poc_page1_cuts.tsv`
  （第 9 句後來手動把起點改到 0:17:51.910 去掉「はい」）。
