from fastapi.testclient import TestClient

from app.main import create_app


def test_ui_serves_three_column_workbench() -> None:
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "Chat" in response.text
    assert "知識圖譜" in response.text
    assert "Admin Uploads" in response.text
    assert "Feedback / Evals" in response.text
    assert "引用來源" in response.text
    assert 'role="tabpanel"' in response.text
    assert 'aria-controls="panel-chat"' in response.text

    css_response = client.get("/static/app.css")
    js_response = client.get("/static/app.js")

    assert css_response.status_code == 200
    assert js_response.status_code == 200
    assert "fetch(\"/chat/stream\"" in js_response.text
    assert "event.event === \"error\"" in js_response.text
    assert "fetch(\"/imports\"" in js_response.text
    assert "fetch(\"/imports/status\"" in js_response.text
    assert "/retry`" in js_response.text
    assert "await refreshBackgroundJobs();" in js_response.text
    assert "elements.uploadFile.value = \"\"" in js_response.text
    assert "elements.uploadForm.reset()" not in js_response.text
    assert "fetch(\"/index\"" in js_response.text
    assert "X-KB-Admin-Key" in js_response.text
    assert "getJson(\"/index/status\"" in js_response.text
    assert "getJson(\"/sources\"" in js_response.text
    assert "parseSseDataLine" in js_response.text
    assert 'id="import-jobs"' in response.text
    assert 'id="refresh-imports"' in response.text


def test_ui_uses_root_relative_static_asset_paths() -> None:
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/static/app.css"' in response.text
    assert 'src="/static/app.js"' in response.text
    assert "http://testserver/static" not in response.text


def test_ui_exposes_eval_workbench_wiring() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    js_response = client.get("/static/app.js")

    assert response.status_code == 200
    assert 'data-console-panel="evals"' in response.text  # evals moved into the admin console
    assert 'id="panel-evals"' in response.text
    assert 'id="eval-form"' in response.text
    assert 'id="eval-status"' in response.text
    assert 'id="eval-report"' in response.text
    assert 'id="seed-evals"' in response.text
    assert 'id="feedback-promotions"' in response.text
    assert 'id="run-evals"' in response.text
    assert "Recent Runs" in response.text
    assert "Worst Cases" in response.text
    assert "fetch(\"/evals/cases\"" in js_response.text
    assert "fetch(\"/evals/run\"" in js_response.text
    assert "fetch(\"/evals/seed\"" in js_response.text
    assert "fetch(\"/evals/cases/promote-feedback\"" in js_response.text
    assert "getJsonWithHeaders(\"/evals/report\"" in js_response.text
    assert "getJsonWithHeaders(\"/evals/runs/latest\"" in js_response.text
    assert "report.recent_runs" in js_response.text
    assert "report.worst_cases" in js_response.text
    assert "setEvalStatus" in js_response.text


def test_ui_exposes_platform_login_wiring() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    js_response = client.get("/static/app.js")

    assert response.status_code == 200
    assert 'id="platform-login-form"' in response.text
    assert 'id="platform-username"' in response.text
    assert 'id="platform-password"' in response.text
    assert 'id="platform-logout"' in response.text
    assert 'id="console-admin-key"' in response.text  # single shared admin key field
    assert "getJsonWithHeaders(\"/auth/session\"" in js_response.text
    assert "fetch(\"/auth/login\"" in js_response.text
    assert "fetch(\"/auth/logout\"" in js_response.text
    assert "X-KB-CSRF-Token" in js_response.text


def test_ui_serves_student_landing_page_and_marks_admin_surfaces() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    css_response = client.get("/static/app.css")

    assert response.status_code == 200
    assert 'id="landing-login-open"' in response.text  # 右上角登入
    assert 'id="landing-login-overlay"' in response.text
    assert 'class="landing-feature-grid"' in response.text
    assert "課程助理" in response.text  # chat panel heading (zh-TW learner copy)
    assert "登入課程帳號" in response.text  # login dialog heading
    assert 'id="tab-chat"' in response.text
    assert 'id="tab-graph"' in response.text
    assert 'id="tab-sources"' in response.text
    # admin tabs no longer exist in the learner tab row; the console entry is admin-only
    for tab_id in ("tab-uploads", "tab-ops", "tab-audit", "tab-evals"):
        assert f'id="{tab_id}"' not in response.text
    console_entry_markup = response.text.split('id="console-entry"', 1)[1].split(">", 1)[0]
    assert "data-admin-only" in console_entry_markup

    for panel_id in ("panel-uploads", "panel-ops", "panel-audit", "panel-evals"):
        panel_markup = response.text.split(f'id="{panel_id}"', 1)[1].split(">", 1)[0]
        assert "data-admin-only" in panel_markup

    document_section_markup = response.text.split('id="admin-documents-section"', 1)[1].split(
        ">",
        1,
    )[0]
    assert "data-admin-only" in document_section_markup

    assert css_response.status_code == 200
    assert "[hidden]" in css_response.text
    # full-page landing with topbar login replaced the landing-card layout
    assert ".landing-topbar" in css_response.text
    assert ".landing-feature-grid" in css_response.text
    assert ".landing-login-overlay" in css_response.text


