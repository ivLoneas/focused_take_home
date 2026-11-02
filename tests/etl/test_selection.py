"""Keep the newest balanced corpus, then process it in chronological order."""

from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from etl import __main__ as cli
from etl import runner
from etl.models import SourceDocument

FAANG = ["alphabet", "amazon", "apple", "meta", "netflix"]


def source(company, year, quarter="1", suffix="report"):
    path = f"{company}/{year}/{quarter or 'annual'}/{suffix}.pdf"
    return SourceDocument(
        document_id=path,
        path=path,
        sha256="a" * 64,
        company=company,
        fiscal_year=year,
        quarter=quarter,
        report_type="financial_report",
        title="Financial report",
        url="https://example.com/report",
        pages=1,
    )


@pytest.fixture
def select(monkeypatch, tmp_path):
    inventory, selected = [], []
    monkeypatch.setattr(runner, "load_manifest", lambda _: list(inventory))
    monkeypatch.setattr(runner, "build_converter", Mock(return_value=object()))
    monkeypatch.setattr(runner, "parser_config", lambda **_: {})
    monkeypatch.setattr(runner, "write_json", lambda *args: None)
    monkeypatch.setattr(runner, "read_chunks", lambda _: [])

    def prepare(item, *args):
        selected.append(item)
        return tmp_path / "artifacts", True

    monkeypatch.setattr(runner, "prepare_document", prepare)

    def run_selection(documents, **options):
        inventory[:] = documents
        selected.clear()
        report = runner.run(
            tmp_path / "raw",
            tmp_path / "silver",
            tmp_path / "cache",
            tmp_path / "report.json",
            "unused",
            None,
            parse_only=True,
            pictures=False,
            **options,
        )
        return list(selected), report

    return run_selection


def test_faang_selection_keeps_newest_100_and_excludes_older_reports(select):
    inventory = [
        source(company, year, str(quarter))
        for company in [*FAANG, "microsoft"]
        for year in range(2020, 2027)
        for quarter in range(1, 5)
    ]
    selected, report = select(list(reversed(inventory)), company=FAANG, per_company_limit=20, keep="newest")
    assert len(selected) == 100
    assert Counter(item.company for item in selected) == {company: 20 for company in FAANG}
    assert all(item.fiscal_year >= 2022 for item in selected)
    assert {item.document_id for item in selected} == {
        item.document_id for item in inventory if item.company in FAANG and item.fiscal_year >= 2022
    }
    for company in FAANG:
        periods = [(item.fiscal_year, int(item.quarter)) for item in selected if item.company == company]
        assert periods == sorted(periods), "Retained newest reports must still be processed chronologically"
    assert report["selection"]["documents"] == 100
    assert report["totals"]["documents_succeeded"] == 100


def test_selection_is_independent_of_manifest_and_company_argument_order(select):
    inventory = [
        source(company, year, str(quarter))
        for company in FAANG
        for year in range(2022, 2025)
        for quarter in range(1, 5)
    ]
    first, _ = select(inventory, company=FAANG, per_company_limit=5, keep="newest")
    second, _ = select(list(reversed(inventory)), company=list(reversed(FAANG)), per_company_limit=5, keep="newest")
    assert [item.document_id for item in first] == [item.document_id for item in second]


def test_newest_selection_is_processed_chronologically_with_annual_after_q4(select):
    inventory = [
        source("apple", 2024, "1"),
        source("apple", 2023, ""),
        source("apple", 2023, "4", "b"),
        source("apple", 2023, "4", "a"),
        source("apple", 2023, "3"),
        source("apple", 2022, ""),
    ]
    selected, _ = select(inventory, company=["apple"], per_company_limit=5, keep="newest")
    assert [(item.fiscal_year, item.quarter, Path(item.path).stem) for item in selected] == [
        (2023, "3", "report"),
        (2023, "4", "a"),
        (2023, "4", "b"),
        (2023, "", "report"),
        (2024, "1", "report"),
    ]


def test_newest_cutoff_retains_annual_report_over_q4(select):
    inventory = [source("apple", 2023, "4"), source("apple", 2023, ""), source("apple", 2024, "1")]
    selected, _ = select(inventory, company=["apple"], per_company_limit=2, keep="newest")
    assert [(item.fiscal_year, item.quarter) for item in selected] == [(2023, ""), (2024, "1")]


def test_legacy_single_company_string_still_filters(select):
    inventory = [source("amazon", 2022), source("apple", 2024), source("apple", 2022)]
    selected, _ = select(inventory, company="apple", limit=1)
    assert len(selected) == 1
    assert selected[0].company == "apple"


def test_duplicate_company_arguments_do_not_duplicate_documents(select):
    inventory = [source("apple", 2022), source("amazon", 2022), source("apple", 2023)]
    selected, _ = select(inventory, company=["apple", "apple"], per_company_limit=2, keep="newest")
    assert len(selected) == 2
    assert len({item.document_id for item in selected}) == 2


def test_per_company_limit_is_a_cap_when_fewer_documents_exist(select):
    inventory = [source("apple", 2022), source("amazon", 2022), source("amazon", 2023)]
    selected, _ = select(inventory, company=["apple", "amazon"], per_company_limit=20, keep="newest")
    assert Counter(item.company for item in selected) == {"apple": 1, "amazon": 2}


@pytest.mark.parametrize("limit", [0, -1])
def test_invalid_per_company_limit_fails(select, limit):
    with pytest.raises(ValueError, match="positive"):
        select([source("apple", 2022)], company=["apple"], per_company_limit=limit, keep="newest")


def test_unknown_requested_company_fails_instead_of_silently_unbalancing_corpus(select):
    with pytest.raises(ValueError):
        select([source("apple", 2022)], company=["apple", "missing-company"], per_company_limit=20, keep="newest")


def test_cli_accepts_repeated_companies_and_newest_per_company_limit():
    args = cli.parser().parse_args(
        ["run", "--company", "apple", "--company", "amazon", "--per-company-limit", "20", "--keep", "newest"]
    )
    assert args.company == ["apple", "amazon"]
    assert args.per_company_limit == 20
    assert args.keep == "newest"


def test_cli_forwards_all_companies_and_cap_to_runner(monkeypatch):
    run = Mock(return_value={"totals": {"documents_failed": 0}})
    monkeypatch.setattr(runner, "run", run)
    monkeypatch.setattr(
        cli,
        "Settings",
        lambda: SimpleNamespace(
            database_url="postgresql://test/database",
            openai_api_key=None,
        ),
    )
    assert (
        cli.main(
            [
                "run",
                "--parse-only",
                "--no-pictures",
                "--company",
                "apple",
                "--company",
                "amazon",
                "--per-company-limit",
                "20",
                "--keep",
                "newest",
            ]
        )
        == 0
    )
    assert run.call_args.kwargs["company"] == ["apple", "amazon"]
    assert run.call_args.kwargs["per_company_limit"] == 20
    assert run.call_args.kwargs["keep"] == "newest"


def test_invalid_retention_policy_fails(select):
    with pytest.raises(ValueError):
        select([source("apple", 2022)], company=["apple"], per_company_limit=1, keep="arbitrary")
