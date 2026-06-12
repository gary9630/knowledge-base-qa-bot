(function () {
  const state = {
    documents: [],
    graph: {
      clusters: [],
      nodes: [],
      edges: [],
      stats: {
        concept_count: 0,
        cluster_count: 0,
        edge_count: 0,
        extracted_at: null,
      },
    },
    graphLoaded: false,
    graphStale: false,
    graphView: "cluster",
    graphConceptDetail: null,
    // concept id -> array of source_ids, filled lazily by findConceptForSource.
    conceptSourceCache: new Map(),
    collapsedClusters: new Set(),
    cy: null,
    importJobs: [],
    backgroundJobs: [],
    workerRuntime: null,
    providerObservability: null,
    adminDocuments: [],
    auditEvents: [],
    evalCases: [],
    evalRun: null,
    evalReport: null,
    feedbackItems: [],
    selectedSources: [],
    chatBusy: false,
    // 持續同一個對話：done 事件回傳的 conversation_id 會帶到後續訊息，
    // 讓整個 session 可以在 DB 端追蹤（retrieval_events / provider_call_logs）。
    conversationId: null,
    transcript: [],
    auth: {
      authRequired: false,
      authenticated: true,
      username: null,
      role: null,
      csrfToken: null,
    },
    runtimeSettings: null,
  };

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));

  const elements = {
    tabs: $$("[data-tab]"),
    panels: $$("[data-panel]"),
    chatForm: $("#chat-form"),
    chatQuery: $("#chat-query"),
    chatLog: $("#chat-log"),
    chatEmptyState: $("#chat-empty-state"),
    chatComposerStatus: $("#chat-composer-status"),
    chatSubmit: $("#chat-submit"),
    learnerChatStatus: $("#learner-chat-status"),
    chatClear: $("#chat-clear"),
    chatExport: $("#chat-export"),
    chatReport: $("#chat-report"),
    samplePrompts: $$("[data-sample-prompt]"),
    selectedSources: $("#answer-sources"),
    selectedSourceCount: $("#selected-source-count"),
    citationDisclosure: $("#citation-disclosure"),
    markdownPreview: $("#markdown-preview"),
    previewSourceMeta: $("#preview-source-meta"),
    sourceTable: $("#source-table"),
    sourceReader: $("#source-reader"),
    sourceReaderBack: $("#source-reader-back"),
    sourceReaderBody: $("#source-reader-body"),
    refreshDocuments: $("#refresh-documents"),
    adminDocuments: $("#admin-documents"),
    graphCanvas: $("#graph-canvas"),
    graphEmpty: $("#graph-empty"),
    graphStats: $("#graph-stats"),
    graphSearch: $("#graph-search"),
    loadGraph: $("#load-graph"),
    graphViewCluster: $("#graph-view-cluster"),
    graphViewRadial: $("#graph-view-radial"),
    graphViewOrder: $("#graph-view-order"),
    refreshSources: $("#refresh-sources"),
    uploadForm: $("#upload-form"),
    auditEventType: $("#audit-event-type"),
    auditOutcome: $("#audit-outcome"),
    auditActorType: $("#audit-actor-type"),
    auditLimit: $("#audit-limit"),
    refreshAudit: $("#refresh-audit"),
    auditEvents: $("#audit-events"),
    uploadFile: $("#upload-file"),
    refreshImports: $("#refresh-imports"),
    importDiagnosticsSummary: $("#import-diagnostics-summary"),
    importJobs: $("#import-jobs"),
    rebuildIndex: $("#rebuild-index"),
    queueIndexJob: $("#queue-index-job"),
    recoverStaleJobs: $("#recover-stale-jobs"),
    refreshBackgroundJobs: $("#refresh-background-jobs"),
    backgroundJobSummary: $("#background-job-summary"),
    backgroundJobStatusFilter: $("#background-job-status-filter"),
    backgroundJobLimit: $("#background-job-limit"),
    workerRuntime: $("#worker-runtime"),
    backgroundJobs: $("#background-jobs"),
    refreshProviderObservability: $("#refresh-provider-observability"),
    providerSummary: $("#provider-summary"),
    providerBudget: $("#provider-budget"),
    providerUsage: $("#provider-usage"),
    providerLatestCalls: $("#provider-latest-calls"),
    providerTraces: $("#provider-traces"),
    operationLog: $("#operation-log"),
    evalForm: $("#eval-form"),
    evalName: $("#eval-name"),
    evalQuery: $("#eval-query"),
    evalDecision: $("#eval-decision"),
    evalSources: $("#eval-sources"),
    evalTags: $("#eval-tags"),
    evalCases: $("#eval-cases"),
    evalResults: $("#eval-results"),
    evalSummary: $("#eval-summary"),
    evalStatus: $("#eval-status"),
    evalReport: $("#eval-report"),
    evalRecentRuns: $("#eval-recent-runs"),
    evalWorstCases: $("#eval-worst-cases"),
    feedbackPromotions: $("#feedback-promotions"),
    refreshEvals: $("#refresh-evals"),
    seedEvals: $("#seed-evals"),
    runEvals: $("#run-evals"),
    platformLogin: $("#platform-login"),
    platformLoginForm: $("#platform-login-form"),
    platformUsername: $("#platform-username"),
    platformPassword: $("#platform-password"),
    platformAuthStatus: $("#platform-auth-status"),
    platformLogout: $("#platform-logout"),
    landingLoginOpen: $("#landing-login-open"),
    landingCtaLogin: $("#landing-cta-login"),
    landingLoginOverlay: $("#landing-login-overlay"),
    landingLoginClose: $("#landing-login-close"),
    themeToggle: $("#theme-toggle"),
    workbench: $("[data-app]"),
    adminOnlySurfaces: $$("[data-admin-only]"),
    console: $("#console"),
    consoleEntry: $("#console-entry"),
    consoleBack: $("#console-back"),
    consoleAdminKey: $("#console-admin-key"),
    consoleNavItems: $$("[data-console-panel]"),
    consolePanels: $$("[data-console-panel-body]"),
    refreshOverview: $("#refresh-overview"),
    statIndex: $("#stat-index"),
    statGraph: $("#stat-graph"),
    statJobs: $("#stat-jobs"),
    statTokens: $("#stat-tokens"),
    recentActivity: $("#recent-activity"),
    triggerGraphExtract: $("#trigger-graph-extract"),
    refreshGraphExtract: $("#refresh-graph-extract"),
    graphExtractStatus: $("#graph-extract-status"),
    runtimeSettingsForm: $("#runtime-settings-form"),
    refreshRuntimeSettings: $("#refresh-runtime-settings"),
    resetRuntimeSettings: $("#reset-runtime-settings"),
    runtimeSettingsStatus: $("#runtime-settings-status"),
    refreshEditorDocuments: $("#refresh-editor-documents"),
    editorDocumentSelect: $("#editor-document-select"),
    editorLoadContent: $("#editor-load-content"),
    editorContent: $("#editor-content"),
    editorSaveContent: $("#editor-save-content"),
    editorNewFilename: $("#editor-new-filename"),
    editorNewContent: $("#editor-new-content"),
    editorCreateDocument: $("#editor-create-document"),
    editorStatus: $("#editor-status"),
    refreshHealth: $("#refresh-health"),
    healthSummary: $("#health-summary"),
    healthChecks: $("#health-checks"),
    providerLogs: $("#provider-logs"),
    refreshProviderLogs: $("#refresh-provider-logs"),
  };

  function init() {
    bindAuth();
    bindTabs();
    bindChat();
    bindSamplePrompts();
    bindSources();
    bindGraph();
    bindAdmin();
    bindEvals();
    bindConsole();
    bindThemeToggle();
    refreshAuthSession();
  }

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

  function bindAuth() {
    elements.platformLoginForm.addEventListener("submit", loginPlatform);
    elements.platformLogout.addEventListener("click", logoutPlatform);
    elements.landingLoginOpen.addEventListener("click", openLoginOverlay);
    elements.landingCtaLogin.addEventListener("click", openLoginOverlay);
    elements.landingLoginClose.addEventListener("click", closeLoginOverlay);
    elements.landingLoginOverlay.addEventListener("click", (event) => {
      if (event.target === elements.landingLoginOverlay) {
        closeLoginOverlay();
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !elements.landingLoginOverlay.hidden) {
        closeLoginOverlay();
      }
    });
  }

  function openLoginOverlay() {
    elements.landingLoginOverlay.hidden = false;
    elements.platformUsername.focus();
  }

  function closeLoginOverlay() {
    elements.landingLoginOverlay.hidden = true;
  }

  async function refreshAuthSession() {
    try {
      const payload = await getJsonWithHeaders("/auth/session", authHeaders());
      setAuthState(payload);
    } catch (error) {
      setAuthState({
        auth_required: true,
        authenticated: false,
        username: null,
        role: null,
        csrf_token: null,
      });
      elements.platformAuthStatus.textContent = `Auth unavailable: ${errorMessage(error)}`;
    }
  }

  async function loginPlatform(event) {
    event.preventDefault();
    const username = elements.platformUsername.value.trim();
    const password = elements.platformPassword.value;
    if (!username || !password) {
      elements.platformAuthStatus.textContent = "Username and password are required.";
      return;
    }

    try {
      const response = await fetch("/auth/login", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ username, password }),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const payload = await response.json();
      elements.platformPassword.value = "";
      setAuthState(payload);
    } catch (error) {
      elements.platformAuthStatus.textContent = errorMessage(error);
    }
  }

  async function logoutPlatform() {
    try {
      const response = await fetch("/auth/logout", {
        method: "POST",
        credentials: "same-origin",
        headers: authHeaders(true),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const payload = await response.json();
      setAuthState(payload);
    } catch (error) {
      elements.platformAuthStatus.textContent = `Logout failed: ${errorMessage(error)}`;
    }
  }

  function setAuthState(payload) {
    state.auth = {
      authRequired: Boolean(payload.auth_required),
      authenticated: Boolean(payload.authenticated),
      username: payload.username || null,
      role: payload.role || null,
      csrfToken: payload.csrf_token || null,
    };

    const blocked = state.auth.authRequired && !state.auth.authenticated;
    if (blocked) {
      closeConsole();
    } else {
      closeLoginOverlay();
    }
    elements.platformLogin.hidden = !blocked;
    elements.workbench.classList.toggle("is-auth-blocked", blocked);
    elements.platformLogout.hidden = !state.auth.authRequired || !state.auth.authenticated;
    applyAccessPolicy();
    elements.platformAuthStatus.textContent = state.auth.authenticated
      ? `已登入${state.auth.username ? `：${state.auth.username}` : ""}。`
      : "請以課程帳號登入以繼續使用。";

    if (!blocked) {
      refreshLearnerContext();
    }
  }

  function bindTabs() {
    elements.tabs.forEach((tab) => {
      tab.addEventListener("click", () => activateTab(tab.dataset.tab));
      tab.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
          return;
        }

        event.preventDefault();
        const nextTab = nextTabForKey(tab, event.key);
        activateTab(nextTab.dataset.tab);
        nextTab.focus();
      });
    });
  }

  function activateTab(tabName) {
    if (!tabIsAvailable(tabName)) {
      return;
    }

    elements.tabs.forEach((tab) => {
      const selected = tab.dataset.tab === tabName;
      tab.classList.toggle("is-active", selected);
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });

    elements.panels.forEach((panel) => {
      const selected = panel.dataset.panel === tabName;
      panel.classList.toggle("is-active", selected);
      panel.hidden = !selected;
    });

    if (tabName === "graph") {
      if (state.graphStale || !state.graphLoaded) {
        loadGraph();
      } else if (state.cy) {
        state.cy.resize();
        state.cy.fit();
      }
    }
  }

  function nextTabForKey(currentTab, key) {
    const tabs = availableTabs();
    if (tabs.length === 0) {
      return currentTab;
    }
    const currentIndex = Math.max(0, tabs.indexOf(currentTab));
    if (key === "Home") {
      return tabs[0];
    }
    if (key === "End") {
      return tabs[tabs.length - 1];
    }

    const offset = key === "ArrowRight" ? 1 : -1;
    const nextIndex = (currentIndex + offset + tabs.length) % tabs.length;
    return tabs[nextIndex];
  }

  function activeTabName() {
    const activeTab = elements.tabs.find((tab) => tab.classList.contains("is-active"));
    return activeTab?.dataset.tab || "chat";
  }

  function availableTabs() {
    return elements.tabs.filter((tab) => tabIsAvailable(tab.dataset.tab));
  }

  function tabIsAvailable(tabName) {
    const tab = elements.tabs.find((candidate) => candidate.dataset.tab === tabName);
    if (!tab) {
      return false;
    }
    return !(isRestrictedLearner() && tab.hasAttribute("data-admin-only"));
  }

  function isRestrictedLearner() {
    // Admin sessions see the console entry and admin-only surfaces; everyone
    // else (students, legacy platform sessions) gets the learner experience.
    return (
      state.auth.authRequired &&
      state.auth.authenticated &&
      state.auth.role !== "admin"
    );
  }

  function applyAccessPolicy() {
    const restricted = isRestrictedLearner();
    elements.adminOnlySurfaces.forEach((surface) => {
      if (restricted || !surface.matches("[data-panel], [data-console-panel-body]")) {
        surface.hidden = restricted;
      }
      surface.setAttribute("aria-hidden", String(restricted));
    });

    if (restricted) {
      closeConsole();
    }

    if (restricted && !tabIsAvailable(activeTabName())) {
      activateTab("chat");
    }
  }

  function bindConsole() {
    elements.consoleEntry.addEventListener("click", openConsole);
    elements.consoleBack.addEventListener("click", closeConsole);
    elements.consoleNavItems.forEach((item) => {
      item.addEventListener("click", () => activateConsolePanel(item.dataset.consolePanel));
    });
    elements.refreshOverview.addEventListener("click", loadConsoleOverview);
    elements.triggerGraphExtract.addEventListener("click", triggerGraphExtraction);
    elements.refreshGraphExtract.addEventListener("click", refreshGraphExtractStatus);
    elements.runtimeSettingsForm.addEventListener("submit", saveRuntimeSettings);
    elements.refreshRuntimeSettings.addEventListener("click", loadRuntimeSettings);
    elements.resetRuntimeSettings.addEventListener("click", resetRuntimeSettings);
    elements.refreshEditorDocuments.addEventListener("click", refreshEditorDocuments);
    elements.editorLoadContent.addEventListener("click", loadEditorContent);
    elements.editorSaveContent.addEventListener("click", saveEditorContent);
    elements.editorCreateDocument.addEventListener("click", createEditorDocument);
    elements.refreshHealth.addEventListener("click", loadSystemHealth);
    elements.refreshProviderLogs.addEventListener("click", refreshProviderLogs);
  }

  function openConsole() {
    elements.workbench.hidden = true;
    elements.console.hidden = false;
    activateConsolePanel("overview");
  }

  function closeConsole() {
    elements.console.hidden = true;
    elements.workbench.hidden = false;
  }

  function activateConsolePanel(panelName) {
    elements.consoleNavItems.forEach((item) => {
      const selected = item.dataset.consolePanel === panelName;
      item.classList.toggle("is-active", selected);
      if (selected) {
        item.setAttribute("aria-current", "true");
      } else {
        item.removeAttribute("aria-current");
      }
    });
    elements.consolePanels.forEach((panel) => {
      panel.hidden = panel.dataset.consolePanelBody !== panelName;
    });

    if (panelName === "overview") {
      loadConsoleOverview();
    }

    if (panelName === "graph-extract") {
      refreshGraphExtractStatus();
    }

    if (panelName === "ops" && !state.providerObservability) {
      refreshProviderObservability();
    }

    if (panelName === "settings") {
      loadRuntimeSettings();
    }

    if (panelName === "editor") {
      refreshEditorDocuments();
    }

    if (panelName === "health") {
      loadSystemHealth();
    }

    if (panelName === "ops") {
      refreshProviderLogs();
    }
  }

  // ── 系統設定（runtime overrides） ────────────────────────
  // 表單欄位留空（或選「使用預設」）代表沿用 .env 預設值；
  // 填值即建立覆寫，儲存後立即生效。
  const RUNTIME_NUMBER_FIELDS = new Set([
    "openai_chat_max_completion_tokens",
    "openai_chat_temperature",
    "provider_budget_daily_token_limit",
    "provider_budget_daily_call_limit",
  ]);
  const RUNTIME_BOOLEAN_FIELDS = new Set([
    "provider_budget_enabled",
    "provider_budget_block_on_exceeded",
  ]);

  function runtimeSettingsFields() {
    return Array.from(
      elements.runtimeSettingsForm.querySelectorAll("input[name], select[name]"),
    );
  }

  function setRuntimeSettingsStatus(message, { failed = false } = {}) {
    elements.runtimeSettingsStatus.textContent = message;
    elements.runtimeSettingsStatus.classList.toggle("is-danger", failed);
  }

  async function loadRuntimeSettings() {
    try {
      const payload = await getJsonWithHeaders("/admin/settings", adminHeaders());
      renderRuntimeSettings(payload);
      setRuntimeSettingsStatus("已載入目前設定。");
    } catch (error) {
      setRuntimeSettingsStatus(`系統設定無法載入：${errorMessage(error)}`, { failed: true });
    }
  }

  function renderRuntimeSettings(payload) {
    state.runtimeSettings = payload || null;
    const overrides = (payload && payload.overrides) || {};
    const defaults = (payload && payload.defaults) || {};

    runtimeSettingsFields().forEach((field) => {
      const key = field.name;
      const overrideValue = overrides[key];
      field.value = overrideValue == null ? "" : String(overrideValue);
    });

    $$("#runtime-settings-form .settings-default").forEach((node) => {
      const key = node.dataset.defaultFor;
      const defaultValue = defaults[key];
      node.textContent = `預設：${formatRuntimeDefault(defaultValue)}`;
    });
  }

  function formatRuntimeDefault(value) {
    if (value == null || value === "") {
      return "未設定";
    }
    if (value === true) {
      return "開啟";
    }
    if (value === false) {
      return "關閉";
    }
    return String(value);
  }

  function collectRuntimeOverrides() {
    const overrides = {};
    runtimeSettingsFields().forEach((field) => {
      const key = field.name;
      const raw = field.value.trim();
      if (!raw) {
        return;
      }
      if (RUNTIME_BOOLEAN_FIELDS.has(key)) {
        overrides[key] = raw === "true";
        return;
      }
      if (RUNTIME_NUMBER_FIELDS.has(key)) {
        overrides[key] = Number(raw);
        return;
      }
      overrides[key] = raw;
    });
    return overrides;
  }

  async function saveRuntimeSettings(event) {
    event.preventDefault();
    await submitRuntimeOverrides(collectRuntimeOverrides(), "設定已儲存並立即生效。");
  }

  async function resetRuntimeSettings() {
    await submitRuntimeOverrides({}, "已清除全部覆寫，恢復 .env 預設值。");
  }

  async function submitRuntimeOverrides(overrides, successMessage) {
    setRuntimeSettingsStatus("儲存中…");
    try {
      const response = await fetch("/admin/settings", {
        method: "PUT",
        headers: jsonAdminHeaders(),
        body: JSON.stringify({ overrides }),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      renderRuntimeSettings(await response.json());
      setRuntimeSettingsStatus(successMessage);
      appendOperation("Runtime settings updated.");
    } catch (error) {
      setRuntimeSettingsStatus(`儲存失敗：${errorMessage(error)}`, { failed: true });
    }
  }

  // ── 教材編輯（markdown CRUD）─────────────────────────────
  function setEditorStatus(message, { failed = false } = {}) {
    elements.editorStatus.textContent = message;
    elements.editorStatus.classList.toggle("is-danger", failed);
  }

  async function refreshEditorDocuments() {
    try {
      const payload = await getJsonWithHeaders("/admin/documents?status=active", adminHeaders());
      const documents = (payload.documents || []).filter((doc) =>
        (doc.filename || "").toLowerCase().endsWith(".md"),
      );
      const previous = elements.editorDocumentSelect.value;
      elements.editorDocumentSelect.replaceChildren();
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "選擇要編輯的教材…";
      elements.editorDocumentSelect.append(placeholder);
      documents.forEach((doc) => {
        const option = document.createElement("option");
        option.value = doc.id;
        option.textContent = doc.title ? `${doc.title}（${doc.filename}）` : doc.filename;
        elements.editorDocumentSelect.append(option);
      });
      if (previous && documents.some((doc) => doc.id === previous)) {
        elements.editorDocumentSelect.value = previous;
      }
      setEditorStatus(`已載入 ${documents.length} 份 markdown 教材。`);
    } catch (error) {
      setEditorStatus(`教材清單無法載入：${errorMessage(error)}`, { failed: true });
    }
  }

  async function loadEditorContent() {
    const documentId = elements.editorDocumentSelect.value;
    if (!documentId) {
      setEditorStatus("請先選擇要編輯的教材。", { failed: true });
      return;
    }
    setEditorStatus("載入內容中…");
    try {
      const payload = await getJsonWithHeaders(
        `/admin/documents/${documentId}/content`,
        adminHeaders(),
      );
      elements.editorContent.value = payload.content;
      setEditorStatus(`已載入「${payload.filename}」，編輯後請儲存。`);
    } catch (error) {
      setEditorStatus(`內容無法載入：${errorMessage(error)}`, { failed: true });
    }
  }

  async function saveEditorContent() {
    const documentId = elements.editorDocumentSelect.value;
    const content = elements.editorContent.value;
    if (!documentId) {
      setEditorStatus("請先選擇要編輯的教材。", { failed: true });
      return;
    }
    if (!content.trim()) {
      setEditorStatus("內容不可為空。", { failed: true });
      return;
    }
    elements.editorSaveContent.disabled = true;
    setEditorStatus("儲存並重新索引中…");
    try {
      const response = await fetch(`/admin/documents/${documentId}/content`, {
        method: "PUT",
        headers: jsonAdminHeaders(),
        body: JSON.stringify({ content }),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const payload = await response.json();
      setEditorStatus(
        `已儲存「${payload.filename}」並重新索引（${payload.section_count} 段落 · ${payload.chunk_count} chunks）。`,
      );
      appendOperation(`Document content updated: ${payload.filename}`);
      await refreshSources();
      refreshGraphAfterContentChange();
    } catch (error) {
      setEditorStatus(`儲存失敗：${errorMessage(error)}`, { failed: true });
    } finally {
      elements.editorSaveContent.disabled = false;
    }
  }

  async function createEditorDocument() {
    const rawFilename = elements.editorNewFilename.value.trim();
    const content = elements.editorNewContent.value;
    if (!rawFilename) {
      setEditorStatus("請輸入新教材的檔名。", { failed: true });
      return;
    }
    if (!content.trim()) {
      setEditorStatus("新教材內容不可為空。", { failed: true });
      return;
    }
    const filename = rawFilename.toLowerCase().endsWith(".md")
      ? rawFilename
      : `${rawFilename}.md`;
    elements.editorCreateDocument.disabled = true;
    setEditorStatus("建立並索引中…");
    try {
      const formData = new FormData();
      formData.append(
        "file",
        new File([content], filename, { type: "text/markdown" }),
      );
      const response = await fetch("/imports", {
        method: "POST",
        headers: adminHeaders(),
        body: formData,
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const payload = await response.json();
      setEditorStatus(`已建立「${payload.filename}」（${payload.status}）。`);
      appendOperation(`Document created from editor: ${payload.filename}`);
      elements.editorNewFilename.value = "";
      elements.editorNewContent.value = "";
      await refreshEditorDocuments();
      await refreshSources();
      refreshGraphAfterContentChange();
    } catch (error) {
      setEditorStatus(`建立失敗：${errorMessage(error)}`, { failed: true });
    } finally {
      elements.editorCreateDocument.disabled = false;
    }
  }

  // ── 服務狀態（health/status）────────────────────────────
  async function loadSystemHealth() {
    elements.healthSummary.textContent = "檢查中…";
    try {
      const payload = await getJsonWithHeaders("/admin/system-status", adminHeaders());
      renderSystemHealth(payload);
    } catch (error) {
      elements.healthSummary.textContent = `服務狀態無法取得：${errorMessage(error)}`;
      elements.healthChecks.replaceChildren(
        emptyText(`服務狀態無法取得：${errorMessage(error)}`),
      );
    }
  }

  const HEALTH_STATUS_LABEL = { ok: "正常", warning: "注意", failed: "異常" };

  function renderSystemHealth(payload) {
    const overall = payload.overall || "unknown";
    const uptime = formatUptime(payload.uptime_seconds);
    elements.healthSummary.textContent = [
      `整體狀態：${HEALTH_STATUS_LABEL[overall] || overall}`,
      uptime ? `已運行 ${uptime}` : null,
      payload.checked_at ? `檢查於 ${formatDateTime(payload.checked_at)}` : null,
    ]
      .filter(Boolean)
      .join(" · ");

    elements.healthChecks.replaceChildren();
    (payload.checks || []).forEach((check) => {
      const card = document.createElement("article");
      card.className = `health-card is-${check.status}`;
      const heading = document.createElement("div");
      heading.className = "health-card-heading";
      const title = document.createElement("strong");
      title.textContent = check.label || check.name;
      const badge = document.createElement("span");
      badge.className = `status-badge is-${check.status === "ok" ? "succeeded" : check.status === "warning" ? "warning" : "failed"}`;
      badge.textContent = HEALTH_STATUS_LABEL[check.status] || check.status;
      heading.append(title, badge);
      const detail = document.createElement("p");
      detail.className = "source-meta";
      detail.textContent = [
        check.detail,
        check.latency_ms != null ? `${check.latency_ms} ms` : null,
      ]
        .filter(Boolean)
        .join(" · ") || "—";
      card.append(heading, detail);
      elements.healthChecks.append(card);
    });
  }

  function formatUptime(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value < 0) {
      return null;
    }
    if (value < 90) {
      return `${Math.round(value)} 秒`;
    }
    if (value < 5400) {
      return `${Math.round(value / 60)} 分鐘`;
    }
    if (value < 172800) {
      return `${(value / 3600).toFixed(1)} 小時`;
    }
    return `${(value / 86400).toFixed(1)} 天`;
  }

  // ── LLM 呼叫紀錄（provider_call_logs）───────────────────
  async function refreshProviderLogs() {
    try {
      const payload = await getJsonWithHeaders("/admin/provider-logs?limit=50", adminHeaders());
      renderProviderLogs(payload.logs || []);
    } catch (error) {
      elements.providerLogs.replaceChildren(
        emptyText(`LLM 呼叫紀錄無法載入：${errorMessage(error)}`),
      );
    }
  }

  function renderProviderLogs(logs) {
    elements.providerLogs.replaceChildren();
    if (logs.length === 0) {
      elements.providerLogs.append(emptyText("尚無 LLM 呼叫紀錄。"));
      return;
    }

    const table = document.createElement("table");
    table.className = "admin-table";
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    ["時間", "操作", "模型", "狀態", "延遲", "tokens", "詳細"].forEach((label) => {
      const cell = document.createElement("th");
      cell.textContent = label;
      headRow.append(cell);
    });
    head.append(headRow);
    table.append(head);

    const body = document.createElement("tbody");
    logs.forEach((log) => {
      const row = document.createElement("tr");
      row.className = log.status === "failed" ? "is-failed" : "";

      const cells = [
        formatDateTime(log.created_at) || "--",
        log.operation,
        log.model,
        log.status + (log.error_type ? ` (${log.error_type})` : ""),
        log.latency_ms != null ? `${log.latency_ms} ms` : "--",
        log.usage && log.usage.total_tokens != null ? String(log.usage.total_tokens) : "--",
      ];
      cells.forEach((value) => {
        const cell = document.createElement("td");
        cell.textContent = String(value);
        row.append(cell);
      });

      const detailCell = document.createElement("td");
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "text-button";
      toggle.textContent = "展開";
      detailCell.append(toggle);
      row.append(detailCell);
      body.append(row);

      const detailRow = document.createElement("tr");
      detailRow.className = "provider-log-detail";
      detailRow.hidden = true;
      const detailContent = document.createElement("td");
      detailContent.colSpan = 7;
      const pre = document.createElement("pre");
      pre.textContent = JSON.stringify(
        { request: log.request, response: log.response, usage: log.usage },
        null,
        2,
      );
      detailContent.append(pre);
      detailRow.append(detailContent);
      body.append(detailRow);

      toggle.addEventListener("click", () => {
        detailRow.hidden = !detailRow.hidden;
        toggle.textContent = detailRow.hidden ? "展開" : "收合";
      });
    });
    table.append(body);
    elements.providerLogs.append(table);
  }

  function sharedAdminKey() {
    return elements.consoleAdminKey.value.trim();
  }

  // ── Console 總覽 dashboard ───────────────────────────────
  // Four independent stat-card fetches + the recent-activity list. Each one
  // degrades to "—" + a muted note on failure so a missing admin key (or any
  // single endpoint outage) never breaks the rest of the dashboard.
  async function loadConsoleOverview() {
    await Promise.allSettled([
      loadOverviewIndexCard(),
      loadOverviewGraphCard(),
      loadOverviewJobsCard(),
      loadOverviewTokensCard(),
      loadOverviewRecentActivity(),
    ]);
  }

  function setStatCard(card, number, note, { failed = false } = {}) {
    const numberNode = card.querySelector(".stat-number");
    const noteNode = card.querySelector(".stat-note");
    numberNode.textContent = number;
    noteNode.textContent = note;
    noteNode.classList.toggle("muted", failed);
  }

  function statCardUnavailable(card, note) {
    setStatCard(card, "—", note, { failed: true });
  }

  async function loadOverviewIndexCard() {
    try {
      const payload = await getJson("/index/status");
      const stats = payload.stats || {};
      const files = stats.files_indexed;
      const chunks = stats.chunks_indexed;
      setStatCard(
        elements.statIndex,
        files == null ? "—" : formatCount(files),
        [`索引 ${payload.status}`, chunks == null ? null : `${formatCount(chunks)} chunks`]
          .filter(Boolean)
          .join(" · "),
      );
    } catch (error) {
      statCardUnavailable(elements.statIndex, `索引狀態無法取得：${errorMessage(error)}`);
    }
  }

  async function loadOverviewGraphCard() {
    try {
      const payload = await getJson("/graph");
      const stats = payload.stats || {};
      setStatCard(
        elements.statGraph,
        formatCount(stats.concept_count || 0),
        `${formatCount(stats.concept_count || 0)} 概念 · ${formatCount(stats.cluster_count || 0)} 主題`,
      );
    } catch (error) {
      statCardUnavailable(elements.statGraph, `圖譜統計無法取得：${errorMessage(error)}`);
    }
  }

  async function loadOverviewJobsCard() {
    try {
      const payload = await getJsonWithHeaders("/admin/jobs/runtime", adminHeaders());
      const queue = payload.queue || {};
      const queued = queue.queued || 0;
      const running = queue.running || 0;
      const workers = Array.isArray(payload.workers) ? payload.workers : [];
      let heartbeat = "尚無 worker 心跳";
      if ((payload.active_workers || 0) > 0) {
        heartbeat = "Worker 心跳 ✓";
      } else if (workers.some((worker) => worker && worker.status === "stopped")) {
        heartbeat = "Worker 已停止";
      } else if (workers.length > 0) {
        heartbeat = "Worker 心跳過期";
      }
      setStatCard(
        elements.statJobs,
        formatCount(queued),
        `${formatCount(queued)} queued · ${formatCount(running)} running · ${heartbeat}`,
      );
    } catch (error) {
      statCardUnavailable(elements.statJobs, `背景任務無法取得：${errorMessage(error)}`);
    }
  }

  async function loadOverviewTokensCard() {
    try {
      const payload = await getJsonWithHeaders("/metrics", adminHeaders());
      const usageByKey = payload.provider_usage_by_key || {};
      let totalTokens = 0;
      Object.values(usageByKey).forEach((usage) => {
        totalTokens += Number(usage && usage.total_tokens) || 0;
      });
      const calls = Number(payload.provider_calls_total) || 0;
      setStatCard(
        elements.statTokens,
        formatCount(totalTokens),
        `${formatCount(calls)} 次 provider 呼叫 · 自服務啟動累計`,
      );
    } catch (error) {
      statCardUnavailable(elements.statTokens, `Token 用量無法取得：${errorMessage(error)}`);
    }
  }

  async function loadOverviewRecentActivity() {
    try {
      const payload = await getJsonWithHeaders("/admin/jobs?limit=8", adminHeaders());
      const jobs = Array.isArray(payload.jobs) ? payload.jobs : [];
      elements.recentActivity.replaceChildren();
      if (jobs.length === 0) {
        const item = document.createElement("li");
        item.className = "muted";
        item.textContent = "尚無背景任務。";
        elements.recentActivity.append(item);
        return;
      }
      jobs.forEach((job) => {
        const item = document.createElement("li");
        item.className = "activity-row";
        if (job.status === "failed") {
          item.classList.add("is-danger");
        }
        item.textContent = `${formatTimeHHMM(job.created_at)} · ${job.task_type} · ${job.status}`;
        elements.recentActivity.append(item);
      });
    } catch (error) {
      const item = document.createElement("li");
      item.className = "muted";
      item.textContent = `最近活動無法取得：${errorMessage(error)}`;
      elements.recentActivity.replaceChildren(item);
    }
  }

  function formatCount(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return "—";
    }
    return number.toLocaleString("en-US");
  }

  function formatTimeHHMM(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return "--:--";
    }
    const hours = String(date.getHours()).padStart(2, "0");
    const minutes = String(date.getMinutes()).padStart(2, "0");
    return `${hours}:${minutes}`;
  }

  // ── 圖譜抽取 panel ───────────────────────────────────────
  function setGraphExtractStatus(message) {
    elements.graphExtractStatus.textContent = message;
  }

  async function triggerGraphExtraction() {
    elements.triggerGraphExtract.disabled = true;
    try {
      const response = await fetch("/graph/extract", {
        method: "POST",
        headers: adminHeaders(),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const payload = await response.json();
      setGraphExtractStatus(
        `已排入概念抽取任務：${payload.job_id}\n狀態：queued（等待背景 worker 執行）`,
      );
      appendOperation(`Queued concept extraction job: ${payload.job_id}`);
    } catch (error) {
      setGraphExtractStatus(`觸發概念抽取失敗：${errorMessage(error)}`);
      appendOperation(`Trigger concept extraction failed: ${errorMessage(error)}`);
    } finally {
      elements.triggerGraphExtract.disabled = false;
    }
  }

  async function refreshGraphExtractStatus() {
    try {
      const payload = await getJsonWithHeaders("/admin/jobs?limit=100", adminHeaders());
      const jobs = Array.isArray(payload.jobs) ? payload.jobs : [];
      const job = jobs.find((item) => item.task_type === "concept_extraction");
      if (!job) {
        setGraphExtractStatus("尚無概念抽取任務。");
        return;
      }
      const lines = [
        `最新概念抽取任務：${job.id}`,
        `狀態：${job.status}${job.error ? `（${job.error}）` : ""}`,
      ];
      const result = job.result || {};
      if (result.skipped) {
        lines.push(`已略過：${result.reason || "unknown"}`);
      }
      const statsParts = [
        "documents_extracted",
        "concepts_created",
        "concepts_merged",
        "provider_calls",
      ]
        .filter((key) => result[key] != null)
        .map((key) => `${key} ${result[key]}`);
      if (statsParts.length > 0) {
        lines.push(`結果：${statsParts.join(" · ")}`);
      }
      setGraphExtractStatus(lines.join("\n"));
    } catch (error) {
      setGraphExtractStatus(`概念抽取任務無法取得：${errorMessage(error)}`);
    }
  }

  function bindChat() {
    elements.chatQuery.addEventListener("keydown", handleChatKeydown);
    elements.chatClear.addEventListener("click", clearConversation);
    elements.chatExport.addEventListener("click", exportConversation);
    elements.chatReport.addEventListener("click", reportConversation);
    elements.chatForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const query = elements.chatQuery.value.trim();
      if (!query || state.chatBusy) {
        return;
      }

      clearChatEmptyState();
      addMessage("user", query);
      state.transcript.push({
        role: "user",
        content: query,
        at: new Date().toISOString(),
      });
      updateChatToolbar();
      const answerNode = addMessage("assistant", "");
      elements.chatQuery.value = "";
      setSelectedSources([]);
      renderStreamingStatus(answerNode, "正在搜尋課程教材…");
      setChatBusy(true, "正在搜尋課程教材…");

      try {
        await streamChat(query, answerNode);
      } catch (error) {
        answerNode.textContent = errorMessage(error);
        state.transcript.push({
          role: "assistant",
          content: errorMessage(error),
          error: true,
          at: new Date().toISOString(),
        });
        renderAnswerFooter(answerNode, {
          decision: "cannot_confirm",
          answer_quality: {
            answer_valid: false,
            citation_errors: [errorMessage(error)],
          },
        });
      } finally {
        setChatBusy(false, "可以繼續提問。");
      }
    });
  }

  // ── 對話工具列：清除 / 匯出 / 回報 ───────────────────────
  function updateChatToolbar() {
    const hasMessages = state.transcript.length > 0;
    elements.chatClear.hidden = !hasMessages;
    elements.chatExport.hidden = !hasMessages;
    // 回報需要 conversation id（第一則回答完成後才有）。
    elements.chatReport.hidden = !state.conversationId;
  }

  function clearConversation() {
    if (state.chatBusy) {
      return;
    }
    Array.from(elements.chatLog.children).forEach((child) => {
      if (child !== elements.chatEmptyState) {
        child.remove();
      }
    });
    elements.chatEmptyState.hidden = false;
    state.conversationId = null;
    state.transcript = [];
    setSelectedSources([]);
    updateChatToolbar();
    elements.chatComposerStatus.textContent = "已清除對話，可以重新提問。";
  }

  function exportConversation() {
    if (state.transcript.length === 0) {
      return;
    }
    const payload = {
      exported_at: new Date().toISOString(),
      conversation_id: state.conversationId,
      message_count: state.transcript.length,
      messages: state.transcript,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    const idPart = state.conversationId ? state.conversationId.slice(0, 8) : "session";
    link.download = `course-chat-${idPart}.json`;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    elements.chatComposerStatus.textContent = "已匯出對話 JSON。";
  }

  async function reportConversation() {
    if (!state.conversationId) {
      return;
    }
    elements.chatReport.disabled = true;
    try {
      const response = await fetch("/chat/report", {
        method: "POST",
        headers: platformJsonHeaders(),
        body: JSON.stringify({ conversation_id: state.conversationId }),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const copied = await copyTextToClipboard(state.conversationId);
      elements.chatComposerStatus.textContent = copied
        ? `已回報這次對話（session id ${state.conversationId.slice(0, 8)}… 已複製到剪貼簿）。`
        : `已回報這次對話。session id：${state.conversationId}`;
    } catch (error) {
      elements.chatComposerStatus.textContent = `回報失敗：${errorMessage(error)}`;
    } finally {
      elements.chatReport.disabled = false;
    }
  }

  async function copyTextToClipboard(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return true;
      }
      const helper = document.createElement("textarea");
      helper.value = text;
      helper.setAttribute("readonly", "");
      helper.style.position = "fixed";
      helper.style.opacity = "0";
      document.body.append(helper);
      helper.select();
      const copied = document.execCommand("copy");
      helper.remove();
      return copied;
    } catch (_) {
      return false;
    }
  }

  function bindSamplePrompts() {
    elements.samplePrompts.forEach((button) => {
      button.addEventListener("click", () => {
        elements.chatQuery.value = button.dataset.samplePrompt || button.textContent.trim();
        elements.chatQuery.focus();
        elements.chatComposerStatus.textContent = "確認問題內容後送出。";
      });
    });
  }

  function handleChatKeydown(event) {
    if (event.isComposing || event.keyCode === 229) {
      return;
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!state.chatBusy) {
        elements.chatForm.requestSubmit();
      }
    }
  }

  function clearChatEmptyState() {
    if (elements.chatEmptyState) {
      elements.chatEmptyState.hidden = true;
    }
  }

  function setChatBusy(isBusy, statusText) {
    state.chatBusy = isBusy;
    elements.chatQuery.disabled = isBusy;
    elements.chatSubmit.disabled = isBusy;
    elements.samplePrompts.forEach((button) => {
      button.disabled = isBusy;
    });
    elements.chatForm.classList.toggle("is-busy", isBusy);
    elements.chatComposerStatus.textContent = statusText || (isBusy ? "處理中…" : "可以提問。");
  }

  function renderStreamingStatus(answerNode, message) {
    answerNode.textContent = message;
    answerNode.classList.add("is-streaming-status");
    elements.chatComposerStatus.textContent = message;
    elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
  }

  async function streamChat(query, answerNode) {
    const payload = {
      query,
      strategy: CHAT_STRATEGY,
      limit: CHAT_LIMIT,
    };
    if (state.conversationId) {
      payload.conversation_id = state.conversationId;
    }
    const response = await fetch("/chat/stream", {
      method: "POST",
      headers: platformJsonHeaders(),
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(await responseError(response));
    }

    if (!response.body) {
      answerNode.textContent = await response.text();
      return;
    }

    let receivedToken = false;
    await readSse(response.body, (event) => {
      if (event.event === "sources") {
        const payload = safeJson(event.data);
        const sourceCount = (payload.selected_sources || payload.sources || []).length;
        if (!receivedToken) {
          renderStreamingStatus(
            answerNode,
            sourceCount > 0
              ? `找到 ${sourceCount} 個相關段落，整理回答中…`
              : "正在整理回答…",
          );
        }
        return;
      }

      if (event.event === "token") {
        if (!receivedToken) {
          answerNode.textContent = "";
          answerNode.classList.remove("is-streaming-status");
          receivedToken = true;
        }
        answerNode.textContent += event.data;
        elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
        return;
      }

      if (event.event === "error") {
        const payload = safeJson(event.data);
        answerNode.textContent = payload.detail || event.data || "Chat stream failed.";
        answerNode.classList.remove("is-streaming-status");
        renderAnswerFooter(answerNode, {
          decision: "cannot_confirm",
          answer_quality: {
            answer_valid: false,
            citation_errors: [answerNode.textContent],
          },
        });
      }

      if (event.event === "done") {
        const payload = safeJson(event.data);
        if (typeof payload.answer === "string" && answerNode.textContent !== payload.answer) {
          answerNode.textContent = payload.answer;
          answerNode.classList.remove("is-streaming-status");
        }
        const citedSources = answerIsCannotConfirm(payload) ? [] : payload.sources || [];
        setSelectedSources(citedSources);
        renderAnswerFooter(answerNode, payload);
        if (payload.conversation_id) {
          state.conversationId = payload.conversation_id;
        }
        state.transcript.push({
          role: "assistant",
          content: payload.answer ?? answerNode.textContent,
          at: new Date().toISOString(),
          decision: payload.decision || null,
          conversation_id: payload.conversation_id || null,
          assistant_message_id: payload.assistant_message_id || null,
          citations: citedSources.map((source) => ({
            source_id: source.source_id,
            heading: source.heading,
            filename: source.filename,
          })),
        });
        updateChatToolbar();
      }
    });
  }

  function answerIsCannotConfirm(payload) {
    const quality = payload.answer_quality || {};
    return (
      payload.decision === "cannot_confirm" ||
      Boolean(quality.cannot_confirm_reason) ||
      quality.answer_valid === false
    );
  }

  async function readSse(body, onEvent) {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let frameEnd = buffer.indexOf("\n\n");
      while (frameEnd !== -1) {
        const frame = buffer.slice(0, frameEnd);
        buffer = buffer.slice(frameEnd + 2);
        const event = parseSseFrame(frame);
        if (event) {
          onEvent(event);
        }
        frameEnd = buffer.indexOf("\n\n");
      }
    }

    buffer += decoder.decode();
    if (buffer.trim()) {
      const event = parseSseFrame(buffer);
      if (event) {
        onEvent(event);
      }
    }
  }

  function parseSseFrame(frame) {
    const event = {
      event: "message",
      data: "",
    };
    const dataLines = [];

    frame.split("\n").forEach((line) => {
      if (line.startsWith("event:")) {
        event.event = line.slice(6).trim();
      }
      if (line.startsWith("data:")) {
        dataLines.push(parseSseDataLine(line));
      }
    });

    event.data = dataLines.join("\n");
    return event.data || event.event !== "message" ? event : null;
  }

  function parseSseDataLine(line) {
    const value = line.slice(5);
    return value.startsWith(" ") ? value.slice(1) : value;
  }

  const CHAT_STRATEGY = "hybrid";
  const CHAT_LIMIT = 10;

  function addMessage(role, text) {
    const wrapper = document.createElement("div");
    wrapper.className = `message ${role}`;

    const label = document.createElement("span");
    label.className = "message-label";
    label.textContent = role === "user" ? "你" : "課程助理";

    const card = document.createElement("div");
    card.className = role === "user" ? "user-bubble" : "answer-card";

    const body = document.createElement("p");
    body.textContent = text;

    card.append(body);
    wrapper.append(label, card);
    elements.chatLog.append(wrapper);
    elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
    return body;
  }

  function renderAnswerFooter(answerNode, payload) {
    const card = answerNode.closest(".answer-card");
    if (!card) {
      return;
    }

    const cannotConfirm = answerIsCannotConfirm(payload);
    const citedSources = cannotConfirm ? [] : payload.sources || state.selectedSources;
    if (!cannotConfirm) {
      renderAnswerCitations(answerNode, citedSources);
    }
    card.querySelector(".trust-badge")?.remove();
    card.querySelector(".answer-footer")?.remove();

    const trust = document.createElement("span");
    const trustState = answerTrustState(payload);
    trust.className = `trust-badge is-${trustState}`;
    trust.textContent = answerTrustText(payload, citedSources);
    card.prepend(trust);

    const footer = document.createElement("div");
    footer.className = "answer-footer";
    renderSourceChips(footer, citedSources);
    renderFeedbackRow(footer, payload, citedSources);
    card.append(footer);
  }

  function renderAnswerCitations(answerNode, sources) {
    const answer = answerNode.textContent || "";
    const ranges = citationRanges(answer, sources);
    if (ranges.length === 0) {
      answerNode.textContent = answer;
      return;
    }

    const fragments = [];
    let cursor = 0;
    ranges.forEach((range) => {
      if (range.start > cursor) {
        fragments.push(document.createTextNode(answer.slice(cursor, range.start)));
      }
      // 對不到任何來源的 token 直接隱藏（range.source 為 null），
      // 不讓原始 [file.md#anchor] 字串干擾學生閱讀。
      if (range.source) {
        fragments.push(inlineCitationButton(range.source, range.displayIndex));
      }
      cursor = range.end;
    });
    if (cursor < answer.length) {
      fragments.push(document.createTextNode(answer.slice(cursor)));
    }
    answerNode.replaceChildren(...fragments);
  }

  // 看起來像引用、但跟已知來源完全比對不到的 token，
  // 例如模型自己改寫過 anchor 的 [1-基本觀念-09-Caching.md#某段落]。
  const LOOSE_CITATION_RE = /\[([^\[\]\r\n]{1,200}\.md#[^\[\]\r\n]{1,200})\]/g;

  function citationRanges(answer, sources) {
    const sourceList = Array.isArray(sources) ? sources : [];
    const ranges = [];
    sourceList.forEach((source, index) => {
      if (!source.source_id) {
        return;
      }
      const token = `[${source.source_id}]`;
      let start = answer.indexOf(token);
      while (start !== -1) {
        ranges.push({
          start,
          end: start + token.length,
          source,
          displayIndex: index + 1,
        });
        start = answer.indexOf(token, start + token.length);
      }
    });

    // 第二輪：寬鬆比對。anchor 對不上時退回以檔名對應同一份教材的
    // 既有引用；連檔名都對不到就標記為 source: null（渲染時隱藏）。
    LOOSE_CITATION_RE.lastIndex = 0;
    let looseMatch = LOOSE_CITATION_RE.exec(answer);
    while (looseMatch !== null) {
      const start = looseMatch.index;
      const end = start + looseMatch[0].length;
      const overlapsExact = ranges.some((range) => start < range.end && end > range.start);
      if (!overlapsExact) {
        const tokenFilename = looseMatch[1].split("#")[0].trim();
        const fallbackIndex = sourceList.findIndex(
          (source) =>
            source.filename === tokenFilename ||
            (source.source_id || "").startsWith(`${tokenFilename}#`),
        );
        ranges.push({
          start,
          end,
          source: fallbackIndex >= 0 ? sourceList[fallbackIndex] : null,
          displayIndex: fallbackIndex >= 0 ? fallbackIndex + 1 : null,
        });
      }
      looseMatch = LOOSE_CITATION_RE.exec(answer);
    }

    return ranges
      .sort((left, right) => left.start - right.start || right.end - left.end)
      .filter((range, index, sortedRanges) => {
        const previous = sortedRanges[index - 1];
        return !previous || range.start >= previous.end;
      });
  }

  function inlineCitationButton(source, displayIndex) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "citation-pill";
    button.textContent = String(displayIndex);
    button.title = source.source_id || citationLabelForSource(source, displayIndex);
    button.setAttribute(
      "aria-label",
      `Preview source ${displayIndex}: ${sourceShortLabel(source)}`,
    );
    button.addEventListener("click", () => previewSourceFromChip(source));
    return button;
  }

  function renderSourceChips(wrapper, sources) {
    const sourceList = Array.isArray(sources) ? sources : [];
    if (sourceList.length === 0) {
      return;
    }

    const chipRow = document.createElement("div");
    chipRow.className = "source-chip-row";
    sourceList.forEach((source, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "source-chip";
      button.textContent = citationLabelForSource(source, index + 1);
      button.title = source.source_id || "";
      button.addEventListener("click", () => previewSourceFromChip(source));
      chipRow.append(button);
    });
    wrapper.append(chipRow);
  }

  function previewSourceFromChip(source) {
    previewCandidate(source);
    elements.markdownPreview.focus({ preventScroll: true });
    if (window.matchMedia("(max-width: 760px)").matches) {
      elements.markdownPreview.scrollIntoView({ block: "start", behavior: "smooth" });
    }
  }

  function renderFeedbackRow(wrapper, payload, sources) {
    if (!payload.assistant_message_id) {
      return;
    }

    const panel = document.createElement("div");
    panel.className = "answer-feedback";
    panel.dataset.messageId = payload.assistant_message_id;

    const actions = document.createElement("div");
    actions.className = "feedback-actions";
    actions.append(
      feedbackActionButton("有幫助", () =>
        submitAnswerFeedback(panel, payload, {
          rating: 1,
          reason: "helpful",
          expectedSource: feedbackExpectedSource(sources, payload.answer_quality),
        }),
      ),
      feedbackActionButton("沒有幫助", () =>
        showFeedbackDetails(panel, payload, sources, "not_helpful"),
      ),
      feedbackActionButton("找不到我要的", () =>
        showFeedbackDetails(panel, payload, sources, "answer_missing"),
      ),
    );

    const status = document.createElement("span");
    status.className = "feedback-status";
    status.setAttribute("aria-live", "polite");

    panel.append(actions, status);
    wrapper.append(panel);
  }

  function feedbackActionButton(label, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "feedback-button";
    button.textContent = label;
    button.addEventListener("click", onClick);
    return button;
  }

  function showFeedbackDetails(panel, payload, sources, reason) {
    panel.querySelector(".feedback-detail")?.remove();

    const detail = document.createElement("div");
    detail.className = "feedback-detail";

    const note = document.createElement("textarea");
    note.rows = 2;
    note.placeholder = reason === "answer_missing"
      ? "您期望得到什麼答案？"
      : "哪裡需要改善？";

    const sourceSelect = document.createElement("select");
    sourceSelect.setAttribute("aria-label", "預期來源");
    const emptyOption = document.createElement("option");
    emptyOption.value = "";
    emptyOption.textContent = "預期來源";
    sourceSelect.append(emptyOption);
    (Array.isArray(sources) ? sources : []).forEach((source, index) => {
      if (!source.source_id) {
        return;
      }
      const option = document.createElement("option");
      option.value = source.source_id;
      option.textContent = citationLabelForSource(source, index + 1);
      sourceSelect.append(option);
    });

    const submit = feedbackActionButton("送出意見", () =>
      submitAnswerFeedback(panel, payload, {
        rating: -1,
        reason,
        expectedSource: feedbackExpectedSource(
          sources,
          payload.answer_quality,
          sourceSelect.value,
        ),
        note: note.value.trim(),
      }),
    );

    detail.append(note, sourceSelect, submit);
    panel.append(detail);
    note.focus();
  }

  async function submitAnswerFeedback(panel, payload, feedback) {
    const status = panel.querySelector(".feedback-status");
    const controls = panel.querySelectorAll("button, textarea, select");
    controls.forEach((control) => {
      control.disabled = true;
    });
    if (status) {
      status.textContent = "儲存中...";
    }

    try {
      const response = await fetch("/feedback", {
        method: "POST",
        headers: platformJsonHeaders(),
        body: JSON.stringify({
          message_id: payload.assistant_message_id,
          rating: feedback.rating,
          reason: feedback.reason,
          expected_source: feedback.expectedSource || null,
          note: feedback.note || null,
        }),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      panel.classList.add("is-submitted");
      if (status) {
        status.textContent = "Feedback saved.";
      }
    } catch (error) {
      controls.forEach((control) => {
        control.disabled = false;
      });
      if (status) {
        status.textContent = `Feedback failed: ${errorMessage(error)}`;
      }
    }
  }

  function feedbackExpectedSource(sources, answerQuality, explicitSource = "") {
    if (explicitSource) {
      return explicitSource;
    }
    const citedSourceIds = answerQuality?.cited_source_ids || [];
    if (citedSourceIds.length > 0) {
      return citedSourceIds[0];
    }
    const firstSource = Array.isArray(sources) ? sources[0] : null;
    return firstSource?.source_id || null;
  }

  function answerTrustText(payload, sources) {
    const quality = payload.answer_quality || {};
    if (quality.cannot_confirm_reason === "not_indexed") {
      return "課程知識庫尚未建立索引";
    }
    if (quality.cannot_confirm_reason === "guardrail_blocked") {
      return "這個問題和課程學習無關";
    }
    if (answerIsCannotConfirm(payload)) {
      return "教材中找不到這個問題的答案";
    }

    const sourceCount = Array.isArray(sources) ? sources.length : 0;
    if (sourceCount > 0) {
      return `✓ 依據 ${sourceCount} 個課程段落回答`;
    }
    return "回答未引用課程段落";
  }

  function answerTrustState(payload) {
    return answerIsCannotConfirm(payload) ? "warn" : "ok";
  }

  function setSelectedSources(sources) {
    state.selectedSources = Array.isArray(sources) ? sources : [];
    elements.selectedSources.replaceChildren();
    elements.selectedSourceCount.textContent = String(state.selectedSources.length);

    if (state.selectedSources.length === 0) {
      elements.selectedSources.append(emptyText("這次回答沒有引用來源。"));
      elements.citationDisclosure.open = false;
      resetPreviewSourceMeta();
      elements.markdownPreview.replaceChildren(
        emptyText("點選回答中的引用編號，這裡會顯示教材原文。"),
      );
      return;
    }

    state.selectedSources.forEach((source, index) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "source-row";
      row.dataset.sourceId = source.source_id || "";
      row.addEventListener("click", () => previewCandidate(source));

      const title = document.createElement("strong");
      title.textContent = citationLabelForSource(source, index + 1);
      const meta = document.createElement("span");
      meta.className = "source-meta";
      meta.textContent = sourceFilenameLabel(source);

      row.append(title, meta);
      elements.selectedSources.append(row);
    });
  }

  function sourceFilenameLabel(source) {
    const filename = source.filename || "";
    return filename.replace(/\.md$/i, "");
  }

  function citationLabelForSource(source, displayIndex) {
    return `[${displayIndex}] ${sourceShortLabel(source)}`;
  }

  function sourceShortLabel(source) {
    const heading = source.heading || "";
    if (heading && heading !== source.source_id) {
      return heading;
    }
    const filename = source.filename || source.source_id || "Source";
    return filename.replace(/\.md$/i, "");
  }

  function previewCandidate(source) {
    const heading = source.heading || "教材段落";
    const body = source.body_md || "這個段落沒有內容。";
    renderPreviewSourceMeta({
      title: heading,
      summary: sourceFilenameLabel(source) || "課程教材",
      kind: "引用來源",
    });
    renderMarkdownInto(elements.markdownPreview, body);
    setActiveSourceRow(source.source_id);
    renderGraphCrossLink(source.source_id, heading, body);
  }

  function setActiveSourceRow(sourceId) {
    $$("#answer-sources .source-row").forEach((row) => {
      row.classList.toggle("is-active", Boolean(sourceId) && row.dataset.sourceId === sourceId);
    });
  }

  function bindSources() {
    elements.refreshSources.addEventListener("click", refreshSources);
    elements.refreshDocuments.addEventListener("click", refreshAdminDocuments);
    elements.sourceReaderBack.addEventListener("click", closeSourceReader);
  }

  async function refreshSources() {
    try {
      const payload = await getJson("/sources");
      state.documents = payload.documents || [];
      renderSources();
      updateLearnerChatStatus();
    } catch (error) {
      state.documents = [];
      elements.sourceTable.replaceChildren(
        emptyText(`無法載入教材：${errorMessage(error)}`),
      );
      updateLearnerChatStatus("目前無法載入課程教材。");
    }
  }

  function renderSources() {
    elements.sourceTable.replaceChildren();

    if (state.documents.length === 0) {
      elements.sourceTable.append(emptyText("尚未找到已索引的來源。"));
      return;
    }

    state.documents.forEach((documentItem) => {
      elements.sourceTable.append(sourceTableRow(documentItem));
    });
  }

  function sourceTableRow(documentItem) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "doc-row";
    row.dataset.docId = documentItem.id;
    row.addEventListener("click", () => openSourceReader(documentItem));

    const title = document.createElement("strong");
    title.className = "source-title";
    title.textContent = documentDisplayTitle(documentItem);
    const meta = document.createElement("span");
    meta.className = "source-meta";
    meta.textContent = documentSourceSummaryZh(documentItem);

    row.append(title, meta);
    return row;
  }

  function documentSourceSummaryZh(documentItem) {
    const sectionCount = documentItem.section_count || 0;
    return `${sectionCount} 個段落`;
  }

  async function refreshAdminDocuments() {
    try {
      const response = await fetch("/admin/documents", {
        headers: adminHeaders(),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const payload = await response.json();
      renderAdminDocuments(payload.documents || []);
    } catch (error) {
      state.adminDocuments = [];
      elements.adminDocuments.replaceChildren(
        emptyText(`文件生命週期資料無法載入：${errorMessage(error)}`),
      );
    }
  }

  function renderAdminDocuments(documents) {
    state.adminDocuments = Array.isArray(documents) ? documents : [];
    elements.adminDocuments.replaceChildren();

    if (state.adminDocuments.length === 0) {
      elements.adminDocuments.append(emptyText("尚未載入管理文件。"));
      return;
    }

    state.adminDocuments.forEach((documentItem) => {
      const row = document.createElement("div");
      row.className = `document-row is-${documentItem.index_status || "unknown"}`;
      const body = document.createElement("div");
      body.className = "job-body";
      const title = document.createElement("strong");
      title.textContent = documentItem.title || documentItem.filename;
      const meta = document.createElement("span");
      meta.className = "source-meta";
      meta.textContent = [
        documentItem.lifecycle_status,
        documentItem.index_status,
        `${documentItem.section_count || 0} sections`,
        `${documentItem.chunk_count || 0} chunks`,
        documentItem.canonical_exists ? "source ok" : "source missing",
      ].join(" · ");
      body.append(title, meta);

      const actions = document.createElement("div");
      actions.className = "button-row";
      if (documentItem.lifecycle_status === "disabled") {
        actions.append(documentActionButton("Enable", () => setDocumentLifecycle(documentItem.id, "active")));
      } else if (documentItem.lifecycle_status !== "deleted") {
        actions.append(
          documentActionButton("Disable", () =>
            setDocumentLifecycle(documentItem.id, "disabled", "disabled from UI"),
          ),
        );
      }
      actions.append(documentActionButton("Reindex", () => reindexDocument(documentItem.id)));
      actions.append(
        documentActionButton("Queue Reindex", () => queueDocumentReindexJob(documentItem.id)),
      );
      actions.append(documentActionButton("Delete Index", () => deleteDocumentIndex(documentItem.id)));
      row.append(body, actions);
      elements.adminDocuments.append(row);
    });
  }

  function documentActionButton(label, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary-button";
    button.textContent = label;
    button.addEventListener("click", onClick);
    return button;
  }

  async function setDocumentLifecycle(documentId, status, reason = null) {
    try {
      const response = await fetch(`/admin/documents/${documentId}/lifecycle`, {
        method: "PATCH",
        headers: jsonAdminHeaders(),
        body: JSON.stringify({ status, reason }),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const payload = await response.json();
      appendOperation(`Document ${payload.lifecycle_status}: ${payload.filename}`);
      await refreshAdminDocuments();
      await refreshSources();
      await refreshGraphAfterContentChange();
    } catch (error) {
      appendOperation(`Document lifecycle update failed: ${errorMessage(error)}`);
    }
  }

  async function deleteDocumentIndex(documentId) {
    try {
      const response = await fetch(`/admin/documents/${documentId}`, {
        method: "DELETE",
        headers: adminHeaders(),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const payload = await response.json();
      appendOperation(`Document index deleted: ${payload.filename}`);
      await refreshAdminDocuments();
      await refreshSources();
      await refreshGraphAfterContentChange();
    } catch (error) {
      appendOperation(`Document index delete failed: ${errorMessage(error)}`);
    }
  }

  async function reindexDocument(documentId) {
    try {
      const response = await fetch(`/admin/documents/${documentId}/reindex`, {
        method: "POST",
        headers: adminHeaders(),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const payload = await response.json();
      appendOperation(`Document reindexed: ${payload.filename}`);
      await refreshAdminDocuments();
      await refreshSources();
      await refreshGraphAfterContentChange();
    } catch (error) {
      appendOperation(`Document reindex failed: ${errorMessage(error)}`);
    }
  }

  // 教材閱讀器 — 在中間欄展開教材全文，取代列表。
  async function openSourceReader(documentItem) {
    elements.sourceTable.hidden = true;
    elements.sourceReader.hidden = false;
    elements.sourceReaderBody.replaceChildren(emptyText("載入教材內容中…"));

    try {
      const documentDetail = await getJson(`/sources/${documentItem.id}`);
      const sections = await Promise.all(
        (documentDetail.sections || []).map((section) =>
          getJson(`/sources/${documentDetail.id}/sections/${section.id}`),
        ),
      );

      const fragment = document.createDocumentFragment();
      const title = document.createElement("h1");
      title.textContent = documentDisplayTitle(documentDetail);
      fragment.append(title);

      if (sections.length === 0) {
        fragment.append(emptyText("這份教材還沒有索引的段落。"));
      }
      sections.forEach((section) => {
        const body = section.body_md || "";
        if (section.heading && !markdownStartsWithHeading(body, section.heading)) {
          const headingLevel = Math.min(4, Math.max(2, (section.level || 1) + 1));
          const heading = document.createElement(`h${headingLevel}`);
          heading.textContent = section.heading;
          fragment.append(heading);
        }
        fragment.append(renderMarkdownFragment(body));
      });

      elements.sourceReaderBody.replaceChildren(fragment);
      elements.sourceReaderBody.focus({ preventScroll: true });
      elements.sourceReaderBody.scrollTop = 0;
    } catch (error) {
      elements.sourceReaderBody.replaceChildren(
        emptyText(`教材內容無法載入：${errorMessage(error)}`),
      );
    }
  }

  function closeSourceReader() {
    elements.sourceReader.hidden = true;
    elements.sourceTable.hidden = false;
  }

  // ── Markdown 渲染（無外部依賴）────────────────────────────
  // 支援：標題、清單、引用、程式碼區塊、表格、粗斜體、行內碼、連結。
  // 一律以 textContent 寫入文字節點，來源內容不會被當成 HTML 解析。
  function renderMarkdownInto(container, markdownText) {
    container.replaceChildren(renderMarkdownFragment(markdownText));
  }

  // ── Mermaid 圖表渲染 ─────────────────────────────────────
  // 教材的 ```mermaid 區塊改畫成圖；mermaid 未載入或語法錯誤時，
  // 退回原本的程式碼區塊，閱讀不會中斷。
  let mermaidSeq = 0;
  let mermaidConfigured = false;

  document.addEventListener("kb-theme-changed", () => {
    // 之後渲染的圖採用新主題；已渲染的圖維持原樣。
    mermaidConfigured = false;
  });

  function ensureMermaidConfigured() {
    if (typeof mermaid === "undefined") {
      return false;
    }
    if (!mermaidConfigured) {
      const dark =
        document.documentElement.getAttribute("data-theme") === "dark" ||
        (!document.documentElement.getAttribute("data-theme") &&
          window.matchMedia("(prefers-color-scheme: dark)").matches);
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        suppressErrorRendering: true,
        theme: dark ? "dark" : "neutral",
        fontFamily: '"Noto Sans TC", "PingFang TC", "Segoe UI", sans-serif',
      });
      mermaidConfigured = true;
    }
    return true;
  }

  function mermaidBlock(codeText) {
    const container = document.createElement("div");
    container.className = "mermaid-diagram";

    const fallbackToCode = () => {
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = codeText;
      pre.append(code);
      container.replaceChildren(pre);
      container.classList.add("is-fallback");
    };

    if (!ensureMermaidConfigured()) {
      fallbackToCode();
      return container;
    }

    const renderId = `kb-mermaid-${++mermaidSeq}`;
    mermaid
      .render(renderId, codeText)
      .then(({ svg }) => {
        // mermaid 在 strict 模式輸出的 SVG 已淨化，可直接插入。
        container.innerHTML = svg;
      })
      .catch(() => {
        document.getElementById(`d${renderId}`)?.remove();
        fallbackToCode();
      });
    return container;
  }

  function markdownStartsWithHeading(markdownText, headingText) {
    const firstLine = String(markdownText || "")
      .split("\n")
      .find((line) => line.trim());
    const match = (firstLine || "").match(/^#{1,6}\s+(.*)$/);
    return Boolean(match) && match[1].trim() === String(headingText).trim();
  }

  function renderMarkdownFragment(markdownText) {
    const fragment = document.createDocumentFragment();
    const lines = String(markdownText || "").replace(/\r\n/g, "\n").split("\n");
    let index = 0;

    while (index < lines.length) {
      const line = lines[index];

      if (!line.trim() || /^\s*<!--.*-->\s*$/.test(line)) {
        index += 1;
        continue;
      }

      const fence = line.match(/^```\s*(\S*)/);
      if (fence) {
        const language = (fence[1] || "").toLowerCase();
        const codeLines = [];
        index += 1;
        while (index < lines.length && !/^```/.test(lines[index])) {
          codeLines.push(lines[index]);
          index += 1;
        }
        index += 1; // skip closing fence
        const codeText = codeLines.join("\n");
        if (language === "mermaid") {
          fragment.append(mermaidBlock(codeText));
        } else {
          const pre = document.createElement("pre");
          const code = document.createElement("code");
          code.textContent = codeText;
          pre.append(code);
          fragment.append(pre);
        }
        continue;
      }

      const heading = line.match(/^(#{1,6})\s+(.*)$/);
      if (heading) {
        const level = Math.min(6, heading[1].length + 1);
        const node = document.createElement(`h${level}`);
        node.append(renderInlineMarkdown(heading[2]));
        fragment.append(node);
        index += 1;
        continue;
      }

      if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
        fragment.append(document.createElement("hr"));
        index += 1;
        continue;
      }

      if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
        const ordered = /^\s*\d+[.)]\s+/.test(line);
        const list = document.createElement(ordered ? "ol" : "ul");
        while (index < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[index])) {
          const item = document.createElement("li");
          item.append(
            renderInlineMarkdown(lines[index].replace(/^\s*([-*+]|\d+[.)])\s+/, "")),
          );
          list.append(item);
          index += 1;
        }
        fragment.append(list);
        continue;
      }

      if (/^>\s?/.test(line)) {
        const quoteLines = [];
        while (index < lines.length && /^>\s?/.test(lines[index])) {
          quoteLines.push(lines[index].replace(/^>\s?/, ""));
          index += 1;
        }
        const quote = document.createElement("blockquote");
        quote.append(renderMarkdownFragment(quoteLines.join("\n")));
        fragment.append(quote);
        continue;
      }

      if (/^\|.*\|\s*$/.test(line)) {
        const tableLines = [];
        while (index < lines.length && /^\|.*\|\s*$/.test(lines[index])) {
          tableLines.push(lines[index]);
          index += 1;
        }
        fragment.append(renderMarkdownTable(tableLines));
        continue;
      }

      const paragraphLines = [];
      while (
        index < lines.length &&
        lines[index].trim() &&
        !/^(#{1,6}\s|```|>\s?|\|.*\|\s*$|\s*([-*+]|\d+[.)])\s+|(-{3,}|\*{3,}|_{3,})\s*$)/.test(
          lines[index],
        )
      ) {
        paragraphLines.push(lines[index].trim());
        index += 1;
      }
      if (paragraphLines.length > 0) {
        const paragraph = document.createElement("p");
        paragraph.append(renderInlineMarkdown(paragraphLines.join(" ")));
        fragment.append(paragraph);
      } else {
        index += 1;
      }
    }

    return fragment;
  }

  function renderMarkdownTable(tableLines) {
    const table = document.createElement("table");
    const rows = tableLines
      .map((line) =>
        line
          .replace(/^\||\|\s*$/g, "")
          .split("|")
          .map((cell) => cell.trim()),
      )
      .filter((cells, rowIndex) => {
        // Skip the |---|---| separator row.
        const isSeparator = cells.every((cell) => /^:?-{2,}:?$/.test(cell || "-"));
        return !(rowIndex === 1 && isSeparator);
      });

    rows.forEach((cells, rowIndex) => {
      const row = document.createElement("tr");
      cells.forEach((cell) => {
        const node = document.createElement(rowIndex === 0 ? "th" : "td");
        node.append(renderInlineMarkdown(cell));
        row.append(node);
      });
      table.append(row);
    });
    return table;
  }

  function renderInlineMarkdown(text) {
    const fragment = document.createDocumentFragment();
    const pattern =
      /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\[([^\]]+)\]\((https?:\/\/[^\s)]+)\))/g;
    let cursor = 0;
    let match = pattern.exec(text);

    while (match) {
      if (match.index > cursor) {
        fragment.append(document.createTextNode(text.slice(cursor, match.index)));
      }
      if (match[1]) {
        const code = document.createElement("code");
        code.textContent = match[1].slice(1, -1);
        fragment.append(code);
      } else if (match[2]) {
        const strong = document.createElement("strong");
        strong.textContent = match[2].slice(2, -2);
        fragment.append(strong);
      } else if (match[3]) {
        const em = document.createElement("em");
        em.textContent = match[3].slice(1, -1);
        fragment.append(em);
      } else if (match[4]) {
        const link = document.createElement("a");
        link.textContent = match[5];
        link.href = match[6];
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        fragment.append(link);
      }
      cursor = match.index + match[0].length;
      match = pattern.exec(text);
    }

    if (cursor < text.length) {
      fragment.append(document.createTextNode(text.slice(cursor)));
    }
    return fragment;
  }

  function documentDisplayTitle(documentItem) {
    const title = documentItem.title || "";
    if (title && title !== documentItem.filename?.replace(/\.md$/i, "")) {
      return title;
    }
    const filename = documentItem.filename || title || "Untitled source";
    return filename.replace(/\.md$/i, "");
  }

  function renderPreviewSourceMeta({ title, summary, kind }) {
    elements.previewSourceMeta.replaceChildren();
    const wrapper = document.createElement("div");
    wrapper.className = "preview-source-card";
    const label = document.createElement("span");
    label.textContent = kind || "預覽";
    const heading = document.createElement("strong");
    heading.textContent = title || "未命名教材";
    const meta = document.createElement("span");
    meta.className = "source-meta";
    meta.textContent = summary || "";
    wrapper.append(label, heading, meta);
    elements.previewSourceMeta.append(wrapper);
  }

  function resetPreviewSourceMeta() {
    elements.previewSourceMeta.replaceChildren(
      emptyText("點選回答中的引用編號，這裡會顯示教材原文。"),
    );
  }

  // --- knowledge graph ---
  // Light palette — existing saturated colours for warm paper surfaces.
  const CLUSTER_COLORS_LIGHT = ["#4285f4", "#34a853", "#f9ab00", "#ea4335", "#9334e6",
    "#12a4af", "#e8710a", "#7b1fa2", "#1565c0", "#2e7d32", "#c2185b", "#5d4037"];
  // Dark palette — same hue family, lightness lifted for legibility on dark canvas.
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

  // Re-render (or mark stale) when the user toggles the theme. Registered once
  // at module scope; the handler only reads state at event time.
  document.addEventListener("kb-theme-changed", () => {
    if (!state.graphLoaded) return;
    if (activeTabName() === "graph") {
      renderGraphView(state.graphView || "cluster");
    } else {
      // Graph tab not visible — defer; activateTab("graph") will reload lazily.
      // Note: any pending focusGraphConcept target from the cross-link is lost
      // here because renderGraphView creates a fresh cy instance. A pending focus
      // could be preserved by storing the concept id in state before re-render
      // and re-selecting after; not implemented — left as a comment per plan.
      state.graphStale = true;
    }
  });

  // Single source for empty-state copy — read once from DOM at bind time.
  let GRAPH_EMPTY_TEXT = "";

  function bindGraph() {
    GRAPH_EMPTY_TEXT = elements.graphEmpty.textContent || "尚未建立知識圖譜。請先建立索引並執行概念抽取。";
    elements.loadGraph.addEventListener("click", loadGraph);
    elements.graphViewCluster.addEventListener("click", () => setGraphView("cluster"));
    elements.graphViewRadial.addEventListener("click", () => setGraphView("radial"));
    elements.graphViewOrder.addEventListener("click", () => setGraphView("order"));
    elements.graphSearch.addEventListener("input", filterGraphNodes);
  }

  async function loadGraph() {
    elements.loadGraph.disabled = true;
    state.graphStale = false;

    try {
      state.graph = await getJson("/graph");
      state.graphLoaded = true;
      // Concept extraction may have changed concept→source mappings.
      state.conceptSourceCache.clear();
      renderGraphView(state.graphView || "cluster");
    } catch (error) {
      // Keep the old canvas and loaded state if an instance already exists so
      // the user isn't left with a blank graph after a transient failure.
      if (!state.cy) {
        state.graphLoaded = false;
        elements.graphEmpty.hidden = false;
        elements.graphEmpty.textContent = `圖譜載入失敗：${errorMessage(error)}`;
      } else {
        console.error("Graph reload failed (keeping previous view):", errorMessage(error));
      }
    } finally {
      elements.loadGraph.disabled = false;
    }
  }

  function graphElements(useCompound, theme) {
    const clusters = state.graph.clusters || [];
    const clusterColor = new Map();
    const clusterIndex = new Map();
    clusters.forEach((cluster, index) => {
      clusterColor.set(cluster.id, theme.clusterColors[index % theme.clusterColors.length]);
      clusterIndex.set(cluster.id, index);
    });
    const clusterCount = clusters.length;
    const parents = clusters.map((cluster) => ({
      data: {
        id: `cluster:${cluster.id}`,
        label: cluster.name,
        baseLabel: cluster.name,
        isCluster: true,
        // Defensive only: the node[?isCluster] selector uses no data() mappings,
        // so these fields are inert — kept in case a generic node rule returns.
        color: "transparent",
        size: 40,
      },
    }));
    const nodes = (state.graph.nodes || []).map((node) => {
      const idx = clusterIndex.has(node.cluster_id) ? clusterIndex.get(node.cluster_id) : 0;
      const nodeData = {
        id: node.id,
        label: node.name,
        summary: node.summary,
        // Newline-joined lowercase aliases so the search filter can match
        // them without a query ever spanning two adjacent aliases.
        aliases: (node.aliases || []).join("\n").toLowerCase(),
        // Unclustered concepts get a theme-aware neutral, never a cluster's color.
        color: clusterColor.get(node.cluster_id) || theme.edgeArrow,
        size: 18 + Math.min(22, node.source_count * 4),
        // clusterIndex used by radial layout for concentric ring assignment.
        clusterIndex: idx,
        clusterCount,
      };
      // Only attach parent when rendering compound (cluster view).
      if (useCompound && node.cluster_id) {
        nodeData.parent = `cluster:${node.cluster_id}`;
      }
      return { data: nodeData };
    });
    const edges = (state.graph.edges || []).map((edge, index) => ({
      data: { id: `e${index}`, source: edge.source, target: edge.target, kind: edge.kind },
    }));
    return { parents, nodes, edges };
  }

  // 叢集視圖使用確定性的「群內螺旋＋群間網格」布局：力導向（cose）在
  // 多群組大圖上會發散成不可讀的巨大畫布，preset 位置每次都穩定可讀。
  function buildClusterPresetPositions(nodeDefs) {
    const GOLDEN_ANGLE = 2.399963229728653;
    const NODE_SPACING = 62;
    const CLUSTER_GAP = 110;
    const ROW_MAX_WIDTH = 2300;

    const groups = new Map();
    nodeDefs.forEach((def) => {
      const key = def.data.parent || `solo:${def.data.clusterIndex ?? "none"}`;
      if (!groups.has(key)) {
        groups.set(key, []);
      }
      groups.get(key).push(def);
    });

    const infos = [...groups.values()]
      .map((members) => ({
        members,
        radius: Math.max(90, NODE_SPACING * 0.7 * Math.sqrt(members.length) + 50),
      }))
      .sort((a, b) => b.members.length - a.members.length);

    const positions = {};
    let rowX = 0;
    let rowY = 0;
    let rowHeight = 0;
    infos.forEach((info) => {
      const diameter = info.radius * 2;
      if (rowX > 0 && rowX + diameter > ROW_MAX_WIDTH) {
        rowY += rowHeight + CLUSTER_GAP;
        rowX = 0;
        rowHeight = 0;
      }
      const centerX = rowX + info.radius;
      const centerY = rowY + info.radius;
      info.members.forEach((def, index) => {
        const r = NODE_SPACING * 0.62 * Math.sqrt(index + 0.5);
        const theta = index * GOLDEN_ANGLE;
        positions[def.data.id] = {
          x: centerX + r * Math.cos(theta),
          y: centerY + r * Math.sin(theta),
        };
      });
      rowX += diameter + CLUSTER_GAP;
      rowHeight = Math.max(rowHeight, diameter);
    });
    return positions;
  }

  const GRAPH_LAYOUTS = {
    // Radial: assign each cluster its own concentric ring.
    // clusterCount - clusterIndex gives outermost ring to cluster 0's concepts;
    // level 0 is reserved for anything without a cluster.
    radial: {
      name: "concentric",
      animate: false,
      padding: 30,
      minNodeSpacing: 48,
      concentric: (node) => {
        const count = node.data("clusterCount") || 1;
        const idx = node.data("clusterIndex") || 0;
        return count - idx;
      },
      levelWidth: () => 1,
      fit: true,
    },
    order: {
      name: "dagre",
      rankDir: "LR",
      animate: false,
      padding: 30,
      nodeSep: 36,
      rankSep: 110,
      fit: true,
    },
  };

  function renderGraphView(view) {
    state.graphView = view;
    // Use cached element refs; sync is-active and aria-pressed together.
    [
      [elements.graphViewCluster, "cluster"],
      [elements.graphViewRadial, "radial"],
      [elements.graphViewOrder, "order"],
    ].forEach(([btn, btnView]) => {
      const active = btnView === view;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-pressed", String(active));
    });
    if (!state.graphLoaded) {
      return;
    }

    const hasNodes = (state.graph.nodes || []).length > 0;
    elements.graphEmpty.hidden = hasNodes;
    if (!hasNodes) {
      elements.graphEmpty.textContent = GRAPH_EMPTY_TEXT;
      if (state.cy) {
        state.cy.destroy();
        state.cy = null;
      }
      return;
    }

    const useCompound = view === "cluster";
    const orderView = view === "order";
    const theme = resolveGraphTheme();
    const { parents, nodes, edges } = graphElements(useCompound, theme);
    if (state.cy) {
      state.cy.destroy();
    }
    const layout = useCompound
      ? (() => {
          const positions = buildClusterPresetPositions(nodes);
          return {
            name: "preset",
            positions: (node) => positions[node.id()],
            fit: true,
            padding: 30,
          };
        })()
      : GRAPH_LAYOUTS[view];
    state.cy = cytoscape({
      container: elements.graphCanvas,
      elements: [...(useCompound ? parents : []), ...nodes, ...edges],
      layout,
      minZoom: 0.03,
      maxZoom: 3,
      wheelSensitivity: 0.2,
      style: [
        { selector: "node[^isCluster]", style: {
          label: "data(label)", "font-size": 12, width: "data(size)", height: "data(size)",
          "background-color": "data(color)", "text-valign": "bottom", "text-margin-y": 5,
          "text-wrap": "wrap", "text-max-width": 130,
          color: theme.label } },
        // Compound parent nodes use a separate selector (no data() size/color
        // mappings) to avoid Cytoscape style-mapping warnings for fields that
        // compound nodes do not carry.
        { selector: "node[?isCluster]", style: {
          "background-opacity": 0.08, "border-width": 1.5,
          "border-color": theme.clusterBorder,
          label: "data(label)", "font-size": 15, "font-weight": 700,
          color: theme.label, "text-valign": "top", shape: "round-rectangle",
          padding: 18 } },
        { selector: "edge", style: {
          width: 1.4, "line-color": theme.edge, "curve-style": "bezier" } },
        { selector: 'edge[kind = "prerequisite"]', style: {
          "target-arrow-shape": "triangle", "target-arrow-color": theme.edgeArrow,
          "line-color": theme.edgeArrow } },
        { selector: 'edge[kind = "part_of"]', style: { "line-style": "dashed" } },
        ...(orderView
          ? [{ selector: 'edge[kind != "prerequisite"]', style: { opacity: 0.25 } }]
          : []),
        { selector: "node.dimmed", style: { opacity: 0.12, "text-opacity": 0.1 } },
        { selector: "edge.dimmed", style: { opacity: 0.08 } },
        { selector: "node.highlighted", style: { "border-width": 3, "border-color": theme.highlight } },
      ],
    });
    state.cy.on("tap", "node[^isCluster]", (event) => {
      highlightGraphNeighborhood(event.target);
      previewConcept(event.target.id());
    });
    state.cy.on("tap", "node[?isCluster]", (event) => toggleClusterCollapse(event.target.id()));
    state.cy.on("tap", (event) => {
      if (event.target === state.cy) {
        clearGraphNeighborhood();
      }
    });
    state.cy.fit(undefined, 30);
    applyClusterCollapse();
    filterGraphNodes();
    renderGraphStats();
  }

  function highlightGraphNeighborhood(node) {
    const cy = state.cy;
    if (!cy) {
      return;
    }
    cy.elements().removeClass("dimmed highlighted");
    const neighborhood = node.closedNeighborhood();
    cy.elements()
      .not(neighborhood)
      .not(cy.nodes("[?isCluster]"))
      .addClass("dimmed");
    node.addClass("highlighted");
  }

  function clearGraphNeighborhood() {
    if (!state.cy) {
      return;
    }
    state.cy.elements().removeClass("dimmed highlighted");
    filterGraphNodes();
  }

  function setGraphView(view) {
    if (view === state.graphView && state.cy) {
      return;
    }
    renderGraphView(view);
  }

  function toggleClusterCollapse(clusterNodeId) {
    if (state.collapsedClusters.has(clusterNodeId)) {
      state.collapsedClusters.delete(clusterNodeId);
    } else {
      state.collapsedClusters.add(clusterNodeId);
    }
    applyClusterCollapse();
  }

  function applyClusterCollapse() {
    if (!state.cy || state.graphView !== "cluster") {
      return;
    }
    state.cy.nodes("[?isCluster]").forEach((clusterNode) => {
      const collapsed = state.collapsedClusters.has(clusterNode.id());
      const children = clusterNode.children();
      children.style("display", collapsed ? "none" : "element");
      children.connectedEdges().style("display", collapsed ? "none" : "element");
      clusterNode.data(
        "label",
        collapsed
          ? `${clusterNode.data("baseLabel")} (+${children.length})`
          : clusterNode.data("baseLabel"),
      );
    });
    state.cy.edges().forEach((edge) => {
      const endpointHidden =
        edge.source().style("display") === "none" || edge.target().style("display") === "none";
      if (endpointHidden) {
        edge.style("display", "none");
      }
    });
  }

  function filterGraphNodes() {
    if (!state.cy) {
      return;
    }
    const query = elements.graphSearch.value.trim().toLowerCase();
    state.cy.nodes("[^isCluster]").forEach((node) => {
      const match =
        !query ||
        node.data("label").toLowerCase().includes(query) ||
        (node.data("aliases") || "").includes(query);
      node.toggleClass("dimmed", !match);
      node.toggleClass("highlighted", Boolean(query) && match);
    });
  }

  function renderGraphStats() {
    const stats = state.graph.stats || {};
    const parts = [
      `${stats.concept_count || 0} 個概念`,
      `${stats.cluster_count || 0} 個主題`,
      `${stats.edge_count || 0} 條關聯`,
    ];
    elements.graphStats.textContent = parts.join(" · ");
  }

  // 概念詳情 — 點選圖中節點後渲染在右欄（來源內容區），
  // 不佔用圖譜畫布的高度，也不需要往下捲動。
  async function previewConcept(conceptId) {
    renderPreviewSourceMeta({
      title: "載入概念中…",
      summary: "",
      kind: "知識圖譜概念",
    });
    elements.markdownPreview.replaceChildren(emptyText("載入概念中…"));

    try {
      const detail = await getJson(`/graph/concepts/${conceptId}`);
      state.graphConceptDetail = detail;
      renderConceptDetail(detail);
    } catch (error) {
      elements.markdownPreview.replaceChildren(
        emptyText(`概念內容無法載入：${errorMessage(error)}`),
      );
    }
  }

  function renderConceptDetail(detail) {
    const sources = Array.isArray(detail.sources) ? detail.sources : [];
    renderPreviewSourceMeta({
      title: detail.name,
      summary: [detail.cluster, `${sources.length} 個相關段落`].filter(Boolean).join(" · "),
      kind: "知識圖譜概念",
    });

    const askButton = document.createElement("button");
    askButton.type = "button";
    askButton.className = "secondary-button graph-detail-ask";
    askButton.textContent = "拿這個概念去提問";
    askButton.addEventListener("click", () => askAboutConcept(detail.name));
    elements.previewSourceMeta.append(askButton);

    const fragment = document.createDocumentFragment();

    if (detail.summary) {
      const summary = document.createElement("p");
      summary.className = "graph-detail-summary";
      summary.textContent = detail.summary;
      fragment.append(summary);
    }

    const aliases = Array.isArray(detail.aliases) ? detail.aliases : [];
    if (aliases.length > 0) {
      const aliasLine = document.createElement("p");
      aliasLine.className = "source-meta";
      aliasLine.textContent = `也稱作：${aliases.join("、")}`;
      fragment.append(aliasLine);
    }

    if (sources.length > 0) {
      const sourcesHeading = document.createElement("h4");
      sourcesHeading.className = "graph-detail-sources-heading";
      sourcesHeading.textContent = `相關教材段落（${sources.length}）`;
      fragment.append(sourcesHeading);

      const sourceList = document.createElement("div");
      sourceList.className = "concept-sources";
      sources.forEach((source) => {
        const row = document.createElement("button");
        row.type = "button";
        row.className = "source-row";
        row.addEventListener("click", () => previewConceptSource(source));

        const rowTitle = document.createElement("strong");
        rowTitle.className = "source-title";
        rowTitle.textContent = source.heading || source.source_id;
        const meta = document.createElement("span");
        meta.className = "source-meta";
        meta.textContent = (source.filename || "").replace(/\.md$/i, "");

        row.append(rowTitle, meta);
        sourceList.append(row);
      });
      fragment.append(sourceList);
    }

    elements.markdownPreview.replaceChildren(fragment);
  }

  async function previewConceptSource(source) {
    const backButton = document.createElement("button");
    backButton.type = "button";
    backButton.className = "text-button concept-back-link";
    backButton.textContent = "← 回到概念";
    backButton.addEventListener("click", () => {
      if (state.graphConceptDetail) {
        renderConceptDetail(state.graphConceptDetail);
      }
    });

    renderPreviewSourceMeta({
      title: source.heading || source.source_id,
      summary: (source.filename || "").replace(/\.md$/i, ""),
      kind: "教材段落",
    });
    elements.markdownPreview.replaceChildren(backButton, emptyText("載入教材段落中…"));

    try {
      const section = await getJson(
        `/sources/${source.document_id}/sections/${source.section_id}`,
      );
      const body = document.createElement("div");
      body.className = "markdown-body";
      renderMarkdownInto(body, section.body_md || "");
      elements.markdownPreview.replaceChildren(backButton, body);
    } catch (error) {
      elements.markdownPreview.replaceChildren(
        backButton,
        emptyText(`教材段落無法載入：${errorMessage(error)}`),
      );
    }
  }

  // Guards async cross-link rendering against stale previews: only the most
  // recent renderGraphCrossLink call may append its button.
  let graphCrossLinkToken = 0;

  async function renderGraphCrossLink(sourceId, headingText, bodyText) {
    const token = ++graphCrossLinkToken;
    elements.previewSourceMeta.querySelector(".graph-cross-link")?.remove();
    if (!state.graphLoaded || !sourceId) {
      return;
    }

    const concept = await findConceptForSource(sourceId, headingText, bodyText);
    if (!concept || token !== graphCrossLinkToken) {
      return;
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = "graph-cross-link";
    button.textContent = `🗺 在知識圖譜中查看「${concept.name}」`;
    button.addEventListener("click", () => focusGraphConcept(concept.id));
    elements.previewSourceMeta.append(button);
  }

  // Heuristic mapping from a previewed section to a graph concept. The /graph
  // payload carries no concept→source lists and adding a backend lookup is out
  // of scope, so: take graph nodes whose name or alias appears in the section
  // heading/body (max 3 candidates), lazily fetch /graph/concepts/{id} for
  // each (results cached in state.conceptSourceCache), and return the first
  // concept whose sources include the previewed source_id.
  async function findConceptForSource(sourceId, headingText, bodyText) {
    const haystack = `${headingText || ""}\n${bodyText || ""}`.toLowerCase();
    const candidates = (state.graph.nodes || [])
      .filter((node) => {
        const name = (node.name || "").toLowerCase();
        if (name && haystack.includes(name)) {
          return true;
        }
        return (node.aliases || []).some(
          (alias) => alias && haystack.includes(alias.toLowerCase()),
        );
      })
      .slice(0, 3);

    for (const node of candidates) {
      let sourceIds = state.conceptSourceCache.get(node.id);
      if (!sourceIds) {
        try {
          const detail = await getJson(`/graph/concepts/${node.id}`);
          sourceIds = (detail.sources || []).map((item) => item.source_id);
          // Only cache on success; a failed fetch is not cached so transient
          // errors (network blip, 5xx) retry on the next invocation.
          state.conceptSourceCache.set(node.id, sourceIds);
        } catch (_) {
          // Transient error: skip caching so the next call retries.
          sourceIds = [];
        }
      }
      if (sourceIds.includes(sourceId)) {
        return node;
      }
    }
    return null;
  }

  function focusGraphConcept(conceptId) {
    // Note: activateTab("graph") may trigger an async loadGraph() call when
    // state.graphStale is true (e.g. after a theme change while the graph tab
    // was hidden). In that case renderGraphView creates a new cy instance, so
    // the select/center below operates on the OLD instance and silently no-ops.
    // Preserving the pending focus across a re-render would require storing
    // the target conceptId in state before the reload — not implemented; the
    // user can re-click the cross-link after the graph reloads.
    activateTab("graph");
    if (!state.cy) {
      return;
    }
    const node = state.cy.$id(conceptId);
    if (node.empty()) {
      return;
    }
    state.cy.elements().unselect();
    node.select();
    state.cy.center(node);
    highlightGraphNeighborhood(node);
    previewConcept(conceptId);
  }

  function askAboutConcept(name) {
    elements.chatQuery.value = `請解釋「${name}」，以及它和課程裡其他概念的關係。`;
    activateTab("chat");
    elements.chatQuery.focus();
  }

  function refreshGraphAfterContentChange() {
    // Mark the graph as stale so it is reloaded lazily when the user
    // returns to the graph tab, avoiding a 0×0 cytoscape container.
    if (state.graphLoaded || state.cy) {
      state.graphStale = true;
    }
    // Reload immediately only when the graph panel is already visible.
    if (activeTabName() === "graph") {
      loadGraph();
    }
  }

  function bindAdmin() {
    elements.uploadForm.addEventListener("submit", uploadFile);
    elements.rebuildIndex.addEventListener("click", rebuildIndex);
    elements.queueIndexJob.addEventListener("click", queueIndexJob);
    elements.recoverStaleJobs.addEventListener("click", recoverStaleJobs);
    elements.refreshImports.addEventListener("click", refreshImportJobs);
    elements.refreshBackgroundJobs.addEventListener("click", refreshBackgroundJobs);
    elements.backgroundJobStatusFilter.addEventListener("change", refreshBackgroundJobs);
    elements.backgroundJobLimit.addEventListener("change", refreshBackgroundJobs);
    elements.refreshProviderObservability.addEventListener("click", refreshProviderObservability);
    elements.refreshAudit.addEventListener("click", refreshAuditEvents);
  }

  function bindEvals() {
    elements.evalForm.addEventListener("submit", createEvalCase);
    elements.refreshEvals.addEventListener("click", refreshEvals);
    elements.seedEvals.addEventListener("click", seedEvals);
    elements.runEvals.addEventListener("click", runEvals);
  }

  async function uploadFile(event) {
    event.preventDefault();
    const file = elements.uploadFile.files[0];
    if (!file) {
      appendOperation("Choose a file before uploading.");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);

    try {
      appendOperation(`Uploading ${file.name}...`);
      const response = await fetch("/imports", {
        method: "POST",
        headers: adminHeaders(),
        body: formData,
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const payload = await response.json();
      appendOperation(
        `Import ${payload.status}: ${payload.filename} -> ${payload.canonical_path}`,
      );
      elements.uploadFile.value = "";
      renderImportJobs([payload, ...state.importJobs]);
      await refreshImportJobs();
      await refreshBackgroundJobs();
    } catch (error) {
      appendOperation(`Upload failed: ${errorMessage(error)}`);
    }
  }

  async function rebuildIndex() {
    elements.rebuildIndex.disabled = true;
    try {
      appendOperation("Rebuilding index...");
      const response = await fetch("/index", {
        method: "POST",
        headers: adminHeaders(),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const payload = await response.json();
      appendOperation(
        `Index ${payload.status}: ${payload.files_indexed} files, ${payload.chunks_indexed} chunks`,
      );
      await refreshSources();
      await refreshGraphAfterContentChange();
    } catch (error) {
      appendOperation(`Index rebuild failed: ${errorMessage(error)}`);
    } finally {
      elements.rebuildIndex.disabled = false;
    }
  }

  async function queueIndexJob() {
    elements.queueIndexJob.disabled = true;
    try {
      const job = await queueBackgroundJob("index.rebuild", { source: "ui" });
      appendOperation(`Queued background job: ${job.task_type} (${job.id})`);
      renderBackgroundJobs([job, ...state.backgroundJobs]);
      await refreshBackgroundJob(job.id);
    } catch (error) {
      appendOperation(`Queue index job failed: ${errorMessage(error)}`);
    } finally {
      elements.queueIndexJob.disabled = false;
    }
  }

  async function queueDocumentReindexJob(documentId) {
    try {
      const job = await queueBackgroundJob("document.reindex", { document_id: documentId });
      appendOperation(`Queued document reindex job: ${job.id}`);
      renderBackgroundJobs([job, ...state.backgroundJobs]);
      await refreshBackgroundJob(job.id);
    } catch (error) {
      appendOperation(`Queue document reindex failed: ${errorMessage(error)}`);
    }
  }

  async function queueBackgroundJob(taskType, payload) {
    const response = await fetch("/admin/jobs", {
      method: "POST",
      headers: jsonAdminHeaders(),
      body: JSON.stringify({
        task_type: taskType,
        payload: payload || {},
      }),
    });
    if (!response.ok) {
      throw new Error(await responseError(response));
    }
    return response.json();
  }

  async function refreshBackgroundJobs() {
    try {
      const response = await fetch("/admin/jobs?" + backgroundJobQueryParams(), {
        headers: adminHeaders(),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const payload = await response.json();
      renderBackgroundJobs(payload.jobs || []);
    } catch (error) {
      state.backgroundJobs = [];
      renderBackgroundJobSummary([]);
      elements.backgroundJobs.replaceChildren(
        emptyText(`Background jobs unavailable: ${errorMessage(error)}`),
      );
    } finally {
      await refreshWorkerRuntime();
    }
  }

  async function refreshWorkerRuntime() {
    try {
      const response = await fetch("/admin/jobs/runtime", {
        headers: adminHeaders(),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      renderWorkerRuntime(await response.json());
    } catch (error) {
      state.workerRuntime = null;
      elements.workerRuntime.replaceChildren(
        emptyText(`Worker runtime unavailable: ${errorMessage(error)}`),
      );
    }
  }

  function renderWorkerRuntime(runtime) {
    state.workerRuntime = runtime || null;
    elements.workerRuntime.replaceChildren();
    if (!runtime) {
      elements.workerRuntime.append(emptyText("No worker runtime status loaded."));
      return;
    }

    const queue = runtime.queue || {};
    [
      ["Queue", `${queue.queued || 0} queued · ${queue.running || 0} running`],
      ["Workers", `${runtime.active_workers || 0} active`],
      ["Stale Jobs", runtime.stale_running_jobs || 0],
    ].forEach(([label, value]) => {
      const card = document.createElement("div");
      card.className = "worker-card";
      const title = document.createElement("strong");
      title.textContent = label;
      const meta = document.createElement("span");
      meta.className = "source-meta";
      meta.textContent = String(value);
      card.append(title, meta);
      elements.workerRuntime.append(card);
    });

    const workers = Array.isArray(runtime.workers) ? runtime.workers : [];
    if (workers.length === 0) {
      const card = document.createElement("div");
      card.className = "worker-card";
      card.append(emptyText("No workers have reported a heartbeat."));
      elements.workerRuntime.append(card);
      return;
    }

    workers.forEach((worker) => {
      const card = document.createElement("div");
      card.className = `worker-card ${worker.is_stale ? "is-danger" : ""}`;
      const heading = document.createElement("div");
      heading.className = "job-row-heading";
      const title = document.createElement("strong");
      title.textContent = worker.worker_id || "worker";
      const badges = document.createElement("div");
      badges.className = "job-badges";
      badges.append(backgroundJobBadge(worker.status || "unknown", worker.status || "unknown"));
      if (worker.is_stale) {
        badges.append(backgroundJobBadge("stale", "stale"));
      }
      heading.append(title, badges);
      const meta = document.createElement("span");
      meta.className = "source-meta";
      meta.textContent = [
        `${worker.processed_jobs || 0} processed`,
        worker.current_task_type ? `current ${worker.current_task_type}` : null,
        worker.last_job_status ? `last ${worker.last_job_status}` : null,
        backgroundJobAgeLabel(worker.last_seen_at, "seen"),
      ]
        .filter(Boolean)
        .join(" · ");
      card.append(heading, meta);
      elements.workerRuntime.append(card);
    });
  }

  async function refreshProviderObservability() {
    elements.refreshProviderObservability.disabled = true;
    try {
      const response = await fetch("/admin/provider-observability?limit=50", {
        headers: adminHeaders(),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const payload = await response.json();
      renderProviderObservability(payload);
    } catch (error) {
      state.providerObservability = null;
      const message = `Provider observability unavailable: ${errorMessage(error)}`;
      elements.providerSummary.replaceChildren(emptyText(message));
      elements.providerBudget.replaceChildren(emptyText("No provider budget loaded."));
      elements.providerUsage.replaceChildren(emptyText("No provider usage loaded."));
      elements.providerLatestCalls.replaceChildren(emptyText("No provider calls loaded."));
      elements.providerTraces.replaceChildren(emptyText("No provider traces loaded."));
    } finally {
      elements.refreshProviderObservability.disabled = false;
    }
  }

  function renderProviderObservability(payload) {
    state.providerObservability = payload || null;
    renderProviderSummary(payload && payload.summary);
    renderProviderBudget(payload && payload.budget);
    renderProviderUsage(payload && payload.usage_by_key);
    renderProviderLatestCalls(payload && payload.latest_calls);
    renderProviderTraces(payload && payload.traces);
  }

  function renderProviderSummary(summary) {
    const safeSummary = summary || {};
    const errorRate = Number(safeSummary.error_rate || 0);
    const cards = [
      ["Calls", safeSummary.total_calls || 0, ""],
      ["Errors", safeSummary.error_calls || 0, safeSummary.error_calls > 0 ? "is-danger" : ""],
      ["Error Rate", formatPercent(errorRate), errorRate > 0 ? "is-warning" : ""],
      ["Tokens", safeSummary.total_tokens || 0, ""],
      ["Cached", safeSummary.cached_tokens || 0, ""],
      ["Reasoning", safeSummary.reasoning_tokens || 0, ""],
    ];

    elements.providerSummary.replaceChildren();
    cards.forEach(([label, value, modifier]) => {
      const card = document.createElement("div");
      card.className = ["ops-summary-card", modifier].filter(Boolean).join(" ");
      const title = document.createElement("span");
      title.textContent = label;
      const count = document.createElement("strong");
      count.textContent = String(value);
      card.append(title, count);
      elements.providerSummary.append(card);
    });
  }

  function renderProviderUsage(items) {
    const usageItems = Array.isArray(items) ? items : [];
    elements.providerUsage.replaceChildren();
    if (usageItems.length === 0) {
      elements.providerUsage.append(emptyText("No provider usage loaded."));
      return;
    }

    usageItems.forEach((item) => {
      const row = document.createElement("div");
      row.className = "job-row provider-row";

      const body = document.createElement("div");
      body.className = "job-body";
      const heading = document.createElement("div");
      heading.className = "job-row-heading";
      const title = document.createElement("strong");
      title.textContent = item.key || "provider operation";
      const badges = document.createElement("div");
      badges.className = "job-badges";
      badges.append(backgroundJobBadge(`${item.calls || 0} calls`, "succeeded"));
      heading.append(title, badges);

      const usage = document.createElement("span");
      usage.className = "source-meta";
      usage.textContent = providerUsageText(item.usage);
      body.append(heading, usage);
      row.append(body);
      elements.providerUsage.append(row);
    });
  }

  function renderProviderBudget(budget) {
    elements.providerBudget.replaceChildren();
    if (!budget) {
      elements.providerBudget.append(emptyText("No provider budget loaded."));
      return;
    }

    const row = document.createElement("div");
    row.className = `job-row provider-budget-row is-${providerBudgetStatusClass(budget.status)}`;
    const body = document.createElement("div");
    body.className = "job-body";

    const heading = document.createElement("div");
    heading.className = "job-row-heading";
    const title = document.createElement("strong");
    title.textContent = budget.enabled ? `Budget ${budget.status || "ok"}` : "Budget disabled";
    const badges = document.createElement("div");
    badges.className = "job-badges";
    badges.append(backgroundJobBadge(budget.status || "ok", providerBudgetStatusClass(budget.status)));
    badges.append(
      backgroundJobBadge(budget.should_block ? "blocking" : "not blocking", budget.should_block ? "failed" : "succeeded"),
    );
    heading.append(title, badges);

    const meta = document.createElement("span");
    meta.className = "source-meta";
    meta.textContent = [
      budget.enabled ? "enabled" : "disabled",
      budget.block_on_exceeded ? "hard block enabled" : "alert only",
      budget.reasons && budget.reasons.length ? `reasons: ${budget.reasons.join(", ")}` : null,
    ]
      .filter(Boolean)
      .join(" · ");
    body.append(heading, meta);
    row.append(body);
    elements.providerBudget.append(row);

    const policies = Array.isArray(budget.policies) ? budget.policies : [];
    if (policies.length === 0) {
      elements.providerBudget.append(emptyText("No active provider budget policies."));
      return;
    }
    policies.forEach((policy) => {
      elements.providerBudget.append(renderProviderBudgetPolicyRow(policy));
    });
  }

  function renderProviderBudgetPolicyRow(policy) {
    const row = document.createElement("div");
    row.className = `job-row provider-budget-policy is-${providerBudgetStatusClass(policy.status)}`;

    const body = document.createElement("div");
    body.className = "job-body";
    const heading = document.createElement("div");
    heading.className = "job-row-heading";
    const title = document.createElement("strong");
    title.textContent = policy.label || policy.name || "Budget policy";
    const badges = document.createElement("div");
    badges.className = "job-badges";
    badges.append(backgroundJobBadge(policy.status || "ok", providerBudgetStatusClass(policy.status)));
    heading.append(title, badges);

    const meta = document.createElement("span");
    meta.className = "source-meta";
    meta.textContent = [
      `used ${providerBudgetValue(policy.used, policy.unit)}`,
      policy.limit == null ? "no limit" : `limit ${providerBudgetValue(policy.limit, policy.unit)}`,
      policy.warning_threshold == null ? null : `warn ${providerBudgetValue(policy.warning_threshold, policy.unit)}`,
      policy.remaining == null ? null : `remaining ${providerBudgetValue(policy.remaining, policy.unit)}`,
    ]
      .filter(Boolean)
      .join(" · ");

    const detail = document.createElement("span");
    detail.className = "source-meta";
    detail.textContent = policy.reason || "Within configured guardrail.";
    body.append(heading, meta, detail);
    row.append(body);
    return row;
  }

  function renderProviderLatestCalls(calls) {
    const providerCalls = Array.isArray(calls) ? calls : [];
    elements.providerLatestCalls.replaceChildren();
    if (providerCalls.length === 0) {
      elements.providerLatestCalls.append(emptyText("No provider calls loaded."));
      return;
    }

    providerCalls.slice(0, 20).forEach((call) => {
      elements.providerLatestCalls.append(renderProviderCallRow(call));
    });
  }

  function renderProviderTraces(traces) {
    const providerTraces = Array.isArray(traces) ? traces : [];
    elements.providerTraces.replaceChildren();
    if (providerTraces.length === 0) {
      elements.providerTraces.append(emptyText("No provider traces loaded."));
      return;
    }

    providerTraces.forEach((trace) => {
      const row = document.createElement("div");
      row.className = "job-row provider-trace";

      const body = document.createElement("div");
      body.className = "job-body";

      const heading = document.createElement("div");
      heading.className = "job-row-heading";
      const title = document.createElement("strong");
      title.textContent = trace.query || "provider-backed answer";
      const badges = document.createElement("div");
      badges.className = "job-badges";
      badges.append(backgroundJobBadge(trace.decision || "unknown", trace.decision === "can_answer" ? "succeeded" : "warning"));
      heading.append(title, badges);

      const meta = document.createElement("span");
      meta.className = "source-meta";
      meta.textContent = [
        trace.strategy ? `strategy ${trace.strategy}` : null,
        trace.latency_ms == null ? null : `${trace.latency_ms} ms`,
        trace.created_at ? formatDateTime(trace.created_at) : null,
        trace.retrieval_event_id ? `event ${trace.retrieval_event_id}` : null,
      ]
        .filter(Boolean)
        .join(" · ");

      const callSummary = document.createElement("span");
      callSummary.className = "source-meta";
      callSummary.textContent = providerTraceCallSummary(trace.provider_calls);

      body.append(heading, meta, callSummary);
      row.append(body);
      elements.providerTraces.append(row);
    });
  }

  function renderProviderCallRow(call) {
    const row = document.createElement("div");
    row.className = `job-row provider-call is-${providerCallStatusClass(call)}`;

    const body = document.createElement("div");
    body.className = "job-body";

    const heading = document.createElement("div");
    heading.className = "job-row-heading";
    const title = document.createElement("strong");
    title.textContent = [call.provider || "provider", call.operation || "operation"].join(" · ");
    const badges = document.createElement("div");
    badges.className = "job-badges";
    badges.append(backgroundJobBadge(call.status || "unknown", providerCallStatusClass(call)));
    badges.append(
      backgroundJobBadge(call.usage_complete ? "usage complete" : "usage pending", call.usage_complete ? "succeeded" : "warning"),
    );
    if (call.error_type) {
      badges.append(backgroundJobBadge(call.error_type, "failed"));
    }
    heading.append(title, badges);

    const meta = document.createElement("span");
    meta.className = "source-meta";
    meta.textContent = [
      call.model ? `model ${call.model}` : null,
      call.latency_ms == null ? null : `${call.latency_ms} ms`,
      call.client_request_id ? `client ${call.client_request_id}` : null,
      call.provider_request_id ? `provider ${call.provider_request_id}` : null,
    ]
      .filter(Boolean)
      .join(" · ");

    const usage = document.createElement("span");
    usage.className = "source-meta";
    usage.textContent = providerUsageText(call.usage);

    body.append(heading, meta, usage);
    row.append(body);
    return row;
  }

  function providerTraceCallSummary(calls) {
    const providerCalls = Array.isArray(calls) ? calls : [];
    if (providerCalls.length === 0) {
      return "provider calls: none recorded";
    }
    return providerCalls
      .slice(0, 4)
      .map((call) =>
        [
          call.provider || "provider",
          call.operation || "operation",
          call.model || null,
          call.status || "unknown",
          call.usage && call.usage.total_tokens != null ? `${call.usage.total_tokens} tokens` : null,
        ]
          .filter(Boolean)
          .join(" "),
      )
      .join(" · ");
  }

  function providerUsageText(usage) {
    const safeUsage = usage || {};
    return [
      `prompt ${safeUsage.prompt_tokens || 0}`,
      `completion ${safeUsage.completion_tokens || 0}`,
      `total ${safeUsage.total_tokens || 0}`,
      `cached ${safeUsage.cached_tokens || 0}`,
      `reasoning ${safeUsage.reasoning_tokens || 0}`,
    ].join(" · ");
  }

  function providerCallStatusClass(call) {
    if (!call || !call.status) {
      return "unknown";
    }
    if (call.status === "succeeded") {
      return "succeeded";
    }
    if (call.status === "failed") {
      return "failed";
    }
    return "warning";
  }

  function providerBudgetStatusClass(status) {
    if (status === "exceeded") {
      return "failed";
    }
    if (status === "warning") {
      return "warning";
    }
    return "succeeded";
  }

  function providerBudgetValue(value, unit) {
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return "--";
    }
    if (unit === "ratio") {
      return formatPercent(number);
    }
    return String(number);
  }

  function backgroundJobQueryParams() {
    const params = new URLSearchParams();
    params.set("limit", String(backgroundJobLimit()));
    if (elements.backgroundJobStatusFilter.value) {
      params.set("status", elements.backgroundJobStatusFilter.value);
    }
    return params.toString();
  }

  function backgroundJobLimit() {
    const rawLimit = Number(elements.backgroundJobLimit.value || 50);
    const normalizedLimit = Number.isFinite(rawLimit) ? Math.round(rawLimit) : 50;
    const clampedLimit = Math.min(100, Math.max(1, normalizedLimit));
    elements.backgroundJobLimit.value = String(clampedLimit);
    return clampedLimit;
  }

  async function refreshBackgroundJob(jobId) {
    const response = await fetch(`/admin/jobs/${jobId}`, {
      headers: adminHeaders(),
    });
    if (!response.ok) {
      throw new Error(await responseError(response));
    }
    const job = await response.json();
    const remaining = state.backgroundJobs.filter((item) => item.id !== job.id);
    renderBackgroundJobs([job, ...remaining]);
    return job;
  }

  async function recoverStaleJobs() {
    elements.recoverStaleJobs.disabled = true;
    try {
      const response = await fetch("/admin/jobs/recover-stale", {
        method: "POST",
        headers: jsonAdminHeaders(),
        body: JSON.stringify({}),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const payload = await response.json();
      appendOperation(`Recovered stale jobs: ${(payload.jobs || []).length}`);
      await refreshBackgroundJobs();
    } catch (error) {
      appendOperation(`Recover stale jobs failed: ${errorMessage(error)}`);
    } finally {
      elements.recoverStaleJobs.disabled = false;
    }
  }

  function renderBackgroundJobs(jobs) {
    state.backgroundJobs = Array.isArray(jobs) ? jobs : [];
    renderBackgroundJobSummary(state.backgroundJobs);
    elements.backgroundJobs.replaceChildren();

    if (state.backgroundJobs.length === 0) {
      elements.backgroundJobs.append(emptyText("No background jobs loaded."));
      return;
    }

    state.backgroundJobs.forEach((job) => {
      elements.backgroundJobs.append(backgroundJobRow(job));
    });
  }

  function renderBackgroundJobSummary(jobs) {
    const safeJobs = Array.isArray(jobs) ? jobs : [];
    const summary = {
      total: safeJobs.length,
      queued: safeJobs.filter((job) => job.status === "queued").length,
      running: safeJobs.filter((job) => job.status === "running").length,
      succeeded: safeJobs.filter((job) => job.status === "succeeded").length,
      needsAction: safeJobs.filter(
        (job) => ["failed", "canceled"].includes(job.status) || isBackgroundJobStale(job),
      ).length,
    };
    const cards = [
      ["Total", summary.total, ""],
      ["Queued", summary.queued, ""],
      ["Running", summary.running, ""],
      ["Needs Action", summary.needsAction, summary.needsAction > 0 ? "is-danger" : ""],
      ["Succeeded", summary.succeeded, "is-success"],
    ];

    elements.backgroundJobSummary.replaceChildren();
    cards.forEach(([label, value, modifier]) => {
      const card = document.createElement("div");
      card.className = ["ops-summary-card", modifier].filter(Boolean).join(" ");
      const title = document.createElement("span");
      title.textContent = label;
      const count = document.createElement("strong");
      count.textContent = String(value);
      card.append(title, count);
      elements.backgroundJobSummary.append(card);
    });
  }

  function backgroundJobRow(job) {
    const row = document.createElement("div");
    row.className = `job-row ${backgroundJobRowClass(job)}`;

    const body = document.createElement("div");
    body.className = "job-body";

    const heading = document.createElement("div");
    heading.className = "job-row-heading";
    const title = document.createElement("strong");
    title.textContent = job.task_type || "background.job";
    const badges = document.createElement("div");
    badges.className = "job-badges";
    badges.append(backgroundJobBadge(job.status || "unknown", job.status || "unknown"));
    if (isBackgroundJobStale(job)) {
      badges.append(backgroundJobBadge("stale", "stale"));
    }
    heading.append(title, badges);

    const meta = document.createElement("span");
    meta.className = "source-meta";
    meta.textContent = [
      `${job.attempts || 0}/${job.max_attempts || 0} attempts`,
      `priority ${job.priority ?? 0}`,
      backgroundJobAgeLabel(job.updated_at, "updated"),
    ]
      .filter(Boolean)
      .join(" · ");

    const timing = document.createElement("span");
    timing.className = "source-meta";
    timing.textContent = backgroundJobTimingSummary(job);

    const details = document.createElement("span");
    details.className = `job-detail ${job.error ? "is-danger" : ""}`;
    details.textContent = job.error
      ? `error: ${job.error}`
      : `result: ${backgroundJobResultSummary(job.result || {})}`;

    const payload = document.createElement("span");
    payload.className = "source-meta";
    payload.textContent = `payload: ${backgroundJobResultSummary(job.payload || {}, "{}")}`;

    body.append(heading, meta, timing, details, payload);
    row.append(body);

    const actions = document.createElement("div");
    actions.className = "job-actions button-row";
    if (job.status === "queued") {
      actions.append(backgroundJobActionButton("Cancel", () => cancelBackgroundJob(job.id)));
    }
    if (["failed", "canceled"].includes(job.status)) {
      actions.append(backgroundJobActionButton("Requeue", () => requeueBackgroundJob(job.id)));
    }
    if (isBackgroundJobStale(job)) {
      actions.append(backgroundJobActionButton("Recover Stale", recoverStaleJobs));
    }
    if (actions.children.length > 0) {
      row.append(actions);
    }

    return row;
  }

  function backgroundJobRowClass(job) {
    const statusClass = `is-${job.status || "unknown"}`;
    return isBackgroundJobStale(job) ? `${statusClass} is-stale` : statusClass;
  }

  function backgroundJobBadge(label, status) {
    const badge = document.createElement("span");
    badge.className = `status-badge is-${status}`;
    badge.textContent = label;
    return badge;
  }

  function backgroundJobActionButton(label, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary-button";
    button.textContent = label;
    button.addEventListener("click", onClick);
    return button;
  }

  function backgroundJobTimingSummary(job) {
    return [
      job.locked_by ? `worker ${job.locked_by}` : null,
      job.locked_at ? backgroundJobAgeLabel(job.locked_at, "locked") : null,
      job.available_at ? `available ${formatDateTime(job.available_at)}` : null,
      job.started_at ? backgroundJobAgeLabel(job.started_at, "started") : null,
      job.finished_at ? backgroundJobAgeLabel(job.finished_at, "finished") : null,
    ]
      .filter(Boolean)
      .join(" · ") || "not claimed by a worker";
  }

  function isBackgroundJobStale(job) {
    return Boolean(job.is_stale);
  }

  function backgroundJobAgeLabel(timestamp, label) {
    if (!timestamp) {
      return null;
    }
    const parsed = Date.parse(timestamp);
    if (!Number.isFinite(parsed)) {
      return `${label} ${timestamp}`;
    }
    const diffMs = Date.now() - parsed;
    if (diffMs < -60 * 1000) {
      return `${label} ${formatDateTime(timestamp)}`;
    }
    const minutes = Math.max(0, Math.floor(diffMs / (60 * 1000)));
    if (minutes < 1) {
      return `${label} just now`;
    }
    if (minutes < 60) {
      return `${label} ${minutes}m ago`;
    }
    const hours = Math.floor(minutes / 60);
    if (hours < 48) {
      return `${label} ${hours}h ago`;
    }
    return `${label} ${formatDateTime(timestamp)}`;
  }

  async function requeueBackgroundJob(jobId) {
    try {
      const response = await fetch(`/admin/jobs/${jobId}/requeue`, {
        method: "POST",
        headers: jsonAdminHeaders(),
        body: JSON.stringify({ reset_attempts: true }),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const job = await response.json();
      appendOperation(`Background job requeued: ${job.id}`);
      await refreshBackgroundJobs();
    } catch (error) {
      appendOperation(`Requeue background job failed: ${errorMessage(error)}`);
    }
  }

  async function cancelBackgroundJob(jobId) {
    try {
      const response = await fetch(`/admin/jobs/${jobId}/cancel`, {
        method: "POST",
        headers: adminHeaders(),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const job = await response.json();
      appendOperation(`Background job ${job.status}: ${job.id}`);
      await refreshBackgroundJobs();
    } catch (error) {
      appendOperation(`Cancel background job failed: ${errorMessage(error)}`);
    }
  }

  function backgroundJobResultSummary(result, emptyLabel = "waiting for worker") {
    const entries = Object.entries(result || {});
    if (entries.length === 0) {
      return emptyLabel;
    }
    return entries
      .slice(0, 4)
      .map(([key, value]) => `${key}: ${String(value)}`)
      .join(" · ");
  }

  async function refreshLearnerContext() {
    await refreshSources();
  }

  function updateLearnerChatStatus(fallbackText = null) {
    if (fallbackText) {
      elements.learnerChatStatus.textContent = fallbackText;
      return;
    }

    const sourceCount = state.documents.length;
    elements.learnerChatStatus.textContent =
      sourceCount > 0
        ? `${sourceCount} 份課程教材可供查詢，回答都會附上引用來源。`
        : "回答都來自課程教材，並附上引用來源。";
  }

  async function refreshImportJobs() {
    try {
      const response = await fetch("/imports/status", {
        headers: adminHeaders(),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const payload = await response.json();
      renderImportJobs(payload.jobs || []);
    } catch (error) {
      state.importJobs = [];
      renderImportDiagnosticsSummary([]);
      elements.importJobs.replaceChildren(emptyText(`Import jobs unavailable: ${errorMessage(error)}`));
    }
  }

  function renderImportJobs(jobs) {
    state.importJobs = Array.isArray(jobs) ? jobs : [];
    renderImportDiagnosticsSummary(state.importJobs);
    elements.importJobs.replaceChildren();

    if (state.importJobs.length === 0) {
      elements.importJobs.append(emptyText("No import jobs loaded."));
      return;
    }

    state.importJobs.slice(0, 10).forEach((job) => {
      elements.importJobs.append(renderImportJobRow(job));
    });
  }

  function renderImportDiagnosticsSummary(jobs) {
    const safeJobs = Array.isArray(jobs) ? jobs : [];
    const summary = {
      total: safeJobs.length,
      active: safeJobs.filter((job) => ["queued", "running"].includes(job.status)).length,
      failed: safeJobs.filter((job) => job.status === "failed").length,
      warnings: safeJobs.filter((job) => importJobWarnings(job).length > 0).length,
      duplicates: safeJobs.filter((job) => job.status === "duplicate").length,
    };
    const cards = [
      ["Loaded", summary.total, ""],
      ["Active", summary.active, summary.active > 0 ? "is-warning" : ""],
      ["Failed", summary.failed, summary.failed > 0 ? "is-danger" : ""],
      ["Warnings", summary.warnings, summary.warnings > 0 ? "is-warning" : ""],
      ["Duplicates", summary.duplicates, ""],
    ];

    elements.importDiagnosticsSummary.replaceChildren();
    cards.forEach(([label, value, modifier]) => {
      const card = document.createElement("div");
      card.className = ["ops-summary-card", modifier].filter(Boolean).join(" ");
      const title = document.createElement("span");
      title.textContent = label;
      const count = document.createElement("strong");
      count.textContent = String(value);
      card.append(title, count);
      elements.importDiagnosticsSummary.append(card);
    });
  }

  function renderImportJobRow(job) {
    const metadata = job.metadata || {};
    const warnings = importJobWarnings(job);
    const row = document.createElement("div");
    row.className = `job-row is-${job.status || "unknown"}`;

    const body = document.createElement("div");
    body.className = "job-body";

    const heading = document.createElement("div");
    heading.className = "job-row-heading";
    const title = document.createElement("strong");
    title.textContent = job.filename || "Uploaded source";
    const badges = document.createElement("div");
    badges.className = "job-badges";
    badges.append(backgroundJobBadge(job.status || "unknown", job.status || "unknown"));
    if (warnings.length > 0) {
      badges.append(backgroundJobBadge("warnings", "warning"));
    }
    heading.append(title, badges);

    const meta = document.createElement("span");
    meta.className = "source-meta";
    meta.textContent = [job.kind, formatDateTime(job.updated_at)].filter(Boolean).join(" · ");

    const details = document.createElement("span");
    details.className = "source-meta";
    details.textContent = importJobMetadataDetails(job);

    const artifacts = document.createElement("span");
    artifacts.className = "source-meta";
    artifacts.textContent = importJobArtifactDetails(job);

    const backgroundJob = document.createElement("span");
    backgroundJob.className = "source-meta";
    backgroundJob.textContent = metadata.background_job_id
      ? `background job: ${metadata.background_job_id}`
      : "background job: not queued";

    body.append(heading, meta, details, artifacts, backgroundJob);

    if (warnings.length > 0) {
      const warning = document.createElement("span");
      warning.className = "job-detail is-warning";
      warning.textContent = `warnings: ${warnings.join(", ")}`;
      body.append(warning);
    }
    if (job.error) {
      const error = document.createElement("span");
      error.className = "job-detail is-danger";
      error.textContent = `error: ${job.error}`;
      body.append(error);
    }

    row.append(body);

    if (job.status === "failed") {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "secondary-button";
      retry.textContent = "Retry";
      retry.addEventListener("click", () => retryImportJob(job.id));
      row.append(retry);
    }

    return row;
  }

  function importJobMetadataDetails(job) {
    const metadata = job.metadata || {};
    return [
      `type: ${metadata.detected_file_type || metadata.extension || "--"}`,
      metadata.content_type ? `content type: ${metadata.content_type}` : "content type: --",
      `size: ${formatBytes(job.size_bytes)}`,
      metadata.markdown_bytes ? `markdown: ${formatBytes(metadata.markdown_bytes)}` : null,
      metadata.path_strategy ? `path: ${metadata.path_strategy}` : null,
      metadata.processed_async ? "processed async" : null,
      metadata.index_after_import === false ? "index disabled" : "index after import",
      job.content_hash ? `hash: ${String(job.content_hash).slice(0, 12)}` : null,
    ]
      .filter(Boolean)
      .join(" · ");
  }

  function importJobArtifactDetails(job) {
    const metadata = job.metadata || {};
    return [
      metadata.original_filename ? `original: ${metadata.original_filename}` : null,
      metadata.raw_filename ? `raw: ${metadata.raw_filename}` : null,
      metadata.canonical_filename ? `canonical: ${metadata.canonical_filename}` : null,
      !metadata.canonical_filename && job.canonical_path ? `canonical: ${job.canonical_path}` : null,
    ]
      .filter(Boolean)
      .join(" · ") || "artifacts: --";
  }

  function importJobWarnings(job) {
    const metadata = job.metadata || {};
    return Array.isArray(metadata.import_warnings)
      ? metadata.import_warnings.filter(Boolean).map(String)
      : [];
  }

  async function refreshAuditEvents() {
    const params = new URLSearchParams();
    params.set("limit", String(auditLimit()));
    if (elements.auditEventType.value) {
      params.set("event_type", elements.auditEventType.value);
    }
    if (elements.auditOutcome.value) {
      params.set("outcome", elements.auditOutcome.value);
    }
    if (elements.auditActorType.value) {
      params.set("actor_type", elements.auditActorType.value);
    }

    try {
      const response = await fetch(`/admin/audit-events?${params}`, {
        headers: adminHeaders(),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const payload = await response.json();
      renderAuditEvents(payload.events || []);
    } catch (error) {
      state.auditEvents = [];
      elements.auditEvents.replaceChildren(emptyText(`Audit events unavailable: ${errorMessage(error)}`));
    }
  }

  // 審計日誌表格：點表頭排序（再點一次反向）。
  const AUDIT_COLUMNS = [
    { key: "created_at", label: "時間" },
    { key: "event_type", label: "事件" },
    { key: "outcome", label: "結果" },
    { key: "actor_type", label: "角色" },
    { key: "actor_id", label: "帳號" },
    { key: "path", label: "路徑" },
    { key: "metadata", label: "詳細", sortable: false },
  ];
  const auditSort = { key: "created_at", dir: "desc" };

  function renderAuditEvents(events) {
    state.auditEvents = Array.isArray(events) ? events : [];
    renderAuditTable();
  }

  function renderAuditTable() {
    elements.auditEvents.replaceChildren();

    if (state.auditEvents.length === 0) {
      elements.auditEvents.append(emptyText("No audit events loaded."));
      return;
    }

    const sorted = [...state.auditEvents].sort((left, right) => {
      const a = String(left[auditSort.key] ?? "");
      const b = String(right[auditSort.key] ?? "");
      const compared = a.localeCompare(b);
      return auditSort.dir === "asc" ? compared : -compared;
    });

    const table = document.createElement("table");
    table.className = "admin-table";
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    AUDIT_COLUMNS.forEach((column) => {
      const cell = document.createElement("th");
      if (column.sortable === false) {
        cell.textContent = column.label;
      } else {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "table-sort-button";
        const active = auditSort.key === column.key;
        button.textContent = active
          ? `${column.label} ${auditSort.dir === "asc" ? "▲" : "▼"}`
          : column.label;
        button.addEventListener("click", () => {
          if (auditSort.key === column.key) {
            auditSort.dir = auditSort.dir === "asc" ? "desc" : "asc";
          } else {
            auditSort.key = column.key;
            auditSort.dir = "desc";
          }
          renderAuditTable();
        });
        cell.append(button);
      }
      headRow.append(cell);
    });
    head.append(headRow);
    table.append(head);

    const body = document.createElement("tbody");
    sorted.forEach((auditEvent) => {
      const row = document.createElement("tr");
      row.className = `is-${auditEvent.outcome || "unknown"}`;
      const values = [
        formatDateTime(auditEvent.created_at) || "--",
        auditEvent.event_type || "--",
        auditEvent.outcome || "--",
        auditEvent.actor_type || "--",
        auditEvent.actor_id || "--",
        auditEvent.path || "--",
        auditMetadataSummary(auditEvent.metadata || {}),
      ];
      values.forEach((value, index) => {
        const cell = document.createElement("td");
        cell.textContent = String(value);
        if (AUDIT_COLUMNS[index].key === "metadata") {
          cell.className = "audit-metadata-cell";
        }
        row.append(cell);
      });
      body.append(row);
    });
    table.append(body);
    elements.auditEvents.append(table);
  }

  function auditLimit() {
    const rawLimit = Number(elements.auditLimit.value || 50);
    const normalizedLimit = Number.isFinite(rawLimit) ? Math.round(rawLimit) : 50;
    const clampedLimit = Math.min(100, Math.max(1, normalizedLimit));
    elements.auditLimit.value = String(clampedLimit);
    return clampedLimit;
  }

  function auditMetadataSummary(metadata) {
    const entries = Object.entries(metadata || {});
    if (entries.length === 0) {
      return "metadata: {}";
    }
    return entries
      .map(([key, value]) => `${key}: ${String(value)}`)
      .join(" · ");
  }

  async function retryImportJob(jobId) {
    try {
      appendOperation("Retrying import job...");
      const response = await fetch(`/imports/${jobId}/retry`, {
        method: "POST",
        headers: adminHeaders(),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const payload = await response.json();
      appendOperation(`Import retry ${payload.status}: ${payload.filename}`);
      await refreshImportJobs();
      await refreshBackgroundJobs();
    } catch (error) {
      appendOperation(`Import retry failed: ${errorMessage(error)}`);
      await refreshImportJobs();
    }
  }

  async function createEvalCase(event) {
    event.preventDefault();
    const name = elements.evalName.value.trim();
    const query = elements.evalQuery.value.trim();
    if (!name || !query) {
      setEvalStatus("Eval case needs a name and query.");
      appendOperation("Eval case needs a name and query.");
      return;
    }

    try {
      const response = await fetch("/evals/cases", {
        method: "POST",
        headers: jsonAdminHeaders(),
        body: JSON.stringify({
          name,
          query,
          expected_decision: elements.evalDecision.value,
          expected_source_ids: splitList(elements.evalSources.value),
          tags: splitList(elements.evalTags.value),
        }),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      elements.evalForm.reset();
      setEvalStatus(`Eval case added: ${name}`);
      appendOperation(`Eval case added: ${name}`);
      await refreshEvals();
    } catch (error) {
      const message = `Eval case failed: ${errorMessage(error)}`;
      setEvalStatus(message);
      appendOperation(message);
    }
  }

  async function refreshEvals() {
    try {
      const casesResponse = await fetch("/evals/cases", {
        headers: adminHeaders(),
      });
      if (!casesResponse.ok) {
        throw new Error(await responseError(casesResponse));
      }
      const casesPayload = await casesResponse.json();
      renderEvalCases(casesPayload.cases || []);
      await refreshLatestEvalRun();
      await refreshEvalReport();
      await refreshFeedbackPromotions();
      setEvalStatus(`Eval cases loaded: ${(casesPayload.cases || []).length}`);
    } catch (error) {
      const message = `Eval cases unavailable: ${errorMessage(error)}`;
      state.evalCases = [];
      state.evalRun = null;
      state.evalReport = null;
      state.feedbackItems = [];
      elements.evalCases.replaceChildren(emptyText(message));
      elements.evalResults.replaceChildren(emptyText("No eval run loaded."));
      elements.evalReport.replaceChildren(emptyText("No eval report loaded."));
      elements.evalRecentRuns.replaceChildren(emptyText("No recent runs loaded."));
      elements.evalWorstCases.replaceChildren(emptyText("No worst cases loaded."));
      elements.feedbackPromotions.replaceChildren(emptyText("No feedback loaded."));
      renderEvalSummary(null);
      setEvalStatus(message);
    }
  }

  async function refreshLatestEvalRun() {
    try {
      const payload = await getJsonWithHeaders("/evals/runs/latest", adminHeaders());
      state.evalRun = payload;
      renderEvalRun(payload);
    } catch (error) {
      state.evalRun = null;
      elements.evalResults.replaceChildren(emptyText("No eval run loaded."));
      renderEvalSummary(null);
      setEvalStatus("No eval run loaded.");
    }
  }

  async function runEvals() {
    elements.runEvals.disabled = true;
    try {
      const response = await fetch("/evals/run", {
        method: "POST",
        headers: jsonAdminHeaders(),
        body: JSON.stringify({
          strategy: CHAT_STRATEGY,
          limit: CHAT_LIMIT,
        }),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const payload = await response.json();
      const message = `Eval ${payload.status}: ${payload.stats.passed}/${payload.stats.total} passed`;
      setEvalStatus(message);
      appendOperation(message);
      state.evalRun = payload;
      renderEvalRun(payload);
      await refreshEvalReport();
    } catch (error) {
      const message = `Eval run failed: ${errorMessage(error)}`;
      setEvalStatus(message);
      appendOperation(message);
    } finally {
      elements.runEvals.disabled = false;
    }
  }

  async function seedEvals() {
    elements.seedEvals.disabled = true;
    try {
      const response = await fetch("/evals/seed", {
        method: "POST",
        headers: jsonAdminHeaders(),
        body: JSON.stringify({}),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const payload = await response.json();
      const message = `Seeded evals: ${payload.summary.created} created, ${payload.summary.updated} updated`;
      setEvalStatus(message);
      appendOperation(message);
      renderEvalCases(payload.cases || []);
      await refreshEvalReport();
    } catch (error) {
      const message = `Eval seed failed: ${errorMessage(error)}`;
      setEvalStatus(message);
      appendOperation(message);
    } finally {
      elements.seedEvals.disabled = false;
    }
  }

  async function refreshEvalReport() {
    try {
      const payload = await getJsonWithHeaders("/evals/report", adminHeaders());
      state.evalReport = payload;
      renderEvalReport(payload);
    } catch (error) {
      state.evalReport = null;
      elements.evalReport.replaceChildren(emptyText("No eval report loaded."));
      elements.evalRecentRuns.replaceChildren(emptyText("No recent runs loaded."));
      elements.evalWorstCases.replaceChildren(emptyText("No worst cases loaded."));
    }
  }

  async function refreshFeedbackPromotions() {
    try {
      const payload = await getJsonWithHeaders("/feedback", adminHeaders());
      renderFeedbackPromotions(payload.feedback || []);
    } catch (error) {
      state.feedbackItems = [];
      elements.feedbackPromotions.replaceChildren(emptyText("No feedback loaded."));
    }
  }

  function renderEvalCases(cases) {
    state.evalCases = Array.isArray(cases) ? cases : [];
    elements.evalCases.replaceChildren();

    if (state.evalCases.length === 0) {
      elements.evalCases.append(emptyText("No eval cases loaded."));
      return;
    }

    state.evalCases.forEach((evalCase) => {
      const row = document.createElement("div");
      row.className = "eval-row";
      const title = document.createElement("strong");
      title.textContent = evalCase.name || evalCase.query;
      const meta = document.createElement("span");
      meta.className = "source-meta";
      meta.textContent = [
        evalCase.expected_decision,
        (evalCase.expected_source_ids || []).join(", "),
        (evalCase.tags || []).join(", "),
      ]
        .filter(Boolean)
        .join(" · ");
      row.append(title, meta);
      elements.evalCases.append(row);
    });
  }

  function renderEvalRun(run) {
    elements.evalResults.replaceChildren();
    renderEvalSummary(run);
    const results = run && Array.isArray(run.results) ? run.results : [];
    if (results.length === 0) {
      elements.evalResults.append(emptyText("No eval run loaded."));
      return;
    }

    results.forEach((result) => {
      const row = document.createElement("div");
      row.className = `eval-row is-${result.passed ? "passed" : "failed"}`;
      const title = document.createElement("strong");
      title.textContent = `${result.passed ? "PASS" : "FAIL"} · ${result.name || result.query}`;
      const meta = document.createElement("span");
      meta.className = "source-meta";
      meta.textContent = [
        `${result.actual_decision}`,
        `score ${formatPercent(result.score)}`,
        `retrieval ${formatPercent(result.metrics && result.metrics.retrieval_recall)}`,
        `citation ${formatPercent(result.metrics && result.metrics.citation_recall)}`,
      ].join(" · ");
      row.append(title, meta);
      elements.evalResults.append(row);
    });
  }

  function renderEvalReport(report) {
    elements.evalReport.replaceChildren();
    elements.evalRecentRuns.replaceChildren();
    elements.evalWorstCases.replaceChildren();
    const totals = report && report.totals ? report.totals : {};
    const latest = report && report.latest_run ? report.latest_run : null;
    const cards = [
      ["Cases", `${totals.active_cases || 0}/${totals.total_cases || 0} active`],
      ["Runs", totals.total_runs || 0],
      ["Latest", latest ? `${formatPercent(latest.stats && latest.stats.pass_rate)} pass` : "--"],
      ["Failures", latest && latest.stats ? latest.stats.failed || 0 : 0],
    ];
    cards.forEach(([label, value]) => {
      const row = document.createElement("div");
      row.className = "report-row";
      const title = document.createElement("strong");
      title.textContent = label;
      const meta = document.createElement("span");
      meta.className = "source-meta";
      meta.textContent = String(value);
      row.append(title, meta);
      elements.evalReport.append(row);
    });

    const failures = report && Array.isArray(report.latest_failures) ? report.latest_failures : [];
    failures.slice(0, 3).forEach((failure) => {
      const row = document.createElement("div");
      row.className = "report-row is-failed";
      const title = document.createElement("strong");
      title.textContent = `FAIL · ${failure.name || failure.query}`;
      const meta = document.createElement("span");
      meta.className = "source-meta";
      meta.textContent = `missing ${(failure.missing_source_ids || []).join(", ") || "--"}`;
      row.append(title, meta);
      elements.evalReport.append(row);
    });

    const recentRuns = report && Array.isArray(report.recent_runs) ? report.recent_runs : [];
    if (recentRuns.length === 0) {
      elements.evalRecentRuns.append(emptyText("No recent runs loaded."));
    } else {
      recentRuns.slice(0, 5).forEach((run) => {
        const row = document.createElement("div");
        row.className = `report-row is-${run.status || "unknown"}`;
        const title = document.createElement("strong");
        title.textContent = `${run.status || "unknown"} · ${formatPercent(run.stats && run.stats.pass_rate)} pass`;
        const meta = document.createElement("span");
        meta.className = "source-meta";
        meta.textContent = [
          run.trigger,
          run.strategy,
          run.stats ? `${run.stats.passed || 0}/${run.stats.total || 0}` : null,
          formatDateTime(run.created_at),
        ]
          .filter(Boolean)
          .join(" · ");
        row.append(title, meta);
        elements.evalRecentRuns.append(row);
      });
    }

    const worstCases = report && Array.isArray(report.worst_cases) ? report.worst_cases : [];
    if (worstCases.length === 0) {
      elements.evalWorstCases.append(emptyText("No worst cases loaded."));
    } else {
      worstCases.slice(0, 5).forEach((evalCase) => {
        const row = document.createElement("div");
        row.className = `report-row ${evalCase.failed ? "is-failed" : "is-passed"}`;
        const title = document.createElement("strong");
        title.textContent = evalCase.name || evalCase.query || evalCase.case_id;
        const meta = document.createElement("span");
        meta.className = "source-meta";
        meta.textContent = [
          `${evalCase.failed || 0}/${evalCase.total || 0} failed`,
          `${formatPercent(evalCase.pass_rate)} pass`,
        ].join(" · ");
        row.append(title, meta);
        elements.evalWorstCases.append(row);
      });
    }
  }

  function renderFeedbackPromotions(feedbackItems) {
    state.feedbackItems = Array.isArray(feedbackItems) ? feedbackItems : [];
    elements.feedbackPromotions.replaceChildren();
    if (state.feedbackItems.length === 0) {
      elements.feedbackPromotions.append(emptyText("No feedback loaded."));
      return;
    }

    state.feedbackItems.slice(0, 8).forEach((feedback) => {
      const row = document.createElement("div");
      row.className = "feedback-row";
      const title = document.createElement("strong");
      title.textContent = feedback.query || "Feedback without query";
      const meta = document.createElement("span");
      meta.className = "source-meta";
      meta.textContent = [
        `rating ${feedback.rating}`,
        feedback.reason,
        feedback.expected_source,
      ]
        .filter(Boolean)
        .join(" · ");
      const action = document.createElement("button");
      action.className = "text-button";
      action.type = "button";
      action.textContent = "Promote";
      action.addEventListener("click", () => promoteFeedback(feedback.id));
      row.append(title, meta, action);
      elements.feedbackPromotions.append(row);
    });
  }

  async function promoteFeedback(feedbackId) {
    try {
      const response = await fetch("/evals/cases/promote-feedback", {
        method: "POST",
        headers: jsonAdminHeaders(),
        body: JSON.stringify({ feedback_id: feedbackId, tags: ["feedback", "regression"] }),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const payload = await response.json();
      const message = `Promoted feedback: ${payload.name}`;
      setEvalStatus(message);
      appendOperation(message);
      await refreshEvals();
    } catch (error) {
      const message = `Feedback promotion failed: ${errorMessage(error)}`;
      setEvalStatus(message);
      appendOperation(message);
    }
  }

  function renderEvalSummary(run) {
    const stats = run && run.stats ? run.stats : null;
    elements.evalSummary.replaceChildren(
      statusRow("Status", run ? run.status : "Unknown"),
      statusRow("Pass Rate", stats ? formatPercent(stats.pass_rate) : "--"),
      statusRow("Cases", stats ? stats.total : "--"),
    );
  }

  function statusRow(label, value) {
    const wrapper = document.createElement("div");
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    term.textContent = label;
    detail.textContent = String(value);
    wrapper.append(term, detail);
    return wrapper;
  }

  async function getJson(path) {
    const response = await fetch(path);
    if (!response.ok) {
      throw new Error(await responseError(response));
    }
    return response.json();
  }

  async function getJsonWithHeaders(path, headers) {
    const response = await fetch(path, { headers, credentials: "same-origin" });
    if (!response.ok) {
      throw new Error(await responseError(response));
    }
    return response.json();
  }

  async function responseError(response) {
    try {
      const payload = await response.json();
      if (payload.detail) {
        return Array.isArray(payload.detail)
          ? payload.detail.map((item) => item.msg || JSON.stringify(item)).join("; ")
          : String(payload.detail);
      }
    } catch (error) {
      return `${response.status} ${response.statusText}`;
    }
    return `${response.status} ${response.statusText}`;
  }

  function safeJson(value) {
    try {
      return JSON.parse(value || "{}");
    } catch (error) {
      return {};
    }
  }

  function errorMessage(error) {
    return error instanceof Error ? error.message : String(error);
  }

  function appendOperation(message) {
    const timestamp = new Date().toLocaleTimeString();
    const current = elements.operationLog.textContent.trim();
    const nextLine = `[${timestamp}] ${message}`;
    elements.operationLog.textContent =
      current && current !== "No admin operations yet." ? `${current}\n${nextLine}` : nextLine;
  }

  function setEvalStatus(message) {
    elements.evalStatus.textContent = message;
  }

  function adminHeaders() {
    const adminKey = sharedAdminKey();
    return authHeaders(true, adminKey ? { "X-KB-Admin-Key": adminKey } : {});
  }

  function jsonAdminHeaders() {
    return {
      "Content-Type": "application/json",
      ...adminHeaders(),
    };
  }

  function platformJsonHeaders() {
    return authHeaders(true, { "Content-Type": "application/json" });
  }

  function authHeaders(unsafe = false, headers = {}) {
    const nextHeaders = { ...headers };
    if (unsafe && state.auth.csrfToken) {
      nextHeaders["X-KB-CSRF-Token"] = state.auth.csrfToken;
    }
    return nextHeaders;
  }

  function splitList(value) {
    return String(value || "")
      .split(/[\n,]/)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function formatPercent(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return "--";
    }
    return `${Math.round(number * 100)}%`;
  }

  function formatBytes(value) {
    const number = Number(value);
    if (!Number.isFinite(number) || number < 0) {
      return "--";
    }
    if (number < 1024) {
      return `${number} B`;
    }
    return `${(number / 1024).toFixed(1)} KB`;
  }

  function formatDateTime(value) {
    if (!value) {
      return null;
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return String(value);
    }
    return date.toLocaleString();
  }

  function emptyText(text) {
    const node = document.createElement("p");
    node.className = "muted";
    node.textContent = text;
    return node;
  }

  document.addEventListener("DOMContentLoaded", init);
})();
