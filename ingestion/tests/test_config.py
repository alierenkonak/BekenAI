from pydantic import SecretStr

from beken_ingestion.config import IngestionSettings


def test_hosted_metadata_url_takes_precedence_without_changing_local_database_url() -> None:
    settings = IngestionSettings(
        _env_file=None,
        database_url="postgresql://local/database",
        supabase_db_url=SecretStr("postgresql://hosted/database"),
    )

    assert settings.database_url == "postgresql://local/database"
    assert settings.metadata_database_url == "postgresql://hosted/database?sslmode=verify-full"


def test_hosted_metadata_url_enforces_ssl_and_preserves_other_parameters() -> None:
    settings = IngestionSettings(
        _env_file=None,
        supabase_db_url=SecretStr(
            "postgresql://hosted/database?application_name=beken&sslmode=disable"
        ),
    )

    assert settings.metadata_database_url == (
        "postgresql://hosted/database?application_name=beken&sslmode=verify-full"
    )


def test_hosted_metadata_url_does_not_downgrade_full_verification() -> None:
    settings = IngestionSettings(
        _env_file=None,
        supabase_db_url=SecretStr(
            "postgresql://hosted/database?sslrootcert=system&sslmode=verify-full"
        ),
    )

    assert settings.metadata_database_url == (
        "postgresql://hosted/database?sslrootcert=system&sslmode=verify-full"
    )


def test_hosted_metadata_url_uses_configured_supabase_ca() -> None:
    settings = IngestionSettings(
        _env_file=None,
        supabase_db_url=SecretStr("postgresql://hosted/database?sslmode=require"),
        supabase_db_ssl_root_cert="/etc/bekenai/supabase-ca.crt",
    )

    assert settings.metadata_database_url == (
        "postgresql://hosted/database?"
        "sslrootcert=%2Fetc%2Fbekenai%2Fsupabase-ca.crt&sslmode=verify-full"
    )


def test_local_database_is_the_safe_fallback() -> None:
    settings = IngestionSettings(
        _env_file=None,
        database_url="postgresql://local/database",
        supabase_db_url=None,
    )

    assert settings.metadata_database_url == "postgresql://local/database"
