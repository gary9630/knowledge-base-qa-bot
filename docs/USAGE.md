# USAGE — 啟動與使用指南

這份文件帶你從零把 Knowledge Base Q&A Bot 跑起來，並逐一說明學員與管理者的
使用方式。架構與工程規範見 [README.md](../README.md) 與 [AGENTS.md](../AGENTS.md)。

---

## 1. 前置需求

| 工具 | 版本 / 備註 |
| --- | --- |
| Python | 3.12（由 `uv` 管理，不必預先安裝） |
| [uv](https://docs.astral.sh/uv/) | 套件與 Python 版本管理 |
| Docker + Docker Compose | 跑 Postgres（pgvector）與容器化部署 |
| OpenAI API key | 真實回答／嵌入需要；純開發可用 fake provider 跳過 |

---

## 2. 第一次啟動（本機開發）

### 2.1 安裝依賴

```bash
git clone https://github.com/gary9630/knowledge-base-qa-bot.git
cd knowledge-base-qa-bot
uv sync --python 3.12 --group dev
```

### 2.2 設定環境變數

```bash
cp .env.example .env
```

`.env` 最少要填：

```bash
# 登入帳號（兩種角色）
KB_AUTH_SECRET_KEY=<隨機長字串>
KB_PLATFORM_USERNAME=student          # 學員帳號
KB_PLATFORM_PASSWORD=<學員密碼>
KB_ADMIN_USERNAME=admin               # 管理者帳號（可進管理主控台）
KB_ADMIN_PASSWORD=<管理者密碼>
KB_ADMIN_API_KEY=<admin API 金鑰>

# 要用真實 LLM 回答時
KB_EMBEDDING_PROVIDER=openai
KB_ANSWER_PROVIDER=openai
OPENAI_API_KEY=sk-...
KB_OPENAI_EMBEDDING_MODEL=text-embedding-3-small
KB_OPENAI_CHAT_MODEL=gpt-5.4-mini
```

不設 OpenAI 時保持 `fake` provider，可以離線開發 UI 與 API（回答為佔位內容）。

### 2.3 啟動資料庫並建表

```bash
docker compose up -d postgres
make migrate
```

### 2.4 放入教材並建立索引

兩種來源擇一：

```bash
# A. 範例教材（快速體驗）
uv run --python 3.12 python -m scripts.seed_sample_docs

# B. 真實課程教材：把 markdown 放進 course-materials-md/（此資料夾不入 git）
#    並將 .env 的 KB_DOCS_DIR 指向它
```

啟動 app 後建立索引：

```bash
make dev          # http://localhost:8000
make index        # 另開終端機執行
```

### 2.5 （可選）背景 worker 與知識圖譜

概念抽取（知識圖譜資料）與排程任務由背景 worker 執行：

```bash
make worker       # 長駐；或 make worker-once 處理單一任務
make graph-seed   # 載入精選的概念圖種子資料
```

> 沒有 worker 在跑時，「觸發概念抽取」排入的任務會一直停在 queued——
> 這不是錯誤；可到管理主控台 → 背景任務取消，或啟動 worker 讓它執行。

---

## 3. 登入與角色

打開 `http://localhost:8000` 會先看到 landing page，右上角「登入」。

| 角色 | 帳號來源 | 能做什麼 |
| --- | --- | --- |
| 學員（student） | `KB_PLATFORM_USERNAME/PASSWORD` | Chat 問答、知識圖譜、閱讀教材 |
| 管理者（admin） | `KB_ADMIN_USERNAME/PASSWORD` | 學員全部功能＋左下角「⚙ 管理主控台」 |

登出按鈕（🚪）在左下角。沒有註冊與忘記密碼流程——帳號就是 `.env` 裡那兩組。

---

## 4. 學員怎麼用

### 4.1 課程助理（Chat）

- 輸入問題送出，回答**逐字串流**並附引用編號 ❶❷…；點編號右欄會顯示該教材段落原文。
- 問題會先經過 LLM guardrail：與課程無關（天氣、聊天）、有害內容、提示注入
  一律擋下，回覆「這個問題和學習無關，Let's learn together!」。
- 通過的題目自動分難度：簡單題用 `gpt-5.4-mini`，需要多概念推理的難題自動
  改用 `gpt-5.4`。
- 教材裡找不到答案時，助理會誠實回覆無法確認，不會編造。
- 每則回答下方可給回饋（有幫助／沒有幫助／找不到我要的）。

對話工具列（標題列右側，開始對話後出現）：

| 按鈕 | 功能 |
| --- | --- |
| 🧹 清除對話 | 清空訊息並開新 session |
| ⬇ 匯出 JSON | 下載整段對話（含引用與 session id） |
| 🚩 回報問題 | 複製 session id 並通知後端記錄，方便管理者排查 |

### 4.2 Sources（教材總覽）

點任一教材卡片即進入**全文閱讀器**：markdown 完整渲染，教材中的 mermaid
圖（流程圖、時序圖）會直接畫成圖形。

### 4.3 知識圖譜

- 三種視角：叢集／放射／學習順序。
- 搜尋框可過濾概念；點節點在右欄顯示概念摘要、別名與相關教材段落，
  可一鍵「拿這個概念去提問」。

---

## 5. 管理者怎麼用（管理主控台）

左下角「⚙ 管理主控台」進入。面板頂部的 Admin Key 欄位通常不用填——
admin 登入的 session 已可呼叫所有 `/admin/*` API。

| 面板 | 用途 |
| --- | --- |
| 總覽 | 索引文件數、圖譜統計、背景任務、token 用量 |
| 上傳與索引 | 上傳教材（PDF/MD/TXT/HTML）、重建索引、追蹤匯入任務 |
| 教材編輯 | **線上編輯 markdown 教材**（如持續更新的課程公告）：選檔 → 載入 → 編輯 → 儲存並自動重新索引；也可直接建立新教材 |
| 文件生命週期 | 啟用／停用／刪除索引／重新索引單一文件 |
| 圖譜抽取 | 觸發概念抽取背景任務（需 worker；內容未變的文件自動略過） |
| 評估與回饋 | Eval cases 管理、執行、報表；學員回饋升級為 eval case |
| 服務狀態 | DB 延遲、pgvector、migration、儲存、索引新鮮度、worker 心跳、provider 預算，一頁健檢 |
| 系統設定 | **免重啟調整 LLM 參數**：chat 模型（一般／困難）、router 模型、max output tokens、temperature、每日呼叫/token 預算 |
| 背景任務 | 任務佇列、取消 queued、重排 failed、回收 stale |
| Provider 用量 | 呼叫統計、token 用量、預算狀態、**LLM 呼叫紀錄**（每次呼叫的完整 request/response，可展開） |
| 審計日誌 | 可排序表格：登入、admin 操作、學員回報（`chat.session_reported`）等 |

### 排查一個學員回報的問題

1. 審計日誌篩 `chat.session_reported`，拿到 conversation id。
2. 用 conversation id 查 `retrieval_events`（問了什麼、檢索到什麼、router 判定）。
3. 同一 id 查 `provider_call_logs` 或在 Provider 用量 → LLM 呼叫紀錄展開，
   看每次 LLM 呼叫的完整 request messages 與 response。

---

## 6. 測試與品質

```bash
make test-unit          # 單元測試（不需 DB）
make test-e2e           # UI/API wiring 測試（不需 DB）
make lint               # ruff + mypy
```

整合測試需要一個獨立的測試資料庫：

```bash
docker exec $(docker compose ps -q postgres) psql -U kb -d kb \
  -c "CREATE DATABASE kb_test OWNER kb;"
docker exec $(docker compose ps -q postgres) psql -U kb -d kb_test \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"

KB_DATABASE_URL_TEST="postgresql+psycopg://kb:kb@localhost:5432/kb_test" \
  make test-integration
```

測試刻意**不讀**本機 `.env`，所以 `.env` 裡的帳密與設定不會影響測試結果。

---

## 7. Docker Compose 全套運行

```bash
docker compose up -d            # app + postgres
docker compose --profile worker up -d   # 加上背景 worker（production 必開）
make docker-smoke               # 煙霧測試
```

部署、備份、上線驗收的完整流程見：

- [ops/deploy.md](../ops/deploy.md)
- [ops/backup-restore.md](../ops/backup-restore.md)
- [ops/live-answer-acceptance.md](../ops/live-answer-acceptance.md)

---

## 8. 疑難排解

| 症狀 | 原因與處理 |
| --- | --- |
| 回答顯示「知識庫尚未建立索引」 | 還沒跑 `make index`，或索引失敗——看管理主控台 → 服務狀態的「索引」卡片 |
| 概念抽取一直 queued | 背景 worker 沒在跑：`make worker`；或到背景任務面板取消 |
| 登入後看不到管理主控台 | 用的是學員帳號；用 `KB_ADMIN_USERNAME` 的帳號登入 |
| API 回 401 | 未登入或 session 過期；`/admin/*` 需要 admin session 或 `X-KB-Admin-Key` |
| `/chat` 回 429 | 觸發 provider 預算上限（`KB_PROVIDER_BUDGET_*`）；可在系統設定面板調整 |
| 改了模型/參數沒生效 | 確認改的是管理主控台「系統設定」（即時生效）；改 `.env` 則需重啟 |
| 服務整體健檢 | `GET /health`（liveness）、`GET /ready`（依賴檢查）、管理主控台 → 服務狀態 |
