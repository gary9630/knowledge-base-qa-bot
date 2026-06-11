# UI Redesign Design — 沉穩學術風 (Scholarly Calm)

Date: 2026-06-11
Status: Approved
Scope: Sub-project 3 of 4 (RAG context expansion → knowledge graph → **UI redesign** →
production readiness). Frontend-only: no backend/API changes, no build tooling, no
framework. Vanilla CSS/JS/Jinja2 stays.

## Problem

The current UI is functional but visually generic: 12–14px type, tight spacing,
1px borders on every card, near-zero elevation/motion, no dark mode, corporate
blue-gray palette. It reads as a 2015-era internal tool, not a product course
learners would trust. Admin features sit as tabs beside learner tabs in one
sidebar, mixing two very different audiences in one cramped IA.

## Decisions (user-confirmed)

1. Visual direction: **沉穩學術風** — warm paper surfaces, serif display headings,
   ink-blue accent, generous whitespace ("a well-bound course reader").
   (Alternatives presented in browser mockups: modern-SaaS, focused-dark; rejected.)
2. **Dual theme from day one**: light (default) + dark "深墨藍夜間閱讀", manual
   toggle + `prefers-color-scheme` default, persisted; applies to ALL surfaces
   including the admin console.
3. **Full scope including admin IA restructure**: learner surfaces fully
   redesigned; admin features move out of the learner tab row into a separate
   console layout with grouped navigation and an overview dashboard.
4. Mockups approved (browser session `.superpowers/brainstorm/16622-1781165292`):
   learner chat (light), night reading mode, admin console overview.

## Design

### 1. Design tokens (CSS variables, dual theme)

`app/ui/static/app.css` is rebuilt around semantic tokens defined on `:root`
(light) and `[data-theme="dark"]` (dark). Components reference ONLY semantic
tokens — no raw hex in component rules.

Light (warm paper):
- `--bg: #faf7f2` (page), `--surface: #fffefb` (cards), `--surface-sunken: #f5f1e8`
  (sidebars/inspector), `--border: #e3dccd`, `--border-strong: #d8cfba`
- `--ink: #2b2a26` (text), `--ink-muted: #6b6353`, `--ink-faint: #a39a87`
- `--accent: #1a3a5c` (ink blue), `--accent-contrast: #faf7f2`
- `--ok: #3c5c34` / `--ok-bg: #e4ede0`; `--warn: #9a7b2e` / `--warn-bg: #f3ecd9`;
  `--danger: #8a3a2e` / `--danger-bg: #f3e1dd`
- `--user-bubble: #e8f0e4`, border `#d4e2cc`
- `--shadow-soft: 0 2px 8px rgba(60,50,30,.05)`, `--shadow-raised: 0 4px 16px rgba(60,50,30,.08)`

Dark (night reading, NOT pure black):
- `--bg: #171d28`, `--surface: #1c2330`, `--surface-sunken: #131823`,
  `--border: #2a3242`, `--border-strong: #354056`
- `--ink: #cfc9bc`, `--ink-muted: #7d8597`, `--ink-faint: #5a6272`
- `--accent: #d4b876` (warm gold), `--accent-contrast: #171d28`
- status colors desaturated for dark (`--ok: #9fc587` on translucent bg, etc.)
- `--user-bubble: #243240`, border `#2e3d4e`

Spacing scale: 4/8/12/16/24/32/48 as `--space-1..7`. Radii: `--radius-sm: 7px`,
`--radius: 10px`, `--radius-lg: 14px`, `--radius-pill: 999px`.

### 2. Typography

- Display/headings: `--font-display: "Noto Serif TC", "Songti TC", "PMingLiU",
  Georgia, serif` — used for h1/h2, brand block, stat numbers, panel titles.
- Body/UI: `--font-body: "Noto Sans TC", "PingFang TC", "Microsoft JhengHei",
  -apple-system, "Segoe UI", sans-serif`.
- Code/IDs: `--font-mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace`.
- NO webfont files are shipped or fetched: system stacks only (zero bytes, no
  external dependency, works offline in Docker). Noto names lead the stacks so
  systems that have them use them.
- Type scale: base 16px; `--text-sm: 13px`, `--text-xs: 11.5px`, h2 22px,
  h1/brand 26px, stat numbers 28px serif. Line-height 1.75 for answer prose,
  1.5 elsewhere. `lang="zh-Hant"` set on `<html>`.

### 3. Theme switching mechanism

- `data-theme="light" | "dark"` on `<html>`; absence = follow
  `prefers-color-scheme` via a `@media` block that mirrors the dark token set.
- Toggle button (☀/☾) in the workbench header; three-state cycle:
  auto → light → dark. Persisted in `localStorage("kb-theme")`; applied by an
  inline `<head>` script before first paint (no flash).
- **Cytoscape graph**: canvas styles can't read CSS variables. The graph module
  resolves needed token values via `getComputedStyle(document.documentElement)`
  when building the style array, and the theme toggle dispatches a
  `kb-theme-changed` event; the graph re-renders (existing `renderGraphView`)
  when visible, or marks itself stale (existing `graphStale` flow) when hidden.
  Cluster color palette gets a dark-mode variant (same hues, adjusted
  lightness), chosen by current theme at render time.

### 4. Learner surfaces (full redesign, markup mostly preserved)

- **Workbench shell**: 3-pane layout kept (sidebar / main / inspector).
  Sidebar = `--surface-sunken` with serif brand block; learner nav reduces to
  exactly 問答 / 知識圖譜 / 教材總覽 + account/logout footer. ALL admin tabs
  leave this sidebar (see §5).