def test_ui_blocks_admin_tabs_for_platform_learners_in_javascript() -> None:
    client = TestClient(create_app())

    js_response = client.get("/static/app.js")

    assert js_response.status_code == 200
    assert "adminOnlySurfaces" in js_response.text
    assert "function applyAccessPolicy" in js_response.text
    assert "function isRestrictedLearner" in js_response.text
    assert "function tabIsAvailable" in js_response.text
    assert "if (!tabIsAvailable(tabName))" in js_response.text
    assert "elements.adminOnlySurfaces.forEach" in js_response.text
    assert "surface.hidden = restricted" in js_response.text
    assert "availableTabs()" in js_response.text


def test_ui_exposes_audit_log_wiring() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    js_response = client.get("/static/app.js")

    assert response.status_code == 200
    assert 'data-console-panel="audit"' in response.text  # audit moved into the admin console
    assert 'id="panel-audit"' in response.text
    assert 'id="audit-admin-key"' not in response.text  # replaced by shared console key
    assert 'id="audit-event-type"' in response.text
    assert 'id="audit-outcome"' in response.text
    assert 'id="audit-actor-type"' in response.text
    assert 'id="audit-limit"' in response.text
    assert 'id="refresh-audit"' in response.text
    assert 'id="audit-events"' in response.text
    assert "fetch(`/admin/audit-events?${params}`" in js_response.text
    assert "renderAuditEvents" in js_response.text
    assert "sharedAdminKey()" in js_response.text


def test_ui_exposes_document_lifecycle_wiring() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    js_response = client.get("/static/app.js")

    assert response.status_code == 200
    assert 'id="document-admin-key"' not in response.text  # replaced by shared console key
    assert 'data-console-panel-body="documents"' in response.text  # lifecycle lives in console
    assert 'id="refresh-documents"' in response.text
    assert 'id="admin-documents"' in response.text
    assert "fetch(\"/admin/documents\"" in js_response.text
    assert "fetch(`/admin/documents/${documentId}/lifecycle`" in js_response.text
    assert "fetch(`/admin/documents/${documentId}`" in js_response.text
    assert "fetch(`/admin/documents/${documentId}/reindex`" in js_response.text
    assert "renderAdminDocuments" in js_response.text
    assert "sharedAdminKey" in js_response.text


def test_ui_exposes_background_jobs_wiring() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    js_response = client.get("/static/app.js")

    assert response.status_code == 200
    assert 'id="queue-index-job"' in response.text
    assert 'id="recover-stale-jobs"' in response.text
    assert 'id="refresh-background-jobs"' in response.text
    assert 'id="background-job-summary"' in response.text
    assert 'id="background-job-status-filter"' in response.text
    assert 'id="background-job-limit"' in response.text
    assert 'id="worker-runtime"' in response.text
    assert 'id="background-jobs"' in response.text
    assert "fetch(\"/admin/jobs\"" in js_response.text
    assert "fetch(\"/admin/jobs/runtime\"" in js_response.text
    assert "renderWorkerRuntime" in js_response.text
    assert "backgroundJobQueryParams" in js_response.text
    assert "renderBackgroundJobSummary" in js_response.text
    assert "backgroundJobAgeLabel" in js_response.text
    assert "fetch(\"/admin/jobs/recover-stale\"" in js_response.text
    assert "fetch(`/admin/jobs/${jobId}/requeue`" in js_response.text
    assert "fetch(`/admin/jobs/${jobId}`" in js_response.text
    assert "renderBackgroundJobs" in js_response.text
    assert "elements.backgroundJobs" in js_response.text
    assert "elements.backgroundJobStatusFilter" in js_response.text
    assert "elements.backgroundJobLimit" in js_response.text
    assert "job.locked_by" in js_response.text
    assert "job.available_at" in js_response.text
    assert "job.priority" in js_response.text
    assert "job.is_stale" in js_response.text
    assert "queueDocumentReindexJob" in js_response.text


