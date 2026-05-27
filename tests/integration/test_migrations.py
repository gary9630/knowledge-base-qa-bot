from sqlalchemy import Engine, inspect, text


def test_initial_migration_creates_core_tables(db_engine: Engine) -> None:
    with db_engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        inspector = inspect(connection)

        table_names = set(inspector.get_table_names())
        document_columns = {column["name"] for column in inspector.get_columns("documents")}
        document_indexes = {index["name"] for index in inspector.get_indexes("documents")}
        eval_case_columns = {column["name"] for column in inspector.get_columns("eval_cases")}
        eval_run_columns = {column["name"] for column in inspector.get_columns("eval_runs")}
        eval_case_indexes = {index["name"] for index in inspector.get_indexes("eval_cases")}
        eval_run_indexes = {index["name"] for index in inspector.get_indexes("eval_runs")}

    assert {
        "documents",
        "sections",
        "chunks",
            "indexing_jobs",
            "ingestion_jobs",
            "conversations",
            "messages",
            "retrieval_events",
        "feedback",
        "eval_cases",
        "eval_runs",
        "eval_results",
    }.issubset(table_names)
    assert {"lifecycle_status", "lifecycle_reason"}.issubset(document_columns)
    assert "ix_documents_lifecycle_status" in document_indexes
    assert {"source_kind", "seed_key", "promoted_feedback_id"}.issubset(eval_case_columns)
    assert "trigger" in eval_run_columns
    assert {
        "ux_eval_cases_seed_key",
        "ux_eval_cases_promoted_feedback_id",
        "ix_eval_cases_source_kind",
    }.issubset(eval_case_indexes)
    assert "ix_eval_runs_trigger_created_at" in eval_run_indexes
