"""Integer configuration must work through textual environment sources."""

import pytest
from pydantic import ValidationError

from backend.config import Settings


@pytest.fixture(autouse=True)
def isolated_numeric_settings(monkeypatch, tmp_path):
    monkeypatch.delenv("RETRIEVAL_LIMIT", raising=False)
    monkeypatch.delenv("MAX_QUESTION_LENGTH", raising=False)
    monkeypatch.chdir(tmp_path)


def load_text_settings(source, values, monkeypatch, tmp_path):
    if source == "environment":
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        return Settings(_env_file=None)

    dotenv = tmp_path / ".env"
    dotenv.write_text("".join(f"{name}='{value}'\n" for name, value in values.items()), encoding="utf-8")
    return Settings(_env_file=dotenv)


@pytest.mark.parametrize("source", ["environment", "dotenv"])
@pytest.mark.parametrize("retrieval_limit,max_question_length", [(5, 2000), (1, 1), (100, 4000)])
def test_integer_settings_load_from_text_sources(source, retrieval_limit, max_question_length, monkeypatch, tmp_path):
    settings = load_text_settings(
        source,
        {"RETRIEVAL_LIMIT": str(retrieval_limit), "MAX_QUESTION_LENGTH": str(max_question_length)},
        monkeypatch,
        tmp_path,
    )

    assert settings.retrieval_limit == retrieval_limit
    assert type(settings.retrieval_limit) is int
    assert settings.max_question_length == max_question_length
    assert type(settings.max_question_length) is int


@pytest.mark.parametrize("source", ["environment", "dotenv"])
@pytest.mark.parametrize(
    "name,value",
    [
        ("RETRIEVAL_LIMIT", ""),
        ("RETRIEVAL_LIMIT", " "),
        ("RETRIEVAL_LIMIT", "five"),
        ("RETRIEVAL_LIMIT", "5.5"),
        ("RETRIEVAL_LIMIT", "true"),
        ("RETRIEVAL_LIMIT", "0"),
        ("RETRIEVAL_LIMIT", "101"),
        ("MAX_QUESTION_LENGTH", ""),
        ("MAX_QUESTION_LENGTH", "invalid"),
        ("MAX_QUESTION_LENGTH", "2000.0"),
        ("MAX_QUESTION_LENGTH", "false"),
        ("MAX_QUESTION_LENGTH", "0"),
        ("MAX_QUESTION_LENGTH", "-1"),
    ],
)
def test_invalid_text_integer_settings_are_rejected(source, name, value, monkeypatch, tmp_path):
    with pytest.raises(ValidationError) as caught:
        load_text_settings(source, {name: value}, monkeypatch, tmp_path)

    assert any(error["loc"] == (name.lower(),) for error in caught.value.errors())


@pytest.mark.parametrize("field", ["retrieval_limit", "max_question_length"])
@pytest.mark.parametrize("value", [True, False, 1.0, 1.5, "1.5", "true", "invalid"])
def test_constructor_inputs_do_not_coerce_non_integer_values(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value}, _env_file=None)


def test_environment_integer_settings_override_dotenv(monkeypatch, tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("RETRIEVAL_LIMIT=5\nMAX_QUESTION_LENGTH=2000\n", encoding="utf-8")
    monkeypatch.setenv("RETRIEVAL_LIMIT", "8")
    monkeypatch.setenv("MAX_QUESTION_LENGTH", "3000")

    settings = Settings(_env_file=dotenv)

    assert settings.retrieval_limit == 8
    assert settings.max_question_length == 3000


def test_integer_defaults_work_without_text_overrides():
    settings = Settings(_env_file=None)

    assert settings.retrieval_limit == 5
    assert settings.max_question_length == 2000
