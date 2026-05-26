from sqlalchemy import Engine, inspect, text


def test_initial_migration_creates_core_tables(db_engine: Engine) -> None:
    with db_engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        inspector = inspect(connection)

        table_names = set(inspector.get_table_names())

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
    }.issubset(table_names)