def test_ui_exposes_provider_observability_wiring() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    js_response = client.get("/static/app.js")

    assert response.status_code == 200
    assert 'data-console-panel="ops"' in response.text  # ops moved into the admin console
    assert 'id="panel-ops"' in response.text
    assert 'id="ops-admin-key"' not in response.text  # replaced by shared console key
    assert 'id="refresh-provider-observability"' in response.text
    assert 'id="provider-summary"' in response.text
    assert 'id="provider-budget"' in response.text
    assert 'id="provider-usage"' in response.text
    assert 'id="provider-latest-calls"' in response.text
    assert 'id="provider-traces"' in response.text
    assert "fetch(\"/admin/provider-observability" in js_response.text
    assert "renderProviderObservability" in js_response.text
    assert "renderProviderSummary" in js_response.text
    assert "renderProviderBudget" in js_response.text
    assert "renderProviderBudgetPolicyRow" in js_response.text
    assert "budget.should_block" in js_response.text
    assert "renderProviderCallRow" in js_response.text
    assert "usage_complete" in js_response.text


def test_ui_exposes_import_diagnostics_wiring() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    js_response = client.get("/static/app.js")

    assert response.status_code == 200
    assert 'id="import-diagnostics-summary"' in response.text
    assert "renderImportDiagnosticsSummary" in js_response.text
    assert "renderImportJobRow" in js_response.text
    assert "importJobMetadataDetails" in js_response.text
    assert "metadata.import_warnings" in js_response.text
    assert "metadata.detected_file_type" in js_response.text
    assert "metadata.path_strategy" in js_response.text
    assert "metadata.markdown_bytes" in js_response.text
    assert "metadata.background_job_id" in js_response.text
    assert "job.content_hash" in js_response.text


def test_ui_keeps_diagnostics_out_of_learner_surfaces() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    js_response = client.get("/static/app.js")

    assert response.status_code == 200
    # Diagnostic panels (answer quality / index status) are admin-console-only;
    # learners see the collapsible citation list and the source preview instead.
    assert 'id="answer-quality"' not in response.text
    assert 'id="index-status"' not in response.text
    assert 'id="citation-disclosure"' in response.text
    assert 'id="selected-source-count"' in response.text
    assert "answerIsCannotConfirm" in js_response.text
    assert "cannot_confirm_reason" in js_response.text
    assert "scoreBreakdownText" not in js_response.text


def test_ui_exposes_learner_chat_polish_wiring() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    js_response = client.get("/static/app.js")
    css_response = client.get("/static/app.css")

    assert response.status_code == 200
    assert 'id="learner-chat-status"' in response.text
    assert 'id="chat-empty-state"' in response.text
    assert "課程助理" in response.text
    assert "data-sample-prompt" in response.text
    assert 'id="chat-composer-status"' in response.text
    assert 'id="chat-submit"' in response.text
    assert 'id="markdown-preview" tabindex="0"' in response.text
    assert "想了解哪個課程主題" in response.text

    assert js_response.status_code == 200
    assert "bindSamplePrompts" in js_response.text
    assert "setChatBusy" in js_response.text
    assert "button.disabled = isBusy" in js_response.text
    assert "renderStreamingStatus" in js_response.text
    assert "renderAnswerFooter" in js_response.text
    assert "renderSourceChips" in js_response.text
    assert "previewSourceFromChip" in js_response.text
    assert "handleChatKeydown" in js_response.text
    assert "event.isComposing" in js_response.text
    assert 'event.key === "Enter"' in js_response.text
    assert "refreshLearnerContext" in js_response.text
    assert "updateLearnerChatStatus" in js_response.text
    assert "scrollIntoView" in js_response.text
    assert "正在搜尋課程教材" in js_response.text
    assert "個課程段落回答" in js_response.text
    assert "教材中找不到這個問題的答案" in js_response.text
    assert "previewCandidate(source)" in js_response.text
    assert "renderAnswerCitations" in js_response.text
    assert "citationLabelForSource" in js_response.text
    assert "submitAnswerFeedback" in js_response.text
    assert "feedbackExpectedSource" in js_response.text
    assert 'fetch("/feedback"' in js_response.text
    # cannot-confirm answers must not render citation chips or fill the rail
    assert "const citedSources = answerIsCannotConfirm(payload) ? []" in js_response.text

    assert css_response.status_code == 200
    assert ".chat-empty-state" in css_response.text
    assert ".sample-prompt-grid" in css_response.text
    assert ".answer-footer" in css_response.text
    assert ".source-chip" in css_response.text
    assert ".trust-badge" in css_response.text
    assert ".citation-pill" in css_response.text
    assert ".answer-feedback" in css_response.text


