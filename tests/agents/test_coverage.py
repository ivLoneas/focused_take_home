"""Database-backed discovery contracts, independent of the active manifest."""

from unittest.mock import Mock

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tools import StructuredTool
from pydantic import ValidationError


def coverage_with_rows(rows):
    from agents.tools import DatabaseCoverage

    connection = Mock()
    connection.execute.return_value.fetchall.return_value = rows
    factory = Mock(return_value=connection)
    return DatabaseCoverage(connection_factory=factory), connection, factory


def test_listed_companies_uses_current_database_rows_without_a_pinned_allowlist():
    coverage, connection, factory = coverage_with_rows([("netflix",), ("tesla",), ("apple",), ("apple",)])

    assert isinstance(coverage.listed_companies, StructuredTool)
    assert coverage.listed_companies.name == "listed_companies"
    assert coverage.listed_companies.invoke({}) == ["Apple", "Netflix", "Tesla"]
    factory.assert_called_once_with()
    query = str(connection.execute.call_args.args[0]).lower()
    assert "distinct" in query and "company" in query and "etl_documents" in query
    connection.close.assert_called_once_with()


def test_discovery_does_not_cache_an_old_database_inventory():
    coverage, connection, _ = coverage_with_rows([])
    connection.execute.return_value.fetchall.side_effect = [[], [("tesla",)]]

    assert coverage.listed_companies.invoke({}) == []
    assert coverage.listed_companies.invoke({}) == ["Tesla"]
    assert connection.close.call_count == 2


def test_periods_merge_only_adjacent_quarters_across_year_boundaries():
    coverage, connection, _ = coverage_with_rows([
        (2026, "2", "earnings_report"), (2025, "4", "annual_report"),
        (2025, "3", "earnings_report"), (2026, "1", "earnings_report"),
        (2025, "3", "earnings_report"), (2026, "4", "earnings_report"),
        (2028, "1", "earnings_report"), (2024, "", "annual_report"),
        (2025, "4", "annual_report"),
    ])

    assert isinstance(coverage.company_periods, StructuredTool)
    assert coverage.company_periods.name == "company_periods"
    assert coverage.company_periods.invoke({"company": "Apple"}) == {
        "company": "Apple",
        "intervals": ["Q3FY2025-Q2FY2026", "Q4FY2026", "Q1FY2028"],
        "annual_reports": ["FY2024", "FY2025"],
    }
    args = connection.execute.call_args.args
    query = str(args[0]).lower()
    assert "etl_documents" in query and "fiscal_year" in query and "quarter" in query
    assert "distinct" in query and "where" in query and "%s" in query
    assert "apple" not in query
    assert args[1][0].lower() == "apple"
    assert "lower" in query or "ilike" in query
    connection.close.assert_called_once_with()


@pytest.mark.parametrize("company", ["Apple", "Unknown Issuer", "x'); DROP TABLE etl_documents; --"])
def test_unknown_company_and_empty_database_return_no_periods(company):
    coverage, connection, _ = coverage_with_rows([])

    assert coverage.company_periods.invoke({"company": company}) == {
        "company": company, "intervals": [], "annual_reports": [],
    }
    assert company not in str(connection.execute.call_args.args[0])
    connection.close.assert_called_once_with()


def test_annual_report_does_not_fabricate_quarter_coverage():
    coverage, _, _ = coverage_with_rows([(2025, "", "annual_report")])

    assert coverage.company_periods.invoke({"company": "Apple"}) == {
        "company": "Apple", "intervals": [], "annual_reports": ["FY2025"],
    }


@pytest.mark.parametrize("company", [None, 42, True, [], "", " \t\n"])
def test_company_input_is_validated_before_opening_database(company):
    coverage, _, factory = coverage_with_rows([])

    with pytest.raises((TypeError, ValueError, ValidationError)):
        coverage.company_periods.invoke({"company": company})
    factory.assert_not_called()


@pytest.mark.parametrize("row", [(0, "1"), (-2025, "1"), (True, "1"), (2025, "0"), (2025, "5"), (2025, "bad")])
def test_invalid_database_periods_fail_clearly_and_close_connection(row):
    coverage, connection, _ = coverage_with_rows([(*row, "earnings_report")])

    with pytest.raises((TypeError, ValueError), match="year|quarter|period"):
        coverage.company_periods.invoke({"company": "Apple"})
    connection.close.assert_called_once_with()


@pytest.mark.parametrize("name,arguments", [("listed_companies", {}), ("company_periods", {"company": "Apple"})])
def test_database_failures_propagate_with_tool_error_events_and_connection_cleanup(name, arguments):
    coverage, connection, _ = coverage_with_rows([])
    error = RuntimeError("database unavailable")
    connection.execute.side_effect = error

    class Events(BaseCallbackHandler):
        def __init__(self):
            self.started = []
            self.errors = []

        def on_tool_start(self, serialized, input_str, **kwargs):
            self.started.append(serialized["name"])

        def on_tool_error(self, received, **kwargs):
            self.errors.append(received)

    events = Events()
    with pytest.raises(RuntimeError, match="database unavailable") as raised:
        getattr(coverage, name).invoke(arguments, config={"callbacks": [events]})

    assert raised.value is error
    assert events.started == [name]
    assert events.errors == [error]
    connection.close.assert_called_once_with()


def test_q4_annual_report_preserves_only_its_actual_quarter_and_annual_evidence():
    coverage, _, _ = coverage_with_rows([(2025, "4", "annual_report")])
    assert coverage.company_periods.invoke({"company": "Apple"}) == {
        "company": "Apple", "intervals": ["Q4FY2025"], "annual_reports": ["FY2025"],
    }


def test_four_quarters_do_not_claim_an_annual_report_exists():
    coverage, _, _ = coverage_with_rows([(2025, str(quarter), "earnings_report") for quarter in range(1, 5)])
    assert coverage.company_periods.invoke({"company": "Apple"}) == {
        "company": "Apple", "intervals": ["Q1FY2025-Q4FY2025"], "annual_reports": [],
    }
