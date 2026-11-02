"""The evaluation corpus must match the active newest-100 FAANG retrieval set."""

import csv
import re
from collections import Counter
from pathlib import Path

import pytest

from etl.manifest import load_manifest
from etl.runner import _select_sources

ROOT = Path(__file__).resolve().parents[2]
FAANG = ("alphabet", "amazon", "apple", "meta", "netflix")
TOPICS = {
    "deterministic_accuracy", "tool_usage", "out_of_distribution", "multiple_companies",
    "conditional_reasoning", "in_domain_no_data", "extra_calculation", "ambiguous_questions",
    "image_questions", "table_questions", "formatting_questions",
}
NEGATIVE_TOPICS = {"out_of_distribution", "in_domain_no_data"}
PDF_REFERENCE = re.compile(r"data/raw/[^\s\"'()<>,;]+?\.pdf", re.IGNORECASE)


@pytest.fixture(scope="module")
def evaluation_rows():
    with (ROOT / "evals/evals_tests.csv").open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


@pytest.fixture(scope="module")
def corpus():
    inventory = load_manifest(ROOT / "data/raw")
    active = load_manifest(ROOT / "data/raw", manifest_path=ROOT / "data/active_manifest.csv")
    assert len(active) == 100
    assert Counter(item.company for item in active) == {company: 20 for company in FAANG}
    return inventory, {f"data/raw/{item.path}" for item in active}


def test_evaluation_has_114_unique_ids_with_coverage_and_formatting_cases(evaluation_rows):
    assert len(evaluation_rows) == 114
    ids = [row["id"].strip() for row in evaluation_rows]
    assert all(ids), "Every evaluation row needs a nonempty ID"
    assert len(set(ids)) == 114, "Evaluation IDs must be unique"
    expected = {topic: 10 for topic in TOPICS}
    expected["deterministic_accuracy"] = 11
    expected["ambiguous_questions"] = 9
    expected["tool_usage"] = 14
    assert Counter(row["topic"] for row in evaluation_rows) == expected


def test_active_corpus_manifest_matches_dynamic_newest_100(corpus):
    inventory, _ = corpus
    active, _ = _select_sources(inventory, company=FAANG, per_company_limit=20,
                                limit=None, keep="newest")
    with (ROOT / "data/raw/manifest.csv").open(newline="", encoding="utf-8") as stream:
        raw_reader = csv.DictReader(stream)
        raw_rows = list(raw_reader)
        raw_fields = raw_reader.fieldnames
    with (ROOT / "data/active_manifest.csv").open(newline="", encoding="utf-8") as stream:
        active_reader = csv.DictReader(stream)
        rows = list(active_reader)
        active_fields = active_reader.fieldnames
    assert active_fields == raw_fields, "Active manifest must preserve the full raw-manifest schema"
    assert len(rows) == 100
    assert len({row["path"] for row in rows}) == 100, "Active corpus paths must be unique"
    assert Counter(row["company"] for row in rows) == {company: 20 for company in FAANG}
    assert {(row["path"], row["sha256"], row["company"]) for row in rows} == {
        (source.path, source.sha256, source.company) for source in active
    }, "Pinned eval corpus paths/checksums must exactly match the current newest-100 selection"
    selected_paths = {source.path for source in active}
    assert {row["path"]: row for row in rows} == {
        row["path"]: row for row in raw_rows if row["path"] in selected_paths
    }, "Every active-manifest field must exactly match its authoritative raw-manifest row"


def test_all_cited_pdf_paths_belong_to_active_newest_100(evaluation_rows, corpus):
    _, active_paths = corpus
    unsupported = []
    for row in evaluation_rows:
        cited_paths = set(PDF_REFERENCE.findall("\n".join(row.values())))
        unsupported.extend(f"{row['id']}: {path}" for path in sorted(cited_paths - active_paths))
    assert not unsupported, "Evaluation cites PDFs outside the active retrieval corpus:\n" + "\n".join(unsupported)


def test_grounded_topics_do_not_reference_excluded_companies(evaluation_rows, corpus):
    inventory, _ = corpus
    excluded = sorted({item.company for item in inventory} - set(FAANG))
    patterns = {company: re.compile(rf"\b{re.escape(company)}\b", re.IGNORECASE) for company in excluded}
    unsupported = []
    for row in evaluation_rows:
        if row["topic"] in NEGATIVE_TOPICS:
            continue
        content = "\n".join(row.values())
        companies = [company for company, pattern in patterns.items() if pattern.search(content)]
        if companies:
            unsupported.append(f"{row['id']} ({row['topic']}): {', '.join(companies)}")
    assert not unsupported, "Positive grounded topics reference excluded companies:\n" + "\n".join(unsupported)
