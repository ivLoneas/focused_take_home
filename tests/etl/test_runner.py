"""Regression for runner-owned PostgreSQL transaction boundaries."""

from unittest.mock import Mock

import pytest

from etl import runner


def test_runner_opens_autocommit_connection_for_per_document_publication(monkeypatch, tmp_path):
    # initialize/is_current issue SQL before replace_document's transaction.
    # Without autocommit, that transaction is merely a savepoint and publishing
    # remains invisible to other connections until the outer transaction commits.
    monkeypatch.setattr(runner, "load_manifest", lambda _: [object()])
    monkeypatch.setattr(runner, "build_converter", lambda **_: object())
    monkeypatch.setattr(runner, "parser_config", lambda **_: {})
    connect = Mock(side_effect=RuntimeError("connection arguments captured"))
    monkeypatch.setattr(runner.psycopg, "connect", connect)

    with pytest.raises(RuntimeError, match="connection arguments captured"):
        runner.run(
            raw_dir=tmp_path / "raw", silver_dir=tmp_path / "silver",
            cache_dir=tmp_path / "cache", report_path=tmp_path / "report.json",
            database_url="postgresql://unused/test", openai_client=None,
            pictures=False,
        )

    connect.assert_called_once_with("postgresql://unused/test", autocommit=True)
