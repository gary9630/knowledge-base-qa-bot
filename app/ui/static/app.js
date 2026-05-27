(function () {
  const state = {
    documents: [],
    mindmap: {
      nodes: [],
      edges: [],
      stats: {
        documents: 0,
        sections: 0,
      },
    },
    mindmapLoaded: false,
    importJobs: [],
    auditEvents: [],
    evalCases: [],
    evalRun: null,
    evalReport: null,
    feedbackItems: [],
    selectedSources: [],
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
    selectedSources: $("#selected-sources"),
    selectedSourceCount: $("#selected-source-count"),
    markdownPreview: $("#markdown-preview"),
    sourceList: $("#source-list"),
    sourceTable: $("#source-table"),
    mindmap: $("#mindmap"),
    loadMindmap: $("#load-mindmap"),
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
    importJobs: $("#import-jobs"),
    rebuildIndex: $("#rebuild-index"),
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
    workbench: $("[data-app]"),
  };

  function init() {
    bindAuth();
    bindTabs();
    bindChat();
    bindSources();
    bindMindmap();
    bindAdmin();
    bindEvals();
    refreshAuthSession();
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
    elements.platformAuthStatus.textContent = state.auth.authenticated
      ? `Signed in${state.auth.username ? ` as ${state.auth.username}` : ""}.`
      : "Sign in to continue.";
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
  }

  function nextTabForKey(currentTab, key) {
    const currentIndex = elements.tabs.indexOf(currentTab);
    if (key === "Home") {
      return elements.tabs[0];
    }
    if (key === "End") {
      return elements.tabs[elements.tabs.length - 1];
    }

    const offset = key === "ArrowRight" ? 1 : -1;
    const nextIndex = (currentIndex + offset + elements.tabs.length) % elements.tabs.length;
    return elements.tabs[nextIndex];
  }

  function bindChat() {
    elements.chatForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const query = elements.chatQuery.value.trim();
      if (!query) {
        return;
      }

      addMessage("user", query);
      const answerNode = addMessage("assistant", "");
      elements.chatQuery.value = "";
      setSelectedSources([]);

      try {
        await streamChat(query, answerNode);
      } catch (error) {
        answerNode.textContent = errorMessage(error);
      }
    });
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

    await readSse(response.body, (event) => {
      if (event.event === "sources") {
        const payload = safeJson(event.data);
        setSelectedSources(payload.selected_sources || payload.sources || []);
        return;
      }

      if (event.event === "token") {
        answerNode.textContent += event.data;
        elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
        return;
      }

      if (event.event === "error") {
        const payload = safeJson(event.data);
        answerNode.textContent = payload.detail || event.data || "Chat stream failed.";
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
    label.textContent = role === "user" ? "You" : "Assistant";

    const body = document.createElement("p");
    body.textContent = text;

    wrapper.append(label, body);
    elements.chatLog.append(wrapper);
    elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
    return body;
  }

  function setSelectedSources(sources) {
    state.selectedSources = Array.isArray(sources) ? sources : [];
    elements.selectedSources.replaceChildren();
    elements.selectedSourceCount.textContent = String(state.selectedSources.length);

    if (state.selectedSources.length === 0) {
      elements.selectedSources.append(emptyText("No selected sources"));
      elements.markdownPreview.textContent = "Select a source to preview markdown.";
      return;
    }

    state.selectedSources.forEach((source, index) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "selected-source";
      row.addEventListener("click", () => previewCandidate(source));

      const title = document.createElement("strong");
      title.textContent = source.source_id || source.filename || "Source";
      const meta = document.createElement("span");
      meta.className = "source-meta";
      meta.textContent = [
        source.strategy,
        typeof source.score === "number" ? source.score.toFixed(3) : null,
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

  function previewCandidate(source) {
    const heading = source.heading || source.source_id || "Source";
    const body = source.body_md || "No markdown body returned for this source.";
    elements.markdownPreview.textContent = `${heading}\n\n${body}`;
  }

  function bindSources() {
    elements.refreshSources.addEventListener("click", refreshSources);
  }

  async function refreshSources() {
    try {
      const payload = await getJson("/sources");
      state.documents = payload.documents || [];
      renderSources();
    } catch (error) {
      state.documents = [];
      elements.sourceList.replaceChildren(emptyText(`Sources unavailable: ${errorMessage(error)}`));
      elements.sourceTable.replaceChildren(emptyText("No indexed sources found."));
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
    title.textContent = documentItem.title || documentItem.filename;
    const meta = document.createElement("span");
    meta.className = "source-meta";
    meta.textContent = `${documentItem.section_count} sections · ${documentItem.source_type}`;

    row.append(title, meta);
    return row;
  }

  function sourceTableRow(documentItem) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "source-table-row source-row";
    row.addEventListener("click", () => previewDocument(documentItem));

    [documentItem.filename, `${documentItem.section_count} sections`, documentItem.source_type].forEach(
      (value) => {
        const cell = document.createElement("span");
        cell.textContent = value || "--";
        row.append(cell);
      },
    );
    return row;
  }

  async function previewDocument(documentItem) {
    elements.markdownPreview.textContent = "Loading source metadata...";
    setSelectedSources([
      {
        source_id: documentItem.filename,
        filename: documentItem.filename,
        heading: documentItem.title || documentItem.filename,
        body_md: "",
      },
    ]);

    try {
      const documentDetail = await getJson(`/sources/${documentItem.id}`);
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

  function chatLimit() {
    const rawLimit = Number(elements.chatLimit.value || 5);
    const normalizedLimit = Number.isFinite(rawLimit) ? Math.round(rawLimit) : 5;
    const clampedLimit = Math.min(20, Math.max(1, normalizedLimit));
    elements.chatLimit.value = String(clampedLimit);
    return clampedLimit;
  }

  function bindMindmap() {
    elements.loadMindmap.addEventListener("click", loadMindmap);
  }

  async function loadMindmap() {
    elements.loadMindmap.disabled = true;
    elements.mindmap.replaceChildren(emptyText("Loading source graph..."));

    try {
      state.mindmap = await getJson("/mindmap");
      state.mindmapLoaded = true;
      renderMindmap();
    } catch (error) {
      state.mindmapLoaded = false;
      elements.mindmap.replaceChildren(
        emptyText(`Source graph unavailable: ${errorMessage(error)}`),
      );
    } finally {
      elements.loadMindmap.disabled = false;
    }
  }

  function renderMindmap() {
    elements.mindmap.replaceChildren();
    if (!state.mindmapLoaded) {
      elements.mindmap.append(emptyText("Load the graph to inspect indexed documents and sections."));
      return;
    }

    const nodes = Array.isArray(state.mindmap.nodes) ? state.mindmap.nodes : [];
    const edges = Array.isArray(state.mindmap.edges) ? state.mindmap.edges : [];
    if (nodes.length === 0) {
      elements.mindmap.append(emptyText("No indexed documents found."));
      return;
    }

    const stats = document.createElement("div");
    stats.className = "mindmap-stats";
    stats.textContent = `${state.mindmap.stats.documents} documents · ${state.mindmap.stats.sections} sections`;
    elements.mindmap.append(stats);

    const tree = document.createElement("div");
    tree.className = "mindmap-tree";
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const sectionIdsByDocumentId = new Map();
    edges.forEach((edge) => {
      if (edge.relation !== "contains") {
        return;
      }
      const sectionIds = sectionIdsByDocumentId.get(edge.source) || [];
      sectionIds.push(edge.target);
      sectionIdsByDocumentId.set(edge.source, sectionIds);
    });

    nodes
      .filter((node) => node.type === "document")
      .forEach((documentNode) => {
        const group = document.createElement("section");
        group.className = "mindmap-group";
        group.append(mindmapNodeButton(documentNode));

        const sectionList = document.createElement("div");
        sectionList.className = "mindmap-sections";
        (sectionIdsByDocumentId.get(documentNode.id) || []).forEach((sectionNodeId) => {
          const sectionNode = nodeById.get(sectionNodeId);
          if (sectionNode) {
            sectionList.append(mindmapNodeButton(sectionNode));
          }
        });
        group.append(sectionList);
        tree.append(group);
    });
    elements.mindmap.append(tree);
  }

  function mindmapNodeButton(node) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `mindmap-node is-${node.type}`;
    button.addEventListener("click", () => previewMindmapNode(node));

    const title = document.createElement("strong");
    title.textContent = node.label || "Untitled node";
    const meta = document.createElement("span");
    meta.textContent = mindmapNodeMeta(node);

    button.append(title, meta);
    return button;
  }

  function mindmapNodeMeta(node) {
    const metadata = node.metadata || {};
    if (node.type === "document") {
      return `${metadata.section_count || 0} sections · ${metadata.source_type || "source"}`;
    }

    return [metadata.source_id, `level ${metadata.level || "--"}`].filter(Boolean).join(" · ");
  }

  async function previewMindmapNode(node) {
    const metadata = node.metadata || {};
    if (node.type === "document" && metadata.document_id) {
      await previewDocument({
        id: metadata.document_id,
        filename: metadata.filename || node.label,
        title: metadata.title || node.label,
        source_type: metadata.source_type || "source",
        section_count: metadata.section_count || 0,
      });
      return;
    }

    if (node.type === "section" && metadata.document_id && metadata.section_id) {
      setSelectedSources([
        {
          source_id: metadata.source_id || node.label,
          heading: metadata.heading || node.label,
          body_md: "Loading source section...",
        },
      ]);
      elements.markdownPreview.textContent = "Loading source section...";
      try {
        const section = await getJson(
          `/sources/${metadata.document_id}/sections/${metadata.section_id}`,
        );
        setSelectedSources([
          {
            source_id: section.source_id,
            heading: section.heading,
            body_md: section.body_md,
          },
        ]);
      } catch (error) {
        elements.markdownPreview.textContent = `Source preview unavailable: ${errorMessage(error)}`;
      }
    }
  }

  async function refreshMindmapAfterContentChange() {
    if (!state.mindmapLoaded) {
      return;
    }

    await loadMindmap();
  }

  function bindAdmin() {
    elements.uploadForm.addEventListener("submit", uploadFile);
    elements.rebuildIndex.addEventListener("click", rebuildIndex);
    elements.refreshStatus.addEventListener("click", refreshStatus);
    elements.refreshImports.addEventListener("click", refreshImportJobs);
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
      appendOperation(`Import ${payload.status}: ${payload.filename} -> ${payload.canonical_path}`);
      elements.uploadFile.value = "";
      renderImportJobs([payload, ...state.importJobs]);
      await refreshImportJobs();
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
      await refreshMindmapAfterContentChange();
    } catch (error) {
      appendOperation(`Index rebuild failed: ${errorMessage(error)}`);
    } finally {
      elements.rebuildIndex.disabled = false;
    }
  }

  async function refreshStatus() {
    try {
      const payload = await getJson("/index/status");
      const chunks = payload.stats && payload.stats.chunks_indexed;
      elements.statusPill.textContent = `Index ${payload.status}`;
      elements.statusPill.className = payload.status === "succeeded" ? "is-success" : "is-warning";
      elements.statusGrid.replaceChildren(
        statusRow("Status", payload.status),
        statusRow("Chunks", chunks ?? "--"),
        statusRow("Updated", payload.updated_at || "--"),
      );
    } catch (error) {
      elements.statusPill.textContent = "Index not ready";
      elements.statusPill.className = "is-warning";
      elements.statusGrid.replaceChildren(
        statusRow("Status", "Unavailable"),
        statusRow("Chunks", "--"),
        statusRow("Updated", errorMessage(error)),
      );
    }
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
      elements.importJobs.replaceChildren(emptyText(`Import jobs unavailable: ${errorMessage(error)}`));
    }
  }

  function renderImportJobs(jobs) {
    state.importJobs = Array.isArray(jobs) ? jobs : [];
    elements.importJobs.replaceChildren();

    if (state.importJobs.length === 0) {
      elements.importJobs.append(emptyText("No import jobs loaded."));
      return;
    }

    state.importJobs.slice(0, 10).forEach((job) => {
      const row = document.createElement("div");
      row.className = `job-row is-${job.status || "unknown"}`;

      const body = document.createElement("div");
      body.className = "job-body";
      const title = document.createElement("strong");
      title.textContent = job.filename || "Uploaded source";
      const meta = document.createElement("span");
      meta.className = "source-meta";
      meta.textContent = [job.kind, job.status, job.updated_at].filter(Boolean).join(" · ");
      body.append(title, meta);
      row.append(body);

      if (job.status === "failed") {
        const retry = document.createElement("button");
        retry.type = "button";
        retry.className = "secondary-button";
        retry.textContent = "Retry";
        retry.addEventListener("click", () => retryImportJob(job.id));
        row.append(retry);
      }

      elements.importJobs.append(row);
    });
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
      elements.auditAdminKey.value ||
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