def test_ui_separates_answer_sources_from_previewed_source() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    js_response = client.get("/static/app.js")
    css_response = client.get("/static/app.css")

    assert response.status_code == 200
    assert "引用來源" in response.text
    assert 'id="answer-sources"' in response.text
    assert 'id="preview-source-meta"' in response.text
    assert "來源內容" in response.text
    assert "這次回答沒有引用來源。" in response.text

    assert js_response.status_code == 200
    assert "documentDisplayTitle" in js_response.text
    assert "renderPreviewSourceMeta" in js_response.text
    # opening the source reader must not touch the chat citation rail
    reader_body = js_response.text.split("async function openSourceReader", 1)[1].split(
        "function closeSourceReader", 1
    )[0]
    assert "setSelectedSources" not in reader_body

    assert css_response.status_code == 200
    assert ".preview-source-meta" in css_response.text
    assert ".source-title" in css_response.text


def test_ui_exposes_dual_theme_wiring() -> None:
    _client = TestClient(create_app())
    page = _client.get("/")
    assert 'lang="zh-Hant"' in page.text
    assert "kb-theme" in page.text  # head boot script reads localStorage("kb-theme")
    assert 'id="theme-toggle"' in page.text

    js_response = _client.get("/static/app.js")
    assert "bindThemeToggle" in js_response.text
    assert "kb-theme-changed" in js_response.text

    css_response = _client.get("/static/app.css")
    assert '[data-theme="dark"]' in css_response.text
    assert "--font-display" in css_response.text


def test_ui_exposes_scholarly_chat_styling() -> None:
    client = TestClient(create_app())

    css_response = client.get("/static/app.css")
    assert ".answer-card" in css_response.text
    assert ".trust-badge" in css_response.text
    assert ".citation-pill" in css_response.text
    assert ".source-row" in css_response.text

    js_response = client.get("/static/app.js")
    assert "renderFeedbackRow" in js_response.text
    assert "graph-cross-link" in js_response.text


def test_ui_exposes_scholarly_landing_and_sources() -> None:
    client = TestClient(create_app())

    page = client.get("/")
    css_response = client.get("/static/app.css")

    assert page.status_code == 200
    # Landing hero structure with topbar login
    assert 'class="landing-topbar"' in page.text
    assert 'class="landing-hero"' in page.text
    assert 'id="landing-cta-login"' in page.text
    # zh-TW copy on landing
    assert "課程知識庫助理" in page.text

    assert css_response.status_code == 200
    # Landing token-based style
    assert ".landing-hero" in css_response.text
    # Sources reading-list style
    assert ".doc-row" in css_response.text


def test_ui_admin_console_structure() -> None:
    client = TestClient(create_app())

    page = client.get("/")
    assert page.status_code == 200
    # learner sidebar: exactly the three learner tabs remain as tabs
    assert 'id="tab-uploads"' not in page.text  # admin tabs no longer in learner tab row
    assert 'id="tab-ops"' not in page.text
    assert 'id="tab-audit"' not in page.text
    assert 'id="tab-evals"' not in page.text
    assert 'id="console-nav"' in page.text
    assert 'id="console-entry"' in page.text
    assert 'data-console-panel="uploads"' in page.text
    assert 'id="console-admin-key"' in page.text

    # every console nav entry has a matching panel body
    for panel in (
        "overview",
        "uploads",
        "editor",
        "documents",
        "graph-extract",
        "evals",
        "health",
        "settings",
        "jobs",
        "ops",
        "audit",
    ):
        assert f'data-console-panel="{panel}"' in page.text
        assert f'data-console-panel-body="{panel}"' in page.text

    # the per-panel admin key inputs are replaced by the single console key
    for key_id in (
        "admin-key",
        "ops-admin-key",
        "audit-admin-key",
        "eval-admin-key",
        "document-admin-key",
    ):
        assert f'id="{key_id}"' not in page.text

    js_response = client.get("/static/app.js")
    assert "bindConsole" in js_response.text
    assert "sharedAdminKey" in js_response.text


