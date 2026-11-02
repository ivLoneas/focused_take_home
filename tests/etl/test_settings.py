"""ETL configuration and CLI credential handling contracts."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from etl import __main__ as cli
from etl import runner
from etl.settings import Settings

DEFAULT_DATABASE_URL = "postgresql://rag:rag_local@localhost:55432/rag"


@pytest.fixture(autouse=True)
def isolate_settings_environment(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_settings_defaults_without_environment_or_dotenv():
    settings = Settings(_env_file=None)

    assert settings.database_url == DEFAULT_DATABASE_URL
    assert settings.openai_api_key is None


def test_settings_loads_default_dotenv_and_ignores_unrelated_keys(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql://dotenv/database\n"
        "OPENAI_API_KEY=dotenv-secret\n"
        "UNRELATED_APPLICATION_SETTING=ignored\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    assert settings.database_url == "postgresql://dotenv/database"
    assert isinstance(settings.openai_api_key, SecretStr)
    assert settings.openai_api_key.get_secret_value() == "dotenv-secret"


def test_environment_overrides_dotenv(monkeypatch, tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "DATABASE_URL=postgresql://dotenv/database\nOPENAI_API_KEY=dotenv-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql://environment/database")
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")

    settings = Settings(_env_file=dotenv)

    assert settings.database_url == "postgresql://environment/database"
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "environment-secret"


def test_constructor_arguments_override_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://environment/database")
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")

    settings = Settings(
        database_url="postgresql://constructor/database",
        openai_api_key="constructor-secret",
        _env_file=None,
    )

    assert settings.database_url == "postgresql://constructor/database"
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "constructor-secret"


@pytest.mark.parametrize("value", ["", " ", "\t\n"])
def test_blank_environment_api_key_is_normalized_to_missing(monkeypatch, value):
    monkeypatch.setenv("OPENAI_API_KEY", value)

    assert Settings(_env_file=None).openai_api_key is None


@pytest.mark.parametrize("value", ["", " ", "\t\n"])
def test_blank_constructor_api_key_is_normalized_to_missing(value):
    assert Settings(openai_api_key=value, _env_file=None).openai_api_key is None


def settings(database_url: str = "postgresql://settings/database", api_key: str | None = None):
    secret = SecretStr(api_key) if api_key is not None else None
    return SimpleNamespace(database_url=database_url, openai_api_key=secret)


def successful_run():
    return {"totals": {"documents_failed": 0}}


def test_parse_only_without_pictures_does_not_require_api_key(monkeypatch):
    openai_factory = Mock()
    run = Mock(return_value=successful_run())
    monkeypatch.setattr(cli, "Settings", lambda: settings())
    monkeypatch.setattr(runner, "run", run)
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=openai_factory))

    assert cli.main(["run", "--parse-only", "--no-pictures"]) == 0
    assert run.call_args.args[4] == "postgresql://settings/database"
    assert run.call_args.args[5] is None
    assert run.call_args.kwargs["pictures"] is False
    openai_factory.assert_not_called()


@pytest.mark.parametrize("arguments", [[], ["--parse-only"]])
def test_picture_or_embedding_run_rejects_missing_api_key_before_work(monkeypatch, arguments):
    openai_factory = Mock()
    run = Mock(return_value=successful_run())
    monkeypatch.setattr(cli, "Settings", lambda: settings())
    monkeypatch.setattr(runner, "run", run)
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=openai_factory))

    with pytest.raises(SystemExit, match="OPENAI_API_KEY"):
        cli.main(["run", *arguments])

    openai_factory.assert_not_called()
    run.assert_not_called()


@pytest.mark.parametrize("arguments", [[], ["--parse-only"]])
def test_picture_or_embedding_run_forwards_explicit_secret_to_openai(monkeypatch, arguments):
    client = object()
    openai_factory = Mock(return_value=client)
    run = Mock(return_value=successful_run())
    monkeypatch.setattr(cli, "Settings", lambda: settings(api_key="explicit-secret"))
    monkeypatch.setattr(runner, "run", run)
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=openai_factory))

    assert cli.main(["run", *arguments]) == 0

    openai_factory.assert_called_once_with(api_key="explicit-secret")
    assert run.call_args.args[5] is client


def test_database_url_argument_overrides_settings(monkeypatch):
    run = Mock(return_value=successful_run())
    monkeypatch.setattr(cli, "Settings", lambda: settings())
    monkeypatch.setattr(runner, "run", run)

    assert cli.main(["run", "--parse-only", "--no-pictures", "--database-url", "postgresql://argument/database"]) == 0
    assert run.call_args.args[4] == "postgresql://argument/database"
