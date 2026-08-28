from pydantic import SecretStr

from beken_ingestion.config import IngestionSettings


def test_hosted_metadata_url_takes_precedence_without_changing_local_database_url() -> None:
    settings = IngestionSettings(
        database_url="postgresql://local/database",
        supabase_db_url=SecretStr("postgresql://hosted/database"),
    )

    assert settings.database_url == "postgresql://local/database"
    assert settings.metadata_database_url == "postgresql://hosted/database?sslmode=require"


def test_hosted_metadata_url_enforces_ssl_and_preserves_other_parameters() -> None:
    settings = IngestionSettings(
        supabase_db_url=SecretStr(
            "postgresql://hosted/database?application_name=beken&sslmode=disable"
        ),
    )

    assert settings.metadata_database_url == (
        "postgresql://hosted/database?application_name=beken&sslmode=require"
    )


def test_local_database_is_the_safe_fallback() -> None:
    settings = IngestionSettings(
        database_url="postgresql://local/database",
        supabase_db_url=None,
    )

    assert settings.metadata_database_url == "postgresql://local/database"