def test_ui_console_dashboard_wiring() -> None:
    client = TestClient(create_app())

    page = client.get("/")
    assert page.status_code == 200
    assert 'data-console-panel-body="overview"' in page.text
    assert 'id="stat-index"' in page.text and 'id="stat-graph"' in page.text
    assert 'id="stat-jobs"' in page.text and 'id="stat-tokens"' in page.text
    assert 'id="recent-activity"' in page.text
    assert 'id="trigger-graph-extract"' in page.text

    js_response = client.get("/static/app.js")
    assert "loadConsoleOverview" in js_response.text
    assert "/admin/jobs/runtime" in js_response.text


def test_ui_graph_uses_theme_tokens() -> None:
    client = TestClient(create_app())
    js_response = client.get("/static/app.js")
    assert "resolveGraphTheme" in js_response.text
    assert 'addEventListener("kb-theme-changed"' in js_response.text


def test_ui_exposes_graph_tab_wiring() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    js_response = client.get("/static/app.js")

    assert response.status_code == 200
    assert 'id="tab-graph"' in response.text
    assert 'id="panel-graph"' in response.text
    assert 'id="graph-canvas"' in response.text
    assert 'id="graph-empty"' in response.text
    assert 'id="graph-search"' in response.text
    assert 'id="load-graph"' in response.text
    assert "vendor/cytoscape.min.js" in response.text
    assert "vendor/dagre.min.js" in response.text
    assert "vendor/cytoscape-dagre.js" in response.text

    # concept detail renders in the right-rail inspector, not below the canvas
    assert 'id="graph-detail"' not in response.text
    assert 'id="graph-stats"' in response.text

    assert "getJson(\"/graph\")" in js_response.text
    assert "renderGraphView" in js_response.text
    assert "graph-view-cluster" in js_response.text
    assert "graph-view-radial" in js_response.text
    assert "graph-view-order" in js_response.text
    assert "askAboutConcept" in js_response.text
    assert "refreshGraphAfterContentChange" in js_response.text
    assert "buildClusterPresetPositions" in js_response.text
    assert "highlightGraphNeighborhood" in js_response.text
    assert "renderConceptDetail" in js_response.text


def test_ui_exposes_source_reader_wiring() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    js_response = client.get("/static/app.js")

    assert response.status_code == 200
    assert 'id="source-table"' in response.text
    assert 'id="source-reader"' in response.text
    assert 'id="source-reader-back"' in response.text
    assert 'id="source-reader-body"' in response.text
    # the standalone sidebar source list is gone; sources live in the tab panel
    assert 'id="source-list"' not in response.text

    assert "openSourceReader" in js_response.text
    assert "closeSourceReader" in js_response.text
    assert "renderMarkdownFragment" in js_response.text
    assert "renderMarkdownInto" in js_response.text

    # mermaid code fences render as diagrams, with a code-block fallback
    assert "vendor/mermaid.min.js" in response.text
    assert "mermaidBlock" in js_response.text
    assert "suppressErrorRendering" in js_response.text
    vendor_response = client.get("/static/vendor/mermaid.min.js")
    assert vendor_response.status_code == 200
    init_body = js_response.text.split("function init() {", 1)[1].split("}", 1)[0]
    assert "loadGraph" not in init_body

    for vendor_path in (
        "/static/vendor/cytoscape.min.js",
        "/static/vendor/dagre.min.js",
        "/static/vendor/cytoscape-dagre.js",
    ):
        vendor_response = client.get(vendor_path)
        assert vendor_response.status_code == 200


def test_ui_motion_and_a11y_rules() -> None:
    client = TestClient(create_app())
    css_response = client.get("/static/app.css")
    assert "prefers-reduced-motion" in css_response.text
    assert ":focus-visible" in css_response.text


def test_ui_runtime_settings_console_wiring() -> None:
    client = TestClient(create_app())

    page = client.get("/")
    js_response = client.get("/static/app.js")

    assert page.status_code == 200
    assert 'data-console-panel="settings"' in page.text
    assert 'id="runtime-settings-form"' in page.text
    assert 'id="settings-chat-model"' in page.text
    assert 'id="settings-max-tokens"' in page.text
    assert 'id="settings-temperature"' in page.text
    assert 'id="settings-budget-enabled"' in page.text
    assert 'id="reset-runtime-settings"' in page.text

    assert "loadRuntimeSettings" in js_response.text
    assert "collectRuntimeOverrides" in js_response.text
    assert '"/admin/settings"' in js_response.text


