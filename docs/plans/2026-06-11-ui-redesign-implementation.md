# UI Redesign Implementation Plan (沉穩學術風)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reskin the entire app in the approved "scholarly calm" dual-theme design and restructure admin features into a console with an overview dashboard — frontend-only, zero backend changes.

**Architecture:** Rebuild `app.css` around semantic design tokens (light `:root` + `[data-theme="dark"]` + `prefers-color-scheme` fallback); restyle learner surfaces (chat/citations/inspector/login/sources) and theme the Cytoscape graph by resolving tokens in JS; move admin panels out of the learner tab row into a console shell with grouped nav and a dashboard that aggregates existing admin endpoints client-side.

**Tech Stack:** Vanilla CSS/JS/Jinja2 (no build tooling, no webfonts). Spec: `docs/plans/2026-06-11-ui-redesign-design.md`. Suites that must stay green: unit 391 / integration 124 / e2e (updated as specified).

**Conventions:**
- Python via `uv run --python 3.12 ...`; e2e: `uv run --python 3.12 pytest tests/e2e -q`
- After every JS change: `node --check app/ui/static/app.js`
- `make lint` unaffected by CSS/HTML but run before each commit anyway (catches accidental Python edits)
- Self-verification: implementers SHOULD start the app (`KB_DATABASE_URL=postgresql+psycopg://kb:kb@localhost:5432/kb uv run --python 3.12 uvicorn app.main:app --port 8050`) and eyeball with the preview/screenshot tooling when available; the local kb DB is seeded (35 docs, 124-concept graph), learner auth is open in local dev. Kill servers when done.
- **Existing ids must stay stable** unless a task explicitly renames them — e2e and app.js depend on them.

**Token naming decision (locks Task 1):** keep the EXISTING variable names used across 1,339 lines (`--bg`, `--surface`, `--surface-muted`, `--border`, `--border-strong`, `--text`, `--muted`, `--accent`, `--success`, `--warning`, `--danger`, `--radius`, `--shadow`) and change their VALUES; add new tokens alongside (`--faint`, `--accent-contrast`, `--success-bg`, `--warning-bg`, `--danger-bg`, `--user-bubble`, `--user-bubble-border`, `--surface-raised-shadow`, `--radius-sm`, `--radius-lg`, `--radius-pill`, `--font-display`, `--font-body`, `--font-mono`, `--space-1..7`). The spec's `--ink*`/`--ok`/`--warn` names map to `--text`/`--muted`/`--success`/`--warning`.

---

### Task 1: Theme foundation — tokens, typography, theme switcher

**Files:**
- Modify: `app/ui/static/app.css` (`:root` block + new `[data-theme="dark"]` + `@media` fallback + base typography)
- Modify: `app/ui/templates/index.html` (head script, `lang`, toggle button)
- Modify: `app/ui/static/app.js` (theme module)
- Test: `tests/e2e/test_ui.py`

