"""Explicit routing for the pinned five-company retrieval corpus."""

from typing import Literal, cast

Company = Literal["Alphabet", "Amazon", "Apple", "Meta", "Netflix"]

COMPANY_TABLES: dict[Company, str] = {
    "Alphabet": "etl_chunks_alphabet",
    "Amazon": "etl_chunks_amazon",
    "Apple": "etl_chunks_apple",
    "Meta": "etl_chunks_meta",
    "Netflix": "etl_chunks_netflix",
}


def require_company(company: object) -> Company:
    """Require a canonical tool literal before any embedding or database work."""
    if not isinstance(company, str):
        raise TypeError("company must be a string")
    if company not in COMPANY_TABLES:
        raise ValueError(f"company must be one of: {', '.join(COMPANY_TABLES)}")
    return cast(Company, company)


def source_company(company: str) -> Company:
    """Route manifest metadata without changing its original casing."""
    return require_company(company.capitalize())