def test_ui_role_based_landing_and_admin_gating() -> None:
    client = TestClient(create_app())

    page = client.get("/")
    js_response = client.get("/static/app.js")

    assert page.status_code == 200
    # landing topbar 登入 + overlay form
    assert 'id="landing-login-open"' in page.text
    assert 'id="landing-login-overlay"' in page.text

    # admin role unlocks the console entry; students stay restricted
    assert 'state.auth.role !== "admin"' in js_response.text
    assert "role: payload.role || null" in js_response.text
    assert "openLoginOverlay" in js_response.text


def test_ui_markdown_editor_console_wiring() -> None:
    client = TestClient(create_app())

    page = client.get("/")
    js_response = client.get("/static/app.js")

    assert 'id="editor-document-select"' in page.text
    assert 'id="editor-content"' in page.text
    assert 'id="editor-save-content"' in page.text
    assert 'id="editor-new-filename"' in page.text
    assert 'id="editor-create-document"' in page.text

    assert "loadEditorContent" in js_response.text
    assert "saveEditorContent" in js_response.text
    assert "/content`" in js_response.text  # /admin/documents/{id}/content


def test_ui_system_health_console_wiring() -> None:
    client = TestClient(create_app())

    page = client.get("/")
    js_response = client.get("/static/app.js")

    assert 'data-console-panel="health"' in page.text
    assert 'id="health-checks"' in page.text
    assert 'id="refresh-health"' in page.text
    assert '"/admin/system-status"' in js_response.text
    assert "renderSystemHealth" in js_response.text


def test_ui_audit_log_renders_sortable_table() -> None:
    client = TestClient(create_app())

    js_response = client.get("/static/app.js")
    css_response = client.get("/static/app.css")

    assert "renderAuditTable" in js_response.text
    assert "table-sort-button" in js_response.text
    assert "AUDIT_COLUMNS" in js_response.text
    assert ".admin-table" in css_response.text


def test_ui_provider_logs_wiring() -> None:
    client = TestClient(create_app())

    page = client.get("/")
    js_response = client.get("/static/app.js")

    assert 'id="provider-logs"' in page.text
    assert "/admin/provider-logs?limit=50" in js_response.text
    assert "renderProviderLogs" in js_response.text


def test_ui_guardrail_blocked_badge_copy() -> None:
    client = TestClient(create_app())
    js_response = client.get("/static/app.js")
    assert "guardrail_blocked" in js_response.text
    assert "這個問題和課程學習無關" in js_response.text


def test_ui_runtime_settings_includes_router_and_hard_models() -> None:
    client = TestClient(create_app())
    page = client.get("/")
    assert 'id="settings-chat-model-hard"' in page.text
    assert 'id="settings-router-model"' in page.text


def test_ui_chat_toolbar_clear_export_report_wiring() -> None:
    client = TestClient(create_app())

    page = client.get("/")
    js_response = client.get("/static/app.js")

    assert 'id="chat-clear"' in page.text
    assert 'id="chat-export"' in page.text
    assert 'id="chat-report"' in page.text
    assert "🧹 清除對話" in page.text
    assert "⬇ 匯出 JSON" in page.text
    assert "🚩 回報問題" in page.text

    assert "function clearConversation" in js_response.text
    assert "function exportConversation" in js_response.text
    assert "async function reportConversation" in js_response.text
    assert "fetch(\"/chat/report\"" in js_response.text
    # 後續訊息帶上既有 conversation_id，done 事件再把它存回 state
    assert "payload.conversation_id = state.conversationId" in js_response.text
    assert "state.conversationId = payload.conversation_id" in js_response.text


def test_ui_logout_moved_to_sidebar_footer_with_emoji() -> None:
    client = TestClient(create_app())

    page = client.get("/")

    footer_markup = page.text.split('class="sidebar-footer"', 1)[1].split("</div>", 1)[0]
    assert 'id="platform-logout"' in footer_markup
    assert "🚪 登出" in footer_markup
    # brand 區不再有 logout 按鈕
    brand_markup = page.text.split('class="brand"', 1)[1].split("</div>", 1)[0]
    assert "platform-logout" not in brand_markup