- [ ] **Step 1: Write the failing e2e test** — append to `tests/e2e/test_ui.py` (match the file's client fixture style):

```python
def test_ui_exposes_dual_theme_wiring(client) -> None:
    page = client.get("/")
    assert 'lang="zh-Hant"' in page.text
    assert "kb-theme" in page.text  # head boot script reads localStorage("kb-theme")
    assert 'id="theme-toggle"' in page.text

    js_response = client.get("/static/app.js")
    assert "bindThemeToggle" in js_response.text
    assert "kb-theme-changed" in js_response.text

    css_response = client.get("/static/app.css")
    assert '[data-theme="dark"]' in css_response.text
    assert "--font-display" in css_response.text
```

Run: `uv run --python 3.12 pytest tests/e2e/test_ui.py::test_ui_exposes_dual_theme_wiring -v` → FAIL.

- [ ] **Step 2: Replace the `:root` block in app.css** (lines 1-17) with the full token set:

```css
:root {
  --bg: #faf7f2;
  --surface: #fffefb;
  --surface-muted: #f5f1e8;
  --border: #e3dccd;
  --border-strong: #d8cfba;
  --text: #2b2a26;
  --muted: #6b6353;
  --faint: #a39a87;
  --accent: #1a3a5c;
  --accent-strong: #142d47;
  --accent-contrast: #faf7f2;
  --success: #3c5c34;
  --success-bg: #e4ede0;
  --warning: #9a7b2e;
  --warning-bg: #f3ecd9;
  --danger: #8a3a2e;
  --danger-bg: #f3e1dd;
  --user-bubble: #e8f0e4;
  --user-bubble-border: #d4e2cc;
  --radius-sm: 7px;
  --radius: 10px;
  --radius-lg: 14px;
  --radius-pill: 999px;
  --shadow: 0 2px 8px rgb(60 50 30 / 5%);
  --shadow-raised: 0 4px 16px rgb(60 50 30 / 8%);
  --font-display: "Noto Serif TC", "Songti TC", "PMingLiU", Georgia, serif;
  --font-body: "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", -apple-system,
    "Segoe UI", sans-serif;
  --font-mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px;
  --space-5: 24px; --space-6: 32px; --space-7: 48px;
}

[data-theme="dark"] {
  --bg: #171d28;
  --surface: #1c2330;
  --surface-muted: #131823;
  --border: #2a3242;
  --border-strong: #354056;
  --text: #cfc9bc;
  --muted: #7d8597;
  --faint: #5a6272;
  --accent: #d4b876;
  --accent-strong: #e2cc94;
  --accent-contrast: #171d28;
  --success: #9fc587;
  --success-bg: rgb(140 180 120 / 12%);
  --warning: #d9b96a;
  --warning-bg: rgb(217 185 106 / 12%);
  --danger: #d98a7a;
  --danger-bg: rgb(217 138 122 / 12%);
  --user-bubble: #243240;
  --user-bubble-border: #2e3d4e;
  --shadow: 0 2px 8px rgb(0 0 0 / 25%);
  --shadow-raised: 0 4px 16px rgb(0 0 0 / 35%);
}
```

Then duplicate the dark block's CONTENTS into a media fallback so "auto" follows the OS without JS (place directly after the `[data-theme="dark"]` block):

```css
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    /* same custom-property assignments as [data-theme="dark"] — keep in sync */
  }
}
```

(Write the full property list out — do not leave the comment as the only content.)

- [ ] **Step 3: Base typography in app.css** — update the `body` rule (and any rule setting font-family) to:

```css
body {
  font-family: var(--font-body);
  font-size: 16px;
  line-height: 1.5;
  background: var(--bg);
  color: var(--text);
}
h1, h2, .workspace-header h2, .panel-title { font-family: var(--font-display); }
```

Adapt selector names to what actually exists (grep `font-family` and heading rules first). Sweep the file for hardcoded hex colors that duplicate token roles (e.g. `#fff`, `#162029`) and replace with the matching token — `grep -n "#[0-9a-fA-F]\{3,6\}" app/ui/static/app.css` and judge each (status hues map to success/warning/danger tokens; leave the graph cluster palette in app.js alone — Task 4 handles it).

- [ ] **Step 4: Head boot script + toggle button in index.html**

In `<head>`, BEFORE the stylesheet link:

```html
<script>
  (function () {
    var saved = localStorage.getItem("kb-theme");
    if (saved === "light" || saved === "dark") {
      document.documentElement.setAttribute("data-theme", saved);
    }
  })();
</script>
```

Set `<html lang="zh-Hant">`. Add the toggle next to the existing header controls (find the workbench header / account area):

```html
<button class="theme-toggle" id="theme-toggle" type="button"
        aria-label="切換深淺色主題" title="主題：自動">☀︎</button>
```

- [ ] **Step 5: Theme module in app.js** — add near the other bind* functions and call from `init()`:

```javascript
  const THEME_SEQUENCE = ["auto", "light", "dark"];
  const THEME_LABEL = { auto: "自動", light: "淺色", dark: "深色" };
  const THEME_ICON = { auto: "☀︎", light: "☀", dark: "☾" };

  function currentTheme() {
    const saved = localStorage.getItem("kb-theme");
    return saved === "light" || saved === "dark" ? saved : "auto";
  }

  function applyTheme(theme) {
    if (theme === "auto") {
      localStorage.removeItem("kb-theme");
      document.documentElement.removeAttribute("data-theme");
    } else {
      localStorage.setItem("kb-theme", theme);
      document.documentElement.setAttribute("data-theme", theme);
    }
    elements.themeToggle.textContent = THEME_ICON[theme];
    elements.themeToggle.title = `主題：${THEME_LABEL[theme]}`;
    document.dispatchEvent(new CustomEvent("kb-theme-changed"));
  }

  function bindThemeToggle() {
    elements.themeToggle.addEventListener("click", () => {
      const next =
        THEME_SEQUENCE[(THEME_SEQUENCE.indexOf(currentTheme()) + 1) % THEME_SEQUENCE.length];
      applyTheme(next);
    });
    applyTheme(currentTheme());
  }
```

Register `themeToggle: $("#theme-toggle")` in the `elements` map; call `bindThemeToggle()` in `init()`.

- [ ] **Step 6: Verify** — `node --check app/ui/static/app.js`; the new e2e test passes; FULL e2e suite passes (existing assertions may reference old CSS strings — fix only genuinely broken ones, reporting each); visual check both themes via preview if available.

- [ ] **Step 7: Commit** — `git add app/ui tests/e2e && git commit -m "feat: dual-theme design tokens and theme switcher"`

---

### Task 2: Learner chat + 引用來源 inspector restyle

**Files:**
- Modify: `app/ui/static/app.css` (chat/message/citation/inspector component rules)
- Modify: `app/ui/templates/index.html` (chat panel + inspector headings/structure tweaks)
- Modify: `app/ui/static/app.js` (trust badge text/classes, feedback row relocation, inspector source rows, graph cross-link)
- Test: `tests/e2e/test_ui.py`

- [ ] **Step 1: Read first** — the chat message rendering (`appendMessage`/answer rendering around the citation-binding code), the trust badge logic, the feedback form code, and the inspector preview helpers in app.js. Map which CSS classes they emit.

- [ ] **Step 2: e2e (failing)** — append:

```python
def test_ui_exposes_scholarly_chat_styling(client) -> None:
    css_response = client.get("/static/app.css")
    assert ".answer-card" in css_response.text
    assert ".trust-badge" in css_response.text
    assert ".citation-pill" in css_response.text
    assert ".source-row" in css_response.text

    js_response = client.get("/static/app.js")
    assert "renderFeedbackRow" in js_response.text
    assert "graph-cross-link" in js_response.text
```

- [ ] **Step 3: Restyle.** Key component CSS (adapt selectors to the real class names found in Step 1; where the JS emits generic classes, rename them in JS to the new names asserted above):

```css
.answer-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px var(--radius-lg) var(--radius-lg) var(--radius-lg);
  box-shadow: var(--shadow);
  padding: var(--space-4) var(--space-5);
  line-height: 1.75;
  max-width: 92%;
}
.user-bubble {
  background: var(--user-bubble);
  border: 1px solid var(--user-bubble-border);
  border-radius: var(--radius-lg) var(--radius-lg) 4px var(--radius-lg);
  padding: var(--space-3) var(--space-4);
  margin-left: auto;
  max-width: 70%;
}
.trust-badge {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 5px;
  font-size: 13px;
  margin-bottom: var(--space-3);
}
.trust-badge.is-ok { background: var(--success-bg); color: var(--success); border: 1px solid color-mix(in srgb, var(--success) 30%, transparent); }
.trust-badge.is-warn { background: var(--warning-bg); color: var(--warning); }
.trust-badge.is-danger { background: var(--danger-bg); color: var(--danger); }
.citation-pill {
  display: inline-block;
  min-width: 18px;
  text-align: center;
  padding: 1px 8px;
  border-radius: var(--radius-pill);
  background: var(--accent);
  color: var(--accent-contrast);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.source-row {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
  margin-top: var(--space-2);
  font-size: 13px;
  cursor: pointer;
}
.source-row.is-active { border-left: 3px solid var(--accent); border-color: var(--border-strong); }
.answer-footer {
  border-top: 1px solid var(--border);
  margin-top: var(--space-3);
  padding-top: var(--space-2);
  font-size: 13px;
  color: var(--muted);
}
```

Trust badge copy (JS): ok → `✓ 依據 N 個課程段落回答`, warn → `知識庫無法確認這個問題`, danger → `回答需要來源審查` (find the existing English badge strings and replace; keep the same decision logic).

Feedback row: extract the existing feedback controls into `renderFeedbackRow(message)` appended inside `.answer-footer` (有幫助 / 沒有幫助 / 找不到我要的 — same三 buttons/handlers as today, restyled as quiet text buttons; the expandable note/source form behavior stays).

Inspector: panel title 引用來源 (N); source rows numbered to match citation pills; clicking a pill highlights (`is-active`) the matching row and loads the existing section preview. Add the graph cross-link row: after a section preview loads, if `state.graphLoaded` and a loaded concept's sources include the previewed `source_id`, render `<button class="graph-cross-link">🗺 在知識圖譜中查看「{name}」</button>` → `activateTab("graph")` + select/centre that node (use `state.cy.$id(conceptId).select()` + `state.cy.center(node)` guarded by instance existence). Hidden when the graph isn't loaded.

- [ ] **Step 4: Verify** — node --check; new + full e2e green; preview both themes: ask a question against the seeded DB and screenshot the answer card with citations.

- [ ] **Step 5: Commit** — `git commit -m "feat: scholarly chat surfaces and citation inspector"`

---

### Task 3: Login/landing + 教材總覽 restyle

**Files:**
- Modify: `app/ui/templates/index.html` (landing shell, sources panel headings)
- Modify: `app/ui/static/app.css` (landing, sources reading-list)
- Modify: `app/ui/static/app.js` (sources list rendering classes if needed)
- Test: `tests/e2e/test_ui.py` (landing test exists — extend)

- [ ] **Step 1:** Read the landing shell markup (hidden-by-default login section) and the sources tab rendering. e2e (failing): extend the existing landing test to assert `.landing-card` and serif brand classes; add `.doc-row` assertion for sources.

- [ ] **Step 2:** Landing: centered `.landing-card` (max-width 880px, `--surface`, `--shadow-raised`, `--radius-lg`) on `--bg`; serif course title 26px; the trust strip becomes three quiet `--muted` chips; form fields restyled (16px inputs, accent submit). Sources panel: replace table chrome with `.doc-row` items — serif document title, `--muted` meta line (`N 個段落 · 狀態`), hover raises with `--shadow`; the admin-only lifecycle form stays but is visually grouped and marked 管理操作 (it MOVES to the console in Task 5 — here it just gets tokens).

- [ ] **Step 3:** Verify (e2e + preview both themes) and commit — `git commit -m "feat: scholarly landing and sources list"`

---

### Task 4: Graph theming via token resolution

**Files:**
- Modify: `app/ui/static/app.js` (graph module)
- Modify: `app/ui/static/app.css` (graph toolbar/stats tokens)
- Test: `tests/e2e/test_ui.py`

- [ ] **Step 1: e2e (failing):**

```python
def test_ui_graph_uses_theme_tokens(client) -> None:
    js_response = client.get("/static/app.js")
    assert "resolveGraphTheme" in js_response.text
    assert 'addEventListener("kb-theme-changed"' in js_response.text
```

- [ ] **Step 2: Implement.** In the graph module:

```javascript
  const CLUSTER_COLORS_LIGHT = [/* existing palette array stays */];
  const CLUSTER_COLORS_DARK = ["#7da7d9", "#9fc587", "#d9b96a", "#d98a7a", "#b89ae0",
    "#6cc6c6", "#d99e6a", "#c490c9", "#8aa7e0", "#90c9a0", "#d987a8", "#a8917a"];

  function resolveGraphTheme() {
    const styles = getComputedStyle(document.documentElement);
    const dark = document.documentElement.getAttribute("data-theme") === "dark" ||
      (!document.documentElement.getAttribute("data-theme") &&
        window.matchMedia("(prefers-color-scheme: dark)").matches);
    return {
      clusterColors: dark ? CLUSTER_COLORS_DARK : CLUSTER_COLORS_LIGHT,
      edge: styles.getPropertyValue("--border-strong").trim(),
      edgeArrow: styles.getPropertyValue("--muted").trim(),
      label: styles.getPropertyValue("--text").trim(),
      clusterBorder: styles.getPropertyValue("--faint").trim(),
      highlight: styles.getPropertyValue("--accent").trim(),
    };
  }
```

`graphElements`/`renderGraphView` consume `resolveGraphTheme()` instead of the hardcoded palette + hex literals (node label color, edge colors, cluster hull border, highlighted border). Theme reaction:

```javascript
  document.addEventListener("kb-theme-changed", () => {
    if (!state.graphLoaded) return;
    if (isTabActive("graph")) renderGraphView(state.graphView || "cluster");
    else state.graphStale = true;
  });
```

(`isTabActive` — use however the file detects the active tab; reuse the lazy-activation flow from the graph stale handling.) Toolbar/search/stats CSS rules swap any leftover hex for tokens.

- [ ] **Step 3: Verify** — node --check; e2e; preview: load graph, toggle theme, confirm re-render in both (screenshot each). Commit `feat: theme-aware knowledge graph rendering`.

---

### Task 5: Admin console shell + panel migration + shared admin key

**Files:**
- Modify: `app/ui/templates/index.html` (sidebar slim-down, console shell, panel moves)
- Modify: `app/ui/static/app.js` (console nav, applyAccessPolicy update, shared key)
- Modify: `app/ui/static/app.css` (console layout/nav)
- Test: `tests/e2e/test_ui.py`

This is the structural task — read `applyAccessPolicy`, the tab registry, and ALL `data-admin-only` markup before editing.

- [ ] **Step 1: e2e (failing):**

```python
def test_ui_admin_console_structure(client) -> None:
    page = client.get("/")
    # learner sidebar: exactly the three learner tabs remain as tabs
    assert 'id="tab-uploads"' not in page.text  # admin tabs no longer in learner tab row
    assert 'id="console-nav"' in page.text
    assert 'id="console-entry"' in page.text
    assert 'data-console-panel="uploads"' in page.text
    assert 'id="console-admin-key"' in page.text

    js_response = client.get("/static/app.js")
    assert "bindConsole" in js_response.text
    assert "sharedAdminKey" in js_response.text
```

- [ ] **Step 2: Markup restructure.** Learner sidebar keeps tabs chat/graph/sources only (sources tab loses its embedded admin lifecycle form — it moves into the console 文件生命週期 panel). Below the learner nav, a `data-admin-only` footer entry:

```html
<button class="console-entry" id="console-entry" type="button" data-admin-only>⚙ 管理主控台</button>
```

New console shell (sibling of the learner workbench, hidden by default):

```html
<div class="console" id="console" hidden>
  <nav class="console-nav" id="console-nav">
    <div class="console-brand">管理主控台</div>
    <input class="console-key" id="console-admin-key" type="password" placeholder="Admin Key" autocomplete="off" />
    <button class="console-nav-item is-active" type="button" data-console-panel="overview">📊 總覽</button>
    <div class="console-section">內容</div>
    <button class="console-nav-item" type="button" data-console-panel="uploads">📥 上傳與索引</button>
    <button class="console-nav-item" type="button" data-console-panel="documents">📄 文件生命週期</button>
    <button class="console-nav-item" type="button" data-console-panel="graph-extract">🗺 圖譜抽取</button>
    <div class="console-section">品質</div>
    <button class="console-nav-item" type="button" data-console-panel="evals">🧪 評估與回饋</button>
    <div class="console-section">維運</div>
    <button class="console-nav-item" type="button" data-console-panel="jobs">⚙️ 背景任務</button>
    <button class="console-nav-item" type="button" data-console-panel="ops">📡 Provider 用量</button>
    <button class="console-nav-item" type="button" data-console-panel="audit">🔒 審計日誌</button>
    <button class="console-back" id="console-back" type="button">← 回到課程</button>
  </nav>
  <main class="console-main" id="console-main"><!-- panels move here --></main>
</div>
```

MOVE the existing admin panel sections (uploads, ops, audit, evals + the documents lifecycle form + a jobs panel if currently embedded in uploads — read the template) into `console-main`, each wrapped `<section class="console-panel" data-console-panel-body="uploads" hidden>`. Their internal ids/forms stay byte-identical (the JS handlers keep working). Remove the per-panel admin-key `<input>`s (`#admin-key`, `#ops-admin-key`, `#audit-admin-key`, `#eval-admin-key`, `#document-admin-key`).

- [ ] **Step 3: JS.** `bindConsole()`: console-entry click → hide learner shell, show console, render overview; console-back reverses; nav items toggle `data-console-panel-body` sections (reuse/extend the tab-switch helper pattern, not a new framework). Shared key: `function sharedAdminKey() { return elements.consoleAdminKey.value.trim(); }`; replace every read of the removed per-panel key inputs (grep the element names from the `elements` map — `adminKey`, `opsAdminKey`, `auditAdminKey`, `evalAdminKey`, `documentAdminKey`) with `sharedAdminKey()`; delete the dead element registrations. `applyAccessPolicy` keeps hiding `data-admin-only` for learners (console-entry inherits it).

Console CSS: fixed dark-slate nav (per spec, BOTH themes):

```css
.console { display: flex; min-height: 100vh; background: var(--bg); }
.console-nav {
  width: 210px; flex-shrink: 0; background: #1f2a38; color: #aeb6c2;
  display: flex; flex-direction: column; gap: 2px; padding: var(--space-4) var(--space-3);
}
.console-brand { font-family: var(--font-display); color: #d4b876; font-weight: 700;
  padding: 0 var(--space-2) var(--space-3); border-bottom: 1px solid #2e3a4a; margin-bottom: var(--space-2); }
.console-nav-item { text-align: left; border: 0; background: transparent; color: inherit;
  padding: var(--space-2) var(--space-3); border-radius: var(--radius-sm); cursor: pointer; font-size: 14px; }
.console-nav-item.is-active { background: #2e3d52; color: #fff; font-weight: 600; }
.console-section { font-size: 11px; letter-spacing: .12em; color: #6b7686; padding: var(--space-3) var(--space-3) var(--space-1); }
.console-key { margin: 0 var(--space-2) var(--space-2); padding: 6px 8px; border-radius: var(--radius-sm);
  border: 1px solid #2e3a4a; background: #16202c; color: #d5dae3; font-size: 12px; }
.console-main { flex: 1; padding: var(--space-5) var(--space-6); overflow-y: auto; }
.console-back { margin-top: auto; border: 0; background: transparent; color: #6b7686; text-align: left;
  padding: var(--space-2) var(--space-3); cursor: pointer; }
```

- [ ] **Step 4: Verify hard.** node --check; new + FULL e2e (expect several existing assertions on admin markup to need updating — the panels moved but ids survive; tab-row assertions change; itemize every updated assertion); manual preview: learner view shows 3 tabs; entering the console with the dev admin key, click through every panel and exercise one real action per panel (refresh jobs, load audit events) against the local app to prove handlers survived the move.

- [ ] **Step 5: Commit** — `git commit -m "feat: admin console shell with shared key"`

---

### Task 6: Console 總覽 dashboard + 圖譜抽取 panel

**Files:**
- Modify: `app/ui/templates/index.html` (overview + graph-extract panel bodies)
- Modify: `app/ui/static/app.js` (dashboard module)
- Modify: `app/ui/static/app.css` (stat cards, activity list)
- Test: `tests/e2e/test_ui.py`

- [ ] **Step 1: e2e (failing):**

```python
def test_ui_console_dashboard_wiring(client) -> None:
    page = client.get("/")
    assert 'data-console-panel-body="overview"' in page.text
    assert 'id="stat-index"' in page.text and 'id="stat-graph"' in page.text
    assert 'id="stat-jobs"' in page.text and 'id="stat-tokens"' in page.text
    assert 'id="recent-activity"' in page.text
    assert 'id="trigger-graph-extract"' in page.text

    js_response = client.get("/static/app.js")
    assert "loadConsoleOverview" in js_response.text
    assert "/admin/jobs/runtime" in js_response.text
```

- [ ] **Step 2: Markup** — overview panel: four `.stat-card`s (索引文件 #stat-index / 知識圖譜 #stat-graph / 背景任務 #stat-jobs / 今日 Token #stat-tokens, each a serif `.stat-number` + `.stat-note`) + `.activity-card` with `#recent-activity` list. Graph-extract panel: explainer line, `#trigger-graph-extract` button (觸發概念抽取), `#graph-extract-status` for the latest extraction job summary.

- [ ] **Step 3: JS `loadConsoleOverview()`** — called on console entry and 總覽 activation; four independent fetches, each `try/catch` → "—" on failure:
  - `/index/status` (existing endpoint; read its actual shape from `app/api/indexing.py`) → 文件數 + 索引狀態 note
  - `/graph` → `stats.concept_count` / `cluster_count`
  - `/admin/jobs/runtime` with `X-KB-Admin-Key: sharedAdminKey()` → queue depth + worker heartbeat note (✓ / 過期)
  - `/metrics` with admin key → today's provider tokens vs budget if present (read `app/api/health.py` or wherever /metrics lives for the JSON shape; degrade gracefully)
  - `/admin/jobs?limit=8` → `#recent-activity` rows (`HH:MM · task_type · status`, failures in `--danger`)

  Graph-extract panel: button POSTs `/graph/extract` with the shared key → status line shows job id; a refresh button loads the latest `concept_extraction` job from `/admin/jobs` and prints its result stats (documents_extracted, concepts_created/merged, provider_calls).

- [ ] **Step 4: Verify** — node --check; e2e; manual: dashboard renders real numbers against the seeded DB (35 docs / 124 concepts / worker 心跳 likely 過期 locally — fine, proves degradation), trigger extraction WITHOUT running the worker (job queues; status shows queued) — do NOT run the worker here. Commit `feat: console overview dashboard and graph extraction panel`.

---

### Task 7: Responsive, motion, a11y pass

**Files:**
- Modify: `app/ui/static/app.css`
- Test: `tests/e2e/test_ui.py`

- [ ] **Step 1: e2e (failing):**

```python
def test_ui_motion_and_a11y_rules(client) -> None:
    css_response = client.get("/static/app.css")
    assert "prefers-reduced-motion" in css_response.text
    assert ":focus-visible" in css_response.text
```

- [ ] **Step 2:** Re-tune the two existing breakpoints (1120px / 760px) for the new spacing (sidebar collapses to icon row <760px; console-nav becomes top bar <760px). Motion: `transition: background-color .15s ease-out, border-color .15s ease-out, box-shadow .2s ease-out;` on interactive components; tab-activation fade-slide:

```css
.workspace-panel:not([hidden]) { animation: panel-in .2s ease-out; }
@keyframes panel-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important; transition-duration: .01ms !important; }
}
```

Global focus ring: `:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }` (verify visible in both themes). Contrast audit: check every `--muted`/`--faint`-on-`--bg`/`--surface` pair and the badge combinations against WCAG AA (4.5:1 body, 3:1 large) — adjust token values if any pair fails, and note adjustments in the commit message.

- [ ] **Step 3: Verify + commit** — `git commit -m "feat: responsive, motion, and accessibility polish"`

---

### Task 8: Full verification + visual acceptance + docs

- [ ] **Step 1: Suites** — unit (391) / integration (124, KB_DATABASE_URL_TEST) / e2e (all, including every new test) / `make lint` / `docker build -t kb-check .`.

- [ ] **Step 2: Visual acceptance (operator)** — app on seeded DB; for EACH theme (light, dark): login page, chat with a real answer + citations + feedback row, graph all three views (toggle theme while graph open — re-render proof), 教材總覽, console overview + uploads + jobs panels; responsive spot-check at 760px; reduced-motion via OS setting or devtools emulation. Capture screenshots to `tmp/ui-acceptance/` (gitignored) and list them in the report.

- [ ] **Step 3: Docs** — README: workbench description gains 主題切換 + 管理主控台 mention; AGENTS.md UI bullet updated (three-pane learner workbench + separate admin console + dual theme); no deploy.md changes (frontend only ships with the app).

- [ ] **Step 4: Commit** — `git add README.md AGENTS.md && git commit -m "docs: document scholarly UI and admin console"`

---

## Completion checklist (gates from the spec)

- [ ] Dual theme everywhere incl. console content area; no flash on load; auto follows OS
- [ ] Zero backend changes (`git diff --stat` touches only app/ui, tests/e2e, README, AGENTS.md)
- [ ] All learner flows work unchanged (chat/citations/feedback/graph/sources/login)
- [ ] Every admin handler still works inside the console (one real action per panel verified)
- [ ] e2e suite green with new assertions; unit/integration untouched and green
- [ ] WCAG AA contrast verified for token pairs in both themes
- [ ] Visual acceptance screenshots captured for both themes
