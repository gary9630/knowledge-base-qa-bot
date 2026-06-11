# Handoff — Production Readiness（Sub-project 4 of 4）

寫給接手的新 session。前三個 sub-project 已完成並收進 PR（見下方連結）；這份文件給你開始
第四個、也是最後一個 sub-project 所需的全部 context。

## 專案現況（2026-06-12）

FastAPI + Postgres/pgvector 的課程知識庫 QA 助理，目標是給課程學員試用的
production-level web app。原始的四個 sub-project 分解（使用者已核可順序）：

1. ✅ **RAG context expansion** — tiktoken 分詞、RRF fusion、full-section + ±1 鄰近
   section 的 context assembly。實測 retrieval_recall 0.56→0.92、top1_hit 0.27→0.77。
2. ✅ **Knowledge graph** — 取代舊 mindmap：124 概念 / 16 主題叢 / 174 edges（策展種子
   資料）、三視角 Cytoscape 前端、增量 LLM 抽取 pipeline（index rebuild 後自動鏈接）。
3. ✅ **UI redesign** — 沉穩學術風雙主題（淺/深/auto）、學員面全面重塑、管理主控台
   （總覽儀表板 + 單一共用 admin key）、WCAG AA 對比達標。
4. ⏳ **Production readiness** — 本文件的主題，尚未開始。

PR（前三個 workstream，157 commits）：見 PR 描述與 per-task 驗收數據。
Branch: `codex/hybrid-kb-qa-bot` → main。

## Sub-project 4 的已知範圍（最初評估時識別的缺口）

依重要性排序（學員試用前的阻塞項在前）：

1. **多學員帳號**。現況是「一組共用帳密」（`KB_PLATFORM_USERNAME`/`PASSWORD`），無註冊、
   無 per-learner 識別。試用需要至少：邀請碼制或預建帳號清單、per-learner session、
   （也許）對話歷史隔離 — 現在 `conversations` 表沒有 user 欄位，所有人共享。
   完整 RBAC 在原始設計中「intentionally deferred」— 不要做過頭。
2. **HTTPS / 部署方案**。目前只有 docker-compose（port 8000 直出）+「假設外部處理 TLS」。
   需要：reverse proxy 配置（Caddy/nginx）、目標環境決定（單機 VM？雲？使用者沒說過 —
   要問）、部署 runbook 更新。
3. **監控告警**。metrics 只有 in-memory（`/metrics`），worker 掛掉沒人知道。最小可行：
   worker heartbeat 告警 + provider budget 告警 +（也許）uptime 監控。原始設計明言
   Prometheus/OTel deferred until traffic requires it — 找輕量做法。
4. **其他 deferred 項**（見 AGENTS.md「Production Hardening Backlog」）：物件儲存
   （現在本地 filesystem + volume）、DB 備援、CI/CD 部署自動化。按試用規模判斷取捨。

## 工作方式（前三個 sub-project 的既定流程，請沿用）

1. `superpowers:brainstorming` skill：先探索 → 逐題釐清（使用者偏好選擇題）→ 2-3 方案
   含推薦 → 分節呈現設計 → 寫 spec 到 `docs/plans/YYYY-MM-DD-<topic>-design.md`（repo
   慣例，不是 skill 預設路徑）→ commit → 使用者過目。
2. `superpowers:writing-plans` skill：實作計畫存 `docs/plans/YYYY-MM-DD-<topic>-implementation.md`，
   bite-sized TDD tasks、完整程式碼、精確指令。
3. `superpowers:subagent-driven-development`：每 task 全新 subagent（機械性任務用
   sonnet、需判斷的用預設模型）→ spec review → quality review → fixer。Reviewer 要求
   獨立驗證（跑測試、對抗性探測、UI 工作要實際截圖）。
4. 完成後 final review + completion notes 寫進 plan 文件。

注意：使用者全程用繁體中文溝通；對話、文件、UI 文案都是 zh-TW。

## 環境備忘（會踩的坑）

- Python 一律 `uv run --python 3.12 ...`（untracked `.python-version` 釘 3.11.9，裸跑會炸）
- `.env` 的 `KB_DATABASE_URL` 指向 docker 內部主機名 `postgres` — 從 host 跑任何指令要
  覆寫 `KB_DATABASE_URL=postgresql+psycopg://kb:kb@localhost:5432/kb`
- `.env` 預設 fake providers；要真實 OpenAI 時 per-command 覆寫 `KB_EMBEDDING_PROVIDER=openai`
  `KB_ANSWER_PROVIDER=openai`（`OPENAI_API_KEY` 已在 .env，pydantic 會讀）
- 測試：unit 391 / integration 124（要 `KB_DATABASE_URL_TEST=postgresql+psycopg://kb:kb@localhost:5432/kb_test`）
  / e2e 21+4skip；`make lint` = ruff + mypy strict（tmp/ 留 .py 檔會弄壞 mypy — 用完即刪）
- 本地 dev：admin key `local-admin-key`、學員帳密 `student`/`student-password`
- `course-materials-md/`（真實課程教材）絕不進 git；`tmp/`、`.DS_Store` 已 gitignore
- macOS 無 `timeout` 指令；`sed` 被 alias 到不存在的 gsed — 用 `head`/`grep` 替代
- 部署這個 branch 需要：`make migrate`（0011 + 0012）→ 全量 reindex（重新 chunk + embed）→
  `make graph-seed`（一次性）→ 調高 `KB_PROVIDER_BUDGET_*`（input tokens 約 4-5×）—
  細節在 `ops/deploy.md`

## 關鍵文件

- 設計/計畫/完成紀錄（全部在 `docs/plans/`，依日期排序）：
  - `2026-06-11-rag-context-expansion-{design,implementation}.md`（implementation 尾部有
    eval before/after completion notes）
  - `2026-06-11-knowledge-graph-{design,implementation}.md` + `2026-06-11-concept-graph-seed.json`
  - `2026-06-11-ui-redesign-{design,implementation}.md`
- `AGENTS.md` — 專案快照、指令、Production Hardening Backlog（sub-project 4 的起點）
- `ops/deploy.md`、`ops/live-answer-acceptance.md`、`ops/backup-restore.md`
- 原始需求討論：`project-ideas.md`（untracked，64KB 歷史文件，跳著看）

## 未結事項（不阻塞，但別重複發現）

- 負向問題不會被拒答（5/5 negative eval cases 錯判 can_answer）— retrieval threshold
  校準問題，已有 background task chip；production 試用前值得做
- Eval runner 的 threshold (0.10) 與 API (0.05) 不一致 — 有 chip
- 知識圖譜「叢集視角」cose layout 在 124 節點時爆炸成微縮圖 — 已有 chip（radial/order
  視角正常，不阻塞）
- `app/api/sources.py` 的 section 排序用 created_at（應改 position）— 有 chip
- Provider telemetry 在 worker process 中只進 job result_json，不進 budget guardrails
  （API process 的 in-memory metrics 看不到 worker 的用量）— 設計已知限制，alerting
  設計時要記得