- **Chat**: user bubbles right-aligned green-tinted; assistant answers as paper
  cards (`--surface`, `--shadow-soft`, 14px radius with one squared corner);
  trust badge row above answer text (依據 N 個課程段落回答 / 無法確認 / 需要
  審查 → ok/warn/danger token colors); inline citations restyled as ink-blue
  pill footnote numbers (gold in dark); answer footer gains the feedback row
  (有幫助 / 沒有幫助 / 找不到 — wired to the EXISTING feedback endpoints and
  JS handlers, restyled and relocated only). Streaming keeps the existing
  token-append behavior with a subtle caret pulse.
- **Right inspector** becomes "引用來源" panel: numbered source rows (active
  row gets `--accent` left bar), click → existing section preview below; plus
  a cross-link row "在知識圖譜中查看「{concept}」" shown when the previewed
  section maps to a graph concept (client-side: match section source_id against
  loaded graph concept sources if the graph has been loaded; hidden otherwise —
  no new API).
- **Knowledge graph tab**: toolbar/buttons/stats line restyled with tokens;
  cytoscape node/edge/hull colors from resolved tokens per §3. Three views,
  collapse, search behavior unchanged.
- **教材總覽 (sources)**: document list as a reading-list (serif document
  titles, section counts, status as quiet text instead of table chrome).
- **Login/landing**: centered paper card on `--bg`, serif course title,
  trust strip restyled; same form fields/flow.
- **Responsive**: keep existing 1120px/760px breakpoints, re-tuned spacing;
  inspector collapses below content as today.
- **Motion**: 150–200ms ease-out transitions on hover/panel switches; a single
  fade-slide (8px) on tab activation; `prefers-reduced-motion` respected
  globally (transitions off).

### 5. Admin console (IA restructure, frontend-only)

- Admin features move to a **console layout** inside the same SPA: when an
  admin key is configured (existing `applyAccessPolicy` flow), the sidebar
  footer shows 管理主控台 entry; activating it swaps the learner shell for the
  console shell (dark slate sidebar `#1f2a38` in BOTH themes, content area
  follows the active theme).
- Console nav groups: 總覽 | 內容 (上傳與索引 / 文件生命週期 / 圖譜抽取) |
  品質 (評估與回饋) | 維運 (背景任務 / Provider 用量 / 審計日誌).
- **總覽 dashboard** (new panel, client-side aggregation of EXISTING admin
  endpoints — zero backend changes): four stat cards (索引文件數+狀態 from
  `/index/status`; 圖譜概念/主題數 from `/graph`; queue depth + worker
  heartbeat from `/admin/jobs/runtime`; today's token usage vs budget from
  `/metrics`) + 最近活動 list (latest jobs from `/admin/jobs`). Cards degrade
  to "—" on fetch errors.
- Existing admin panels (uploads, documents, evals, ops, audit, jobs) keep
  their current forms/tables/JS handlers, re-skinned with tokens and placed
  under the new nav. 圖譜抽取 = a small panel exposing the existing
  `POST /graph/extract` trigger + latest extraction job stats from
  `/admin/jobs` (filter task_type) — currently this trigger has no UI.
- Admin key entry: one console-level key field (stored in the existing JS
  state) replacing the per-panel repeated key inputs; panels read the shared
  key. (Pure JS refactor; backend auth unchanged.)

### 6. File/code structure

- `app/ui/static/app.css` rewritten (~1,400 lines → tokens + components,
  organized: tokens / base / layout / learner components / console / graph /
  responsive / motion). One file, no preprocessor.
- `app/ui/templates/index.html`: learner sidebar slimmed; console shell +
  dashboard markup added; admin panels move under console containers; theme
  toggle + head script added.
- `app/ui/static/app.js`: theme module (~60 lines), console nav module
  (reusing the existing tab-switching helper), dashboard fetch/render
  (~120 lines), shared admin-key refactor, graph token-resolution change.
  Existing handlers/endpoints untouched otherwise.
- Login template (landing shell within index.html) restyled in place.

### 7. Testing & acceptance

- e2e (`tests/e2e/test_ui.py`): update string assertions — theme toggle +
  head script present; learner sidebar contains exactly the 3 learner tabs
  (no admin tab ids); console markup ids (`console-nav`, `panel-console-overview`
  etc.); dashboard JS wiring (`/admin/jobs/runtime` fetch in app.js);
  data-theme default handling. Existing graph/chat assertions stay stable
  (ids preserved).
- Unit/integration suites: unaffected (no backend changes) — must stay green
  as the regression gate (unit 391 / integration 124).
- Visual acceptance (operator step): app + seeded data, browser pass over both
  themes × (login, chat with citations, graph 3 views, sources, console
  overview + 2 admin panels), responsive spot-check at 760px, reduced-motion
  check. Screenshots archived for before/after comparison in the PR.
- A11y gates: visible focus rings on all interactive elements in both themes;
  WCAG AA contrast for text tokens (verify ink/bg pairs); `aria-pressed` kept
  on view toggles; feedback/citation buttons keep accessible names.

## Out of scope

Backend/API changes of any kind; build tooling/bundlers; webfont files; admin
feature additions beyond the dashboard aggregation and graph-extract trigger
panel; learner-facing feature changes (chat/graph behavior identical); the
production-readiness items (sub-project 4).
