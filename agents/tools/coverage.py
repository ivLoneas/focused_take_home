"""Discover published report coverage from PostgreSQL, without a prompt inventory."""

from collections.abc import Callable
from typing import Any

from langchain_core.tools import StructuredTool

from utils import require_nonblank_string


class DatabaseCoverage:
    """Expose fresh database metadata through traced LangChain tools."""

    def __init__(self, *, connection_factory: Callable[[], Any]) -> None:
        self.connection_factory = connection_factory
        self.listed_companies = StructuredTool.from_function(
            self._listed_companies,
            name="listed_companies",
            description="Return all companies with reports currently published in the database.",
        )
        self.company_periods = StructuredTool.from_function(
            self._company_periods,
            name="company_periods",
            description=(
                "Return a company's available fiscal quarter intervals and annual report years. "
                "Use a company name returned by listed_companies. Consecutive quarters are merged, "
                "for example Q3FY2025-Q2FY2026; gaps remain separate intervals. "
                "Annual report availability is separate and quarter coverage does not guarantee a metric."
            ),
        )

    def _listed_companies(self) -> list[str]:
        connection = self.connection_factory()
        try:
            rows = connection.execute("SELECT DISTINCT company FROM etl_documents ORDER BY company").fetchall()
            return sorted({name.capitalize() if name.islower() else name for (name,) in rows})
        finally:
            connection.close()

    def _company_periods(self, company: str) -> dict[str, Any]:
        company = require_nonblank_string(company, field_name="company")
        connection = self.connection_factory()
        try:
            rows = connection.execute(
                "SELECT DISTINCT fiscal_year, quarter, report_type FROM etl_documents "
                "WHERE lower(company) = lower(%s) ORDER BY fiscal_year, quarter, report_type",
                (company,),
            ).fetchall()
            # Preserve every quarter independently; merge only at the tool output boundary.
            quarters: set[int] = set()
            annual_years: set[int] = set()
            for year, quarter, report_type in rows:
                if isinstance(year, bool) or not isinstance(year, int) or year < 1:
                    raise ValueError("Invalid fiscal year in database coverage")
                if quarter not in {"", "1", "2", "3", "4"}:
                    raise ValueError("Invalid fiscal quarter in database coverage")
                if report_type == "annual_report":
                    annual_years.add(year)
                if quarter:
                    quarters.add(year * 4 + int(quarter) - 1)
            intervals = []
            first = last = None
            for quarter in sorted(quarters):
                if last is not None and quarter != last + 1:
                    intervals.append(_interval(first, last))
                    first = None
                if first is None:
                    first = quarter
                last = quarter
            if first is not None:
                intervals.append(_interval(first, last))
            return {
                "company": company,
                "intervals": intervals,
                "annual_reports": [f"FY{year}" for year in sorted(annual_years)],
            }
        finally:
            connection.close()


def _interval(first: int, last: int) -> str:
    start = f"Q{first % 4 + 1}FY{first // 4}"
    end = f"Q{last % 4 + 1}FY{last // 4}"
    return start if first == last else f"{start}-{end}"
