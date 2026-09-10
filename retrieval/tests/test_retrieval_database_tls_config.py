from pydantic import SecretStr

from beken_retrieval.config import RetrievalSettings


def test_hosted_corpus_database_requires_hostname_verified_tls() -> None:
    settings = RetrievalSettings(
        _env_file=None,
        supabase_db_url=SecretStr(
            "postgresql://hosted/database?application_name=beken&sslmode=require"
        ),
    )

    assert settings.corpus_database_url == (
        "postgresql://hosted/database?application_name=beken&sslmode=verify-full"
    )


def test_hosted_corpus_database_uses_configured_supabase_ca() -> None:
    settings = RetrievalSettings(
        _env_file=None,
        supabase_db_url=SecretStr("postgresql://hosted/database?sslmode=require"),
        supabase_db_ssl_root_cert="/etc/bekenai/supabase-ca.crt",
    )

    assert settings.corpus_database_url == (
        "postgresql://hosted/database?"
        "sslrootcert=%2Fetc%2Fbekenai%2Fsupabase-ca.crt&sslmode=verify-full"
    )


def test_local_corpus_database_url_is_not_rewritten() -> None:
    settings = RetrievalSettings(
        _env_file=None,
        database_url="postgresql://localhost/beken?sslmode=disable",
        supabase_db_url=None,
    )

    assert settings.corpus_database_url == "postgresql://localhost/beken?sslmode=disable"
