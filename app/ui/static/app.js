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
    retrievalDiagnostics: null,
    answerQuality: null,
    chatBusy: false,
    indexStatus: null,
    auth: {
      authRequired: false,
      authenticated: true,
      username: null,
      csrfToken: null,
    },
  };

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));

  const elements = {
    tabs: $$("[data-tab]"),
    panels: $$("[data-panel]"),
    chatForm: $("#chat-form"),
    chatQuery: $("#chat-query"),
    chatLimit: $("#chat-limit"),
    chatStrategy: $("#chat-strategy"),
    chatLog: $("#chat-log"),
    chatEmptyState: $("#chat-empty-state"),
    chatComposerStatus: $("#chat-composer-status"),
    chatSubmit: $("#chat-submit"),
    learnerChatStatus: $("#learner-chat-status"),
    samplePrompts: $$("[data-sample-prompt]"),
    selectedSources: $("#answer-sources"),
    selectedSourceCount: $("#selected-source-count"),
    answerQuality: $("#answer-quality"),
    markdownPreview: $("#markdown-preview"),
    previewSourceMeta: $("#preview-source-meta"),
    sourceList: $("#source-list"),
    sourceTable: $("#source-table"),
    documentAdminKey: $("#document-admin-key"),
    refreshDocuments: $("#refresh-documents"),
    adminDocuments: $("#admin-documents"),
    graphCanvas: $("#graph-canvas"),
    graphEmpty: $("#graph-empty"),
    graphSearch: $("#graph-search"),
    loadGraph: $("#load-graph"),
    graphViewCluster: $("#graph-view-cluster"),
    graphViewRadial: $("#graph-view-radial"),
    graphViewOrder: $("#graph-view-order"),
    refreshSources: $("#refresh-sources"),
    refreshStatus: $("#refresh-status"),
    statusPill: $("#index-status-pill"),
    statusGrid: $("#index-status"),
    uploadForm: $("#upload-form"),
    adminKey: $("#admin-key"),
    auditAdminKey: $("#audit-admin-key"),
    auditEventType: $("#audit-event-type"),
    auditOutcome: $("#audit-outcome"),
    auditActorType: $("#audit-actor-type"),
    auditLimit: $("#audit-limit"),
    refreshAudit: $("#refresh-audit"),
    auditEvents: $("#audit-events"),
    evalAdminKey: $("#eval-admin-key"),
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
    opsAdminKey: $("#ops-admin-key"),
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
    themeToggle: $("#theme-toggle"),
    workbench: $("[data-app]"),
    adminOnlySurfaces: $$("[data-admin-only]"),
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
      csrfToken: payload.csrf_token || null,
    };

    const blocked = state.auth.authRequired && !state.auth.authenticated;
    elements.platformLogin.hidden = !blocked;
    elements.workbench.classList.toggle("is-auth-blocked", blocked);
    elements.platformLogout.hidden = !state.auth.authRequired || !state.auth.authenticated;
    applyAccessPolicy();
    elements.platformAuthStatus.textContent = state.auth.authenticated
      ? `Signed in${state.auth.username ? ` as ${state.auth.username}` : ""}.`
      : "Sign in to continue.";

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

    if (tabName === "ops" && !state.providerObservability) {
      refreshProviderObservability();
    }

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
    return state.auth.authRequired && state.auth.authenticated;
  }

  function applyAccessPolicy() {
    const restricted = isRestrictedLearner();
    elements.adminOnlySurfaces.forEach((surface) => {
      if (restricted || !surface.matches("[data-panel]")) {
        surface.hidden = restricted;
      }
      surface.setAttribute("aria-hidden", String(restricted));
    });

    if (restricted && !tabIsAvailable(activeTabName())) {
      activateTab("chat");
    }
  }

  function bindChat() {
    elements.chatQuery.addEventListener("keydown", handleChatKeydown);
    elements.chatForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const query = elements.chatQuery.value.trim();
      if (!query || state.chatBusy) {
        return;
      }

      clearChatEmptyState();
      addMessage("user", query);
      const answerNode = addMessage("assistant", "");
      elements.chatQuery.value = "";
      setSelectedSources([]);
      renderAnswerQuality(null);
      renderStreamingStatus(answerNode, "Looking through course sources...");
      setChatBusy(true, "Looking through course sources...");

      try {
        await streamChat(query, answerNode);
      } catch (error) {
        answerNode.textContent = errorMessage(error);
        renderAnswerFooter(answerNode, {
          answer_quality: {
            answer_valid: false,
            citation_errors: [errorMessage(error)],
          },
        });
      } finally {
        setChatBusy(false, "Ready for your next question.");
      }
    });
  }

  function bindSamplePrompts() {
    elements.samplePrompts.forEach((button) => {
      button.addEventListener("click", () => {
        elements.chatQuery.value = button.dataset.samplePrompt || button.textContent.trim();
        elements.chatQuery.focus();
        elements.chatComposerStatus.textContent = "Review or send the suggested question.";
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
    elements.chatStrategy.disabled = isBusy;
    elements.chatLimit.disabled = isBusy;
    elements.chatSubmit.disabled = isBusy;
    elements.samplePrompts.forEach((button) => {
      button.disabled = isBusy;
    });
    elements.chatForm.classList.toggle("is-busy", isBusy);
    elements.chatComposerStatus.textContent = statusText || (isBusy ? "Working..." : "Ready.");
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
      strategy: elements.chatStrategy.value,
      limit: chatLimit(),
    };
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
        setSelectedSources(payload.selected_sources || payload.sources || []);
        renderAnswerQuality({
          retrieval_diagnostics: payload.retrieval_diagnostics,
        });
        if (!receivedToken) {
          const sourceCount = state.selectedSources.length;
          renderStreamingStatus(
            answerNode,
            sourceCount === 1
              ? "Found 1 relevant source."
              : `Found ${sourceCount} relevant sources.`,
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
        mergeCitedSources(payload.sources);
        renderAnswerQuality(payload);
        renderAnswerFooter(answerNode, payload);
      }
    });
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

  function addMessage(role, text) {
    const wrapper = document.createElement("div");
    wrapper.className = `message ${role}`;

    const label = document.createElement("span");
    label.className = "message-label";
    label.textContent = role === "user" ? "You" : "Course Assistant";

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

    renderAnswerCitations(answerNode, state.selectedSources);
    card.querySelector(".trust-badge")?.remove();
    card.querySelector(".answer-footer")?.remove();

    const trust = document.createElement("span");
    const trustState = answerTrustState(payload);
    trust.className = `trust-badge is-${trustState}`;
    trust.textContent = answerTrustText(payload, state.selectedSources);
    card.prepend(trust);

    const footer = document.createElement("div");
    footer.className = "answer-footer";
    renderSourceChips(footer, state.selectedSources);
    renderFeedbackRow(footer, payload, state.selectedSources);
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
      fragments.push(inlineCitationButton(range.source, range.displayIndex));
      cursor = range.end;
    });
    if (cursor < answer.length) {
      fragments.push(document.createTextNode(answer.slice(cursor)));
    }
    answerNode.replaceChildren(...fragments);
  }

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
      ? "What answer did you expect?"
      : "What should be improved?";

    const sourceSelect = document.createElement("select");
    sourceSelect.setAttribute("aria-label", "Expected source");
    const emptyOption = document.createElement("option");
    emptyOption.value = "";
    emptyOption.textContent = "Expected source";
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

    const submit = feedbackActionButton("Send feedback", () =>
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
      status.textContent = "Saving feedback...";
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
    if (quality.answer_valid === false) {
      return "回答需要來源審查";
    }
    if (quality.cannot_confirm_reason || payload.decision === "cannot_confirm") {
      return "知識庫無法確認這個問題";
    }

    const sourceCount = Array.isArray(sources) ? sources.length : 0;
    if (sourceCount > 0) {
      return `✓ 依據 ${sourceCount} 個課程段落回答`;
    }
    return "回答未引用課程段落";
  }

  function answerTrustState(payload) {
    const quality = payload.answer_quality || {};
    if (quality.answer_valid === false) {
      return "danger";
    }
    if (quality.cannot_confirm_reason || payload.decision === "cannot_confirm") {
      return "warn";
    }
    return "ok";
  }

  function setSelectedSources(sources) {
    state.selectedSources = Array.isArray(sources) ? sources : [];
    elements.selectedSources.replaceChildren();
    elements.selectedSourceCount.textContent = String(state.selectedSources.length);

    if (state.selectedSources.length === 0) {
      elements.selectedSources.append(emptyText("這次回答沒有引用來源。"));
      resetPreviewSourceMeta();
      elements.markdownPreview.textContent = "Select a source to preview markdown.";
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
      meta.textContent = [
        source.source_id,
        source.strategy,
        typeof source.score === "number" ? source.score.toFixed(3) : null,
        scoreBreakdownText(source),
      ]
        .filter(Boolean)
        .join(" · ");

      row.append(title, meta);
      elements.selectedSources.append(row);

      if (index === 0) {
        previewCandidate(source);
      }
    });
  }

  function mergeCitedSources(sources) {
    const citedSources = Array.isArray(sources) ? sources : [];
    const knownSourceIds = new Set(
      state.selectedSources.map((source) => source.source_id),
    );
    const newSources = citedSources.filter(
      (source) => source && source.source_id && !knownSourceIds.has(source.source_id),
    );
    if (newSources.length === 0) {
      return;
    }
    setSelectedSources([...state.selectedSources, ...newSources]);
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
    const heading = source.heading || source.source_id || "Source";
    const body = source.body_md || "No markdown body returned for this source.";
    const diagnostics = scoreBreakdownText(source);
    renderPreviewSourceMeta({
      title: heading,
      summary: source.source_id || source.filename || "Answer source",
      kind: "引用來源",
    });
    elements.markdownPreview.textContent = [
      heading,
      diagnostics ? `Diagnostics: ${diagnostics}` : null,
      body,
    ]
      .filter(Boolean)
      .join("\n\n");
    setActiveSourceRow(source.source_id);
    renderGraphCrossLink(source.source_id, heading, body);
  }

  function setActiveSourceRow(sourceId) {
    $$("#answer-sources .source-row").forEach((row) => {
      row.classList.toggle("is-active", Boolean(sourceId) && row.dataset.sourceId === sourceId);
    });
  }

  function renderAnswerQuality(payload) {
    if (!payload) {
      state.retrievalDiagnostics = null;
      state.answerQuality = null;
      elements.answerQuality.replaceChildren(
        statusRow("Decision", "Unknown"),
        statusRow("Grounding", "--"),
        statusRow("Retrieval", "--"),
      );
      return;
    }

    if (payload.retrieval_diagnostics) {
      state.retrievalDiagnostics = payload.retrieval_diagnostics;
    }
    if (payload.answer_quality) {
      state.answerQuality = payload.answer_quality;
    }

    const diagnostics = state.retrievalDiagnostics || {};
    const quality = state.answerQuality || {};
    const grounding = quality.answer_valid === false
      ? `invalid: ${(quality.citation_errors || []).join(", ") || "citation validation"}`
      : quality.cannot_confirm_reason
        ? `cannot confirm: ${quality.cannot_confirm_reason}`
        : quality.answer_valid === true
          ? "valid citations"
          : "--";
    const retrieval = diagnostics.accepted_count == null
      ? "--"
      : `${diagnostics.accepted_count} selected · ${diagnostics.rejected_count || 0} rejected`;

    elements.answerQuality.replaceChildren(
      statusRow("Decision", payload.decision || "--"),
      statusRow("Grounding", grounding),
      statusRow("Retrieval", retrieval),
      statusRow("Top Score", diagnostics.top_score == null ? "--" : Number(diagnostics.top_score).toFixed(3)),
    );
  }

  function scoreBreakdownText(source) {
    const debugScores = source.debug_scores || {};
    const parts = [
      debugScores.lexical_score != null ? `lexical ${Number(debugScores.lexical_score).toFixed(3)}` : null,
      debugScores.vector_score != null ? `vector ${Number(debugScores.vector_score).toFixed(3)}` : null,
      debugScores.source_priority_boost != null
        ? `priority +${Number(debugScores.source_priority_boost).toFixed(3)}`
        : null,
    ];
    return parts.filter(Boolean).join(" · ");
  }

  function bindSources() {
    elements.refreshSources.addEventListener("click", refreshSources);
    elements.refreshDocuments.addEventListener("click", refreshAdminDocuments);
  }

  async function refreshSources() {
    try {
      const payload = await getJson("/sources");
      state.documents = payload.documents || [];
      renderSources();
      updateLearnerChatStatus();
    } catch (error) {
      state.documents = [];
      elements.sourceList.replaceChildren(emptyText(`Sources unavailable: ${errorMessage(error)}`));
      elements.sourceTable.replaceChildren(emptyText("No indexed sources found."));
      updateLearnerChatStatus("Course sources unavailable.");
    }
  }

  function renderSources() {
    elements.sourceList.replaceChildren();
    elements.sourceTable.replaceChildren();

    if (state.documents.length === 0) {
      elements.sourceList.append(emptyText("No sources loaded"));
      elements.sourceTable.append(emptyText("No indexed sources found."));
      return;
    }

    state.documents.forEach((documentItem) => {
      const row = sourceButton(documentItem);
      elements.sourceList.append(row);
      elements.sourceTable.append(sourceTableRow(documentItem));
    });
  }

  function sourceButton(documentItem) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "source-row";
    row.addEventListener("click", () => previewDocument(documentItem));

    const title = document.createElement("strong");
    title.className = "source-title";
    title.textContent = documentDisplayTitle(documentItem);
    const meta = document.createElement("span");
    meta.className = "source-meta";
    meta.textContent = documentSourceSummary(documentItem);

    row.append(title, meta);
    return row;
  }

  function sourceTableRow(documentItem) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "doc-row";
    row.addEventListener("click", () => previewDocument(documentItem));

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
    const status = documentItem.index_status === "indexed" ? "已索引"
      : documentItem.index_status === "not_indexed" ? "未索引"
      : documentItem.index_status || "未知";
    const parts = [
      `${sectionCount} 個段落`,
      status,
      documentItem.source_type || null,
    ];
    return parts.filter(Boolean).join(" · ");
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
        emptyText(`Document lifecycle unavailable: ${errorMessage(error)}`),
      );
    }
  }

  function renderAdminDocuments(documents) {
    state.adminDocuments = Array.isArray(documents) ? documents : [];
    elements.adminDocuments.replaceChildren();

    if (state.adminDocuments.length === 0) {
      elements.adminDocuments.append(emptyText("No admin documents loaded."));
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

  async function previewDocument(documentItem) {
    elements.markdownPreview.textContent = "Loading source metadata...";
    renderPreviewSourceMeta({
      title: documentDisplayTitle(documentItem),
      summary: documentSourceSummary(documentItem),
      kind: "Source browser",
    });

    try {
      const documentDetail = await getJson(`/sources/${documentItem.id}`);
      renderPreviewSourceMeta({
        title: documentDisplayTitle(documentDetail),
        summary: documentSourceSummary(documentDetail),
        kind: "Source browser",
      });
      elements.markdownPreview.textContent = await formatDocumentPreview(documentDetail);
    } catch (error) {
      elements.markdownPreview.textContent = `Source preview unavailable: ${errorMessage(error)}`;
    }
  }

  async function formatDocumentPreview(documentDetail) {
    const sections = await Promise.all(
      (documentDetail.sections || []).map(async (section) => {
        const detail = await getJson(`/sources/${documentDetail.id}/sections/${section.id}`);
        return detail.body_md;
      }),
    );
    return [
      `# ${documentDetail.title || documentDetail.filename}`,
      "",
      `Path: ${documentDetail.canonical_path}`,
      `Type: ${documentDetail.source_type}`,
      "",
      sections.join("\n\n") || "No sections indexed.",
    ].join("\n");
  }

  function documentDisplayTitle(documentItem) {
    const title = documentItem.title || "";
    if (title && title !== documentItem.filename?.replace(/\.md$/i, "")) {
      return title;
    }
    const filename = documentItem.filename || title || "Untitled source";
    return filename.replace(/\.md$/i, "");
  }

  function documentSourceSummary(documentItem) {
    const parts = [
      `${documentItem.section_count || 0} sections`,
      documentItem.source_type || "source",
      documentItem.imported_from ? `from ${documentItem.imported_from}` : documentItem.filename,
    ];
    return parts.filter(Boolean).join(" · ");
  }

  function renderPreviewSourceMeta({ title, summary, kind }) {
    elements.previewSourceMeta.replaceChildren();
    const wrapper = document.createElement("div");
    wrapper.className = "preview-source-card";
    const label = document.createElement("span");
    label.textContent = kind || "Preview";
    const heading = document.createElement("strong");
    heading.textContent = title || "Untitled source";
    const meta = document.createElement("span");
    meta.className = "source-meta";
    meta.textContent = summary || "No source metadata available.";
    wrapper.append(label, heading, meta);
    elements.previewSourceMeta.append(wrapper);
  }

  function resetPreviewSourceMeta() {
    elements.previewSourceMeta.replaceChildren(emptyText("No preview selected."));
  }

  function chatLimit() {
    const rawLimit = Number(elements.chatLimit.value || 5);
    const normalizedLimit = Number.isFinite(rawLimit) ? Math.round(rawLimit) : 5;
    const clampedLimit = Math.min(20, Math.max(1, normalizedLimit));
    elements.chatLimit.value = String(clampedLimit);
    return clampedLimit;
  }

  // --- knowledge graph ---
  const CLUSTER_COLORS = ["#4285f4", "#34a853", "#f9ab00", "#ea4335", "#9334e6",
    "#12a4af", "#e8710a", "#7b1fa2", "#1565c0", "#2e7d32", "#c2185b", "#5d4037"];

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

  function graphElements(useCompound) {
    const clusters = state.graph.clusters || [];
    const clusterColor = new Map();
    const clusterIndex = new Map();
    clusters.forEach((cluster, index) => {
      clusterColor.set(cluster.id, CLUSTER_COLORS[index % CLUSTER_COLORS.length]);
      clusterIndex.set(cluster.id, index);
    });
    const clusterCount = clusters.length;
    const parents = clusters.map((cluster) => ({
      data: {
        id: `cluster:${cluster.id}`,
        label: cluster.name,
        baseLabel: cluster.name,
        isCluster: true,
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
        color: clusterColor.get(node.cluster_id) || "#62717f",
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

  const GRAPH_LAYOUTS = {
    cluster: { name: "cose", animate: false, padding: 24, nodeRepulsion: 9000 },
    // Radial: assign each cluster its own concentric ring.
    // clusterCount - clusterIndex gives outermost ring to cluster 0's concepts;
    // level 0 is reserved for anything without a cluster.
    radial: {
      name: "concentric",
      animate: false,
      padding: 24,
      minNodeSpacing: 28,
      concentric: (node) => {
        const count = node.data("clusterCount") || 1;
        const idx = node.data("clusterIndex") || 0;
        return count - idx;
      },
      levelWidth: () => 1,
    },
    order: { name: "dagre", rankDir: "LR", animate: false, padding: 24 },
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
    const { parents, nodes, edges } = graphElements(useCompound);
    if (state.cy) {
      state.cy.destroy();
    }
    state.cy = cytoscape({
      container: elements.graphCanvas,
      elements: [...(useCompound ? parents : []), ...nodes, ...edges],
      layout: GRAPH_LAYOUTS[view],
      style: [
        { selector: "node", style: {
          label: "data(label)", "font-size": 11, width: "data(size)", height: "data(size)",
          "background-color": "data(color)", "text-valign": "bottom", "text-margin-y": 4 } },
        { selector: "node[?isCluster]", style: {
          "background-opacity": 0.08, "border-width": 1.5, "border-color": "#aaa",
          label: "data(label)", "font-size": 14, "font-weight": 700,
          "text-valign": "top", shape: "round-rectangle" } },
        { selector: "edge", style: {
          width: 1.4, "line-color": "#c4ccd4", "curve-style": "bezier" } },
        { selector: 'edge[kind = "prerequisite"]', style: {
          "target-arrow-shape": "triangle", "target-arrow-color": "#8a96a3",
          "line-color": "#8a96a3" } },
        { selector: 'edge[kind = "part_of"]', style: { "line-style": "dashed" } },
        ...(orderView
          ? [{ selector: 'edge[kind != "prerequisite"]', style: { opacity: 0.25 } }]
          : []),
        { selector: "node.dimmed", style: { opacity: 0.15 } },
        { selector: "node.highlighted", style: { "border-width": 3, "border-color": "#162029" } },
      ],
    });
    state.cy.on("tap", "node[^isCluster]", (event) => previewConcept(event.target.id()));
    state.cy.on("tap", "node[?isCluster]", (event) => toggleClusterCollapse(event.target.id()));
    applyClusterCollapse();
    filterGraphNodes();
    renderGraphStats();
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
    if (stats.extracted_at) {
      try {
        parts.push(`最後更新 ${new Date(stats.extracted_at).toLocaleString()}`);
      } catch (_) {
        // ignore malformed date
      }
    }
    let statsEl = elements.graphCanvas.previousElementSibling;
    if (!statsEl || !statsEl.classList.contains("graph-stats")) {
      statsEl = document.createElement("p");
      statsEl.className = "graph-stats";
      elements.graphCanvas.parentNode.insertBefore(statsEl, elements.graphCanvas);
    }
    statsEl.textContent = parts.join(" · ");
  }

  async function previewConcept(conceptId) {
    elements.markdownPreview.textContent = "載入概念中…";

    try {
      const detail = await getJson(`/graph/concepts/${conceptId}`);
      renderConceptDetail(detail);
    } catch (error) {
      resetPreviewSourceMeta();
      elements.markdownPreview.textContent = `Concept detail unavailable: ${errorMessage(error)}`;
    }
  }

  function renderConceptDetail(detail) {
    const sources = Array.isArray(detail.sources) ? detail.sources : [];
    renderPreviewSourceMeta({
      title: detail.name,
      summary: [detail.cluster, `${sources.length} 個來源`].filter(Boolean).join(" · "),
      kind: "知識圖譜概念",
    });

    const askButton = document.createElement("button");
    askButton.type = "button";
    askButton.id = "ask-about-concept";
    askButton.className = "secondary-button";
    askButton.textContent = "去問問題";
    askButton.addEventListener("click", () => askAboutConcept(detail.name));
    elements.previewSourceMeta.append(askButton);

    const sourceList = document.createElement("div");
    sourceList.className = "concept-sources";
    sources.forEach((source) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "source-row";
      row.addEventListener("click", () => previewConceptSource(source));

      const title = document.createElement("strong");
      title.className = "source-title";
      title.textContent = source.heading || source.source_id;
      const meta = document.createElement("span");
      meta.className = "source-meta";
      meta.textContent = [source.filename, source.source_id].filter(Boolean).join(" · ");

      row.append(title, meta);
      sourceList.append(row);
    });
    elements.previewSourceMeta.append(sourceList);

    const aliases = Array.isArray(detail.aliases) ? detail.aliases : [];
    elements.markdownPreview.textContent = [
      detail.name,
      detail.summary,
      aliases.length > 0 ? `Aliases: ${aliases.join(", ")}` : null,
    ]
      .filter(Boolean)
      .join("\n\n");
  }

  async function previewConceptSource(source) {
    elements.markdownPreview.textContent = "載入來源段落中…";
    renderPreviewSourceMeta({
      title: source.heading || source.source_id,
      summary: source.source_id || "概念來源",
      kind: "知識圖譜預覽",
    });
    try {
      const section = await getJson(
        `/sources/${source.document_id}/sections/${source.section_id}`,
      );
      renderPreviewSourceMeta({
        title: section.heading,
        summary: section.source_id,
        kind: "知識圖譜預覽",
      });
      elements.markdownPreview.textContent = [section.heading, section.body_md].join("\n\n");
      renderGraphCrossLink(section.source_id, section.heading, section.body_md);
    } catch (error) {
      elements.markdownPreview.textContent = `Source preview unavailable: ${errorMessage(error)}`;
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
        } catch (_) {
          sourceIds = [];
        }
        state.conceptSourceCache.set(node.id, sourceIds);
      }
      if (sourceIds.includes(sourceId)) {
        return node;
      }
    }
    return null;
  }

  function focusGraphConcept(conceptId) {
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
    elements.refreshStatus.addEventListener("click", refreshStatus);
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
      await refreshStatus();
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

  async function refreshStatus() {
    try {
      const payload = await getJson("/index/status");
      const chunks = payload.stats && payload.stats.chunks_indexed;
      state.indexStatus = {
        status: payload.status,
        chunks,
        updatedAt: payload.updated_at || null,
      };
      elements.statusPill.textContent = `Index ${payload.status}`;
      elements.statusPill.className = payload.status === "succeeded" ? "is-success" : "is-warning";
      elements.statusGrid.replaceChildren(
        statusRow("Status", payload.status),
        statusRow("Chunks", chunks ?? "--"),
        statusRow("Updated", payload.updated_at || "--"),
      );
      updateLearnerChatStatus();
    } catch (error) {
      state.indexStatus = {
        status: "unavailable",
        chunks: null,
        updatedAt: null,
      };
      elements.statusPill.textContent = "Index not ready";
      elements.statusPill.className = "is-warning";
      elements.statusGrid.replaceChildren(
        statusRow("Status", "Unavailable"),
        statusRow("Chunks", "--"),
        statusRow("Updated", errorMessage(error)),
      );
      updateLearnerChatStatus("Course source index unavailable.");
    }
  }

  async function refreshLearnerContext() {
    await Promise.allSettled([refreshStatus(), refreshSources()]);
  }

  function updateLearnerChatStatus(fallbackText = null) {
    if (fallbackText) {
      elements.learnerChatStatus.textContent = fallbackText;
      return;
    }

    const sourceCount = state.documents.length;
    const sourceLabel = sourceCount === 1 ? "1 course source" : `${sourceCount} course sources`;
    if (!state.indexStatus) {
      elements.learnerChatStatus.textContent = `${sourceLabel} available.`;
      return;
    }

    if (state.indexStatus.status === "succeeded") {
      const chunkText = state.indexStatus.chunks == null ? "chunks indexed" : `${state.indexStatus.chunks} chunks indexed`;
      elements.learnerChatStatus.textContent = `${sourceLabel} available · ${chunkText}.`;
      return;
    }

    if (state.indexStatus.status === "unavailable") {
      elements.learnerChatStatus.textContent = "Course source index unavailable.";
      return;
    }

    elements.learnerChatStatus.textContent = `Index ${state.indexStatus.status} · ${sourceLabel} available.`;
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

  function renderAuditEvents(events) {
    state.auditEvents = Array.isArray(events) ? events : [];
    elements.auditEvents.replaceChildren();

    if (state.auditEvents.length === 0) {
      elements.auditEvents.append(emptyText("No audit events loaded."));
      return;
    }

    state.auditEvents.forEach((auditEvent) => {
      const row = document.createElement("div");
      row.className = `audit-row is-${auditEvent.outcome || "unknown"}`;

      const title = document.createElement("strong");
      title.textContent = auditEvent.event_type || "audit.event";
      const meta = document.createElement("span");
      meta.className = "source-meta";
      meta.textContent = [
        auditEvent.outcome,
        auditEvent.actor_type,
        auditEvent.actor_id,
        auditEvent.path,
        auditEvent.request_id,
        formatDateTime(auditEvent.created_at),
      ]
        .filter(Boolean)
        .join(" · ");
      const details = document.createElement("span");
      details.className = "source-meta";
      details.textContent = auditMetadataSummary(auditEvent.metadata || {});
      row.append(title, meta, details);
      elements.auditEvents.append(row);
    });
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
      const adminKey = elements.evalAdminKey.value;
      elements.evalForm.reset();
      elements.evalAdminKey.value = adminKey;
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
          strategy: elements.chatStrategy.value,
          limit: chatLimit(),
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
    const adminKey = (
      elements.adminKey.value ||
      elements.documentAdminKey.value ||
      elements.auditAdminKey.value ||
      elements.opsAdminKey.value ||
      elements.evalAdminKey.value ||
      ""
    ).trim();
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
