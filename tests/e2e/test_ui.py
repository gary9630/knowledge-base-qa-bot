from fastapi.testclient import TestClient

from app.main import create_app


def test_ui_serves_three_column_workbench() -> None:
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "Chat" in response.text
    assert "Mindmap" in response.text
    assert "Admin Uploads" in response.text
    assert "Feedback / Evals" in response.text
    assert "answer sources" in response.text.lower()
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


def test_ui_exposes_eval_workbench_wiring() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    js_response = client.get("/static/app.js")

    assert response.status_code == 200
    assert 'id="tab-evals"' in response.text
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
    assert 'id="admin-key"' in response.text
    assert 'id="eval-admin-key"' in response.text
    assert "getJsonWithHeaders(\"/auth/session\"" in js_response.text
    assert "fetch(\"/auth/login\"" in js_response.text
    assert "fetch(\"/auth/logout\"" in js_response.text
    assert "X-KB-CSRF-Token" in js_response.text


def test_ui_serves_student_landing_page_and_marks_admin_surfaces() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    css_response = client.get("/static/app.css")

    assert response.status_code == 200
    assert 'id="landing-preview"' in response.text
    assert 'id="landing-trust-strip"' in response.text
    assert "Course Assistant" in response.text
    assert "Student sign in" in response.text
    assert 'id="tab-chat"' in response.text
    assert 'id="tab-mindmap"' in response.text
    assert 'id="tab-sources"' in response.text
    for tab_id in ("tab-uploads", "tab-ops", "tab-audit", "tab-evals"):
        tab_markup = response.text.split(f'id="{tab_id}"', 1)[1].split(">", 1)[0]
        assert "data-admin-only" in tab_markup

    for panel_id in ("panel-uploads", "panel-ops", "panel-audit", "panel-evals"):
        panel_markup = response.text.split(f'id="{panel_id}"', 1)[1].split(">", 1)[0]
        assert "data-admin-only" in panel_markup

    document_form_markup = response.text.split('id="document-lifecycle-form"', 1)[1].split(
        ">",
        1,
    )[0]
    document_section_markup = response.text.split('id="admin-documents-section"', 1)[1].split(
        ">",
        1,
    )[0]
    assert "data-admin-only" in document_form_markup
    assert "data-admin-only" in document_section_markup

    assert css_response.status_code == 200
    assert "[hidden]" in css_response.text
    assert ".landing-copy" in css_response.text
    assert ".landing-preview" in css_response.text
    assert ".landing-trust-strip" in css_response.text


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
    assert 'id="tab-audit"' in response.text
    assert 'id="panel-audit"' in response.text
    assert 'id="audit-admin-key"' in response.text
    assert 'id="audit-event-type"' in response.text
    assert 'id="audit-outcome"' in response.text
    assert 'id="audit-actor-type"' in response.text
    assert 'id="audit-limit"' in response.text
    assert 'id="refresh-audit"' in response.text
    assert 'id="audit-events"' in response.text
    assert "fetch(`/admin/audit-events?${params}`" in js_response.text
    assert "renderAuditEvents" in js_response.text
    assert "elements.auditAdminKey" in js_response.text


def test_ui_exposes_document_lifecycle_wiring() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    js_response = client.get("/static/app.js")

    assert response.status_code == 200
    assert 'id="document-admin-key"' in response.text
    assert 'id="refresh-documents"' in response.text
    assert 'id="admin-documents"' in response.text
    assert "fetch(\"/admin/documents\"" in js_response.text
    assert "fetch(`/admin/documents/${documentId}/lifecycle`" in js_response.text
    assert "fetch(`/admin/documents/${documentId}`" in js_response.text
    assert "fetch(`/admin/documents/${documentId}/reindex`" in js_response.text
    assert "renderAdminDocuments" in js_response.text
    assert "elements.documentAdminKey" in js_response.text


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
    assert 'id="tab-ops"' in response.text
    assert 'id="panel-ops"' in response.text
    assert 'id="ops-admin-key"' in response.text
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


def test_ui_exposes_answer_quality_wiring() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    js_response = client.get("/static/app.js")

    assert response.status_code == 200
    assert 'id="answer-quality"' in response.text
    assert "renderAnswerQuality" in js_response.text
    assert "retrieval_diagnostics" in js_response.text
    assert "answer_quality" in js_response.text
    assert "scoreBreakdownText" in js_response.text
    assert "source.debug_scores" in js_response.text
    assert "cannot_confirm_reason" in js_response.text


def test_ui_exposes_learner_chat_polish_wiring() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    js_response = client.get("/static/app.js")
    css_response = client.get("/static/app.css")

    assert response.status_code == 200
    assert 'id="learner-chat-status"' in response.text
    assert 'id="chat-empty-state"' in response.text
    assert "Course Assistant" in response.text
    assert "data-sample-prompt" in response.text
    assert 'id="chat-composer-status"' in response.text
    assert 'id="chat-submit"' in response.text
    assert 'id="markdown-preview" tabindex="0"' in response.text
    assert "Ask about course policies, homework, or Network Essentials" in response.text

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
    assert "Looking through course sources" in js_response.text
    assert "Answered from" in js_response.text
    assert "could not confirm" in js_response.text
    assert "previewCandidate(source)" in js_response.text
    assert "renderAnswerCitations" in js_response.text
    assert "citationLabelForSource" in js_response.text
    assert "submitAnswerFeedback" in js_response.text
    assert "feedbackExpectedSource" in js_response.text
    assert 'fetch("/feedback"' in js_response.text

    assert css_response.status_code == 200
    assert ".chat-empty-state" in css_response.text
    assert ".sample-prompt-grid" in css_response.text
    assert ".answer-footer" in css_response.text
    assert ".source-chip" in css_response.text
    assert ".answer-trust" in css_response.text
    assert ".inline-citation" in css_response.text
    assert ".answer-feedback" in css_response.text


def test_ui_separates_answer_sources_from_previewed_source() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    js_response = client.get("/static/app.js")
    css_response = client.get("/static/app.css")

    assert response.status_code == 200
    assert "Answer Sources" in response.text
    assert 'id="answer-sources"' in response.text
    assert 'id="preview-source-meta"' in response.text
    assert "Previewed Source" in response.text
    assert "No answer sources for the latest response." in response.text

    assert js_response.status_code == 200
    assert "documentDisplayTitle" in js_response.text
    assert "documentSourceSummary" in js_response.text
    assert "renderPreviewSourceMeta" in js_response.text
    assert "No preview selected." in js_response.text
    preview_document_body = js_response.text.split("async function previewDocument", 1)[1].split(
        "async function formatDocumentPreview", 1
    )[0]
    assert "setSelectedSources" not in preview_document_body

    assert css_response.status_code == 200
    assert ".preview-source-meta" in css_response.text
    assert ".source-title" in css_response.text


def test_ui_exposes_mindmap_on_demand_wiring() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    js_response = client.get("/static/app.js")

    assert response.status_code == 200
    assert 'id="load-mindmap"' in response.text
    assert "getJson(\"/mindmap\"" in js_response.text
    assert "loadMindmap" in js_response.text
    assert "refreshMindmapAfterContentChange" in js_response.text
    init_body = js_response.text.split("function init() {", 1)[1].split("}", 1)[0]
    assert "loadMindmap" not in init_body
