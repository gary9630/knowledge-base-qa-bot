# CLAUDE.md

Claude Code 的專案速覽。完整工程規範見 [AGENTS.md](AGENTS.md)，
啟動與使用教學見 [docs/USAGE.md](docs/USAGE.md)。

## 專案是什麼

FastAPI 課程知識庫問答助理：教材（PDF/Markdown/TXT/HTML）轉成 canonical Markdown，
索引進 Postgres + pgvector，學員提問後以 hybrid 檢索（lexical + vector + markdown, RRF
融合）取回段落，交給 OpenAI 模型產生**必附引用**的回答，引用經正規化驗證。

回答管線（`/chat`、`/chat/stream`）：

```text
query → LLM router/guardrail（gpt-5.4-mini，無關課程/有害/提示注入 → 擋下）
      → 難度分級（easy → gpt-5.4-mini；hard → gpt-5.4）
      → hybrid 檢索 → context assembly（段落＋鄰居，token 預算內）
      → answer provider → 引用驗證（slugify 正規化、部分容忍）
      → 持久化：messages / retrieval_events / provider_call_logs（完整 request/response）
```

## 關鍵事實

- Python 3.12 + uv；DB 為 Postgres + pgvector（docker compose）；migration 用 Alembic。
- 雙角色登入設定在 `.env`：學員 `KB_PLATFORM_USERNAME/PASSWORD`（role=student）、
  管理者 `KB_ADMIN_USERNAME/PASSWORD`（role=admin）。只有 admin 看得到管理主控台；
  `/admin/*` 接受 admin session 或 `X-KB-Admin-Key`。
- 本機開發預設帳號：`student/student-password`、`admin/admin-password`、admin key
  `local-admin-key`（僅限開發）。
- LLM 預設：chat `gpt-5.4-mini`、難題 `gpt-5.4`、router `gpt-5.4-mini`、max output
  tokens 4096。管理主控台「系統設定」可線上覆寫（存 `runtime_settings` 表，免重啟）。
- 真實教材在 `course-materials-md/`（git ignore，絕不入庫）；範例教材在 `sample-docs/`。
- 學員 UI 原則：不顯示診斷資訊（分數、index status、answer quality 內部欄位）；
  引用驗證失敗要優雅降級，不能毀掉整個回答。診斷一律放管理主控台。
- 除錯追蹤鏈：audit `chat.session_reported`（學員按 🚩 回報）→
  `retrieval_events.conversation_id` → `provider_call_logs.conversation_id`
  （每次 LLM 呼叫的完整 request messages 與 response）。

## 常用指令

```bash
uv sync --python 3.12 --group dev      # 安裝依賴
docker compose up -d postgres          # 啟動 DB
make migrate                           # 跑 migration
make dev                               # 啟動 app（http://localhost:8000）
make index                             # 重建索引
make worker                            # 背景 worker（概念抽取等任務需要它）
make test-unit / make test-e2e         # 單元 / e2e 測試（不需 DB）
make test-integration                  # 整合測試（需 KB_DATABASE_URL_TEST）
make lint                              # ruff + mypy
node --check app/ui/static/app.js      # 前端改動後的語法檢查
```

整合測試的本機 DB 進備（一次性）：

```bash
docker exec <postgres-container> psql -U kb -d kb \
  -c "CREATE DATABASE kb_test OWNER kb;"
docker exec <postgres-container> psql -U kb -d kb_test \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"
KB_DATABASE_URL_TEST="postgresql+psycopg://kb:kb@localhost:5432/kb_test" make test-integration
```

注意：測試一律不讀本機 `.env`（`tests/conftest.py` 將 `Settings.model_config["env_file"]`
設為 None）。需要特定設定的測試顯式傳 `Settings(...)` 參數。

## 程式碼地圖

| 區域 | 位置 |
| --- | --- |
| 設定（env, `KB_` 前綴） | `app/core/config.py` |
| Runtime 設定覆寫 | `app/runtime_settings.py`, `app/api/admin_settings.py` |
| Chat 管線 / 回報 | `app/api/chat.py` |
| Query router/guardrail | `app/answer/query_router.py` |
| 引用驗證 | `app/answer/citations.py`（slugify 正規化在此） |
| Answer provider（OpenAI） | `app/answer/providers.py` |
| LLM 呼叫紀錄 | `app/provider_telemetry.py` → `provider_call_logs` 表 |
| 檢索 | `app/retrieval/`（hybrid RRF 在 `hybrid.py`） |
| 索引 / 切塊 | `app/indexing/`（anchor slug 規則在 `citations.py`） |
| 教材內容 CRUD | `app/api/documents.py`（content GET/PUT + reindex） |
| 服務狀態 | `app/api/system_status.py` |
| 背景任務 / worker | `app/background_jobs/`, `scripts/run_background_worker.py` |
| 知識圖譜 | `app/graph/`, `app/api/graph.py` |
| 前端（單檔 vanilla JS） | `app/ui/static/app.js`, `app/ui/templates/index.html` |
| DB models / migrations | `app/models/tables.py`, `migrations/versions/` |

## 操作紀錄（重大變更）

- 2026-06: 引用驗證改為正規化比對（標題標點變體可匹配）＋部分容忍：
  有至少一個有效引用的回答不再整個降級為 cannot_confirm。
- 2026-06: 新增 LLM router/guardrail 與難度分流；擋下的問題回固定句
  「這個問題和學習無關，Let's learn together!」，決策存 `scores_json.query_route`。
- 2026-06: 新增 `runtime_settings`（migration 0014）與 `provider_call_logs`
  （migration 0015）。後者存每次 LLM 呼叫完整 request/response。
- 2026-06: 雙角色登入＋landing page；學員 UI 大幅精簡（移除診斷資訊）、
  教材閱讀器（含 mermaid 渲染）、知識圖譜詳情移右欄。
- 2026-06: 管理主控台新增：教材編輯（markdown CRUD＋reindex）、服務狀態頁、
  系統設定、LLM 呼叫紀錄表、審計日誌表格化（可排序）。
- 2026-06: Chat 工具列（清除對話／匯出 JSON／回報問題）；conversation_id 跨訊息
  延續，session 可全鏈追蹤。
- 2026-06: 預設 max output tokens 1024 → 4096。
- 已知狀態：概念抽取（圖譜）需要背景 worker 在跑，否則任務停在 queued；
  可在管理主控台「背景任務」取消。

## 安全紅線

- 不批次刪檔、不 `rm -rf`（見 AGENTS.md Repository Safety Rules）。
- `course-materials-md/`、`.env`、`backups/` 絕不 commit。
- audit metadata 不存原始密碼/金鑰（用 `fingerprint_secret()`）。
- 學員介面不暴露 admin 端點、原始 prompts 或診斷內部欄位。
