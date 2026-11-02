"""Embedding cache contracts: bounded requests, restartability and integrity."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from etl.embeddings import DIMENSIONS, MODEL, embedding_text
from etl.gold import cached_embeddings
from etl.models import Chunk, SourceDocument


def fake_client():
    def create(*, input, model, dimensions, **kwargs):
        assert model == MODEL
        assert dimensions == DIMENSIONS == 1536
        items = [SimpleNamespace(index=index, embedding=[float(sum(text.encode()) % 100 + 1)] + [0.0] * 1535) for index, text in enumerate(input)]
        return SimpleNamespace(data=list(reversed(items)))
    return SimpleNamespace(embeddings=SimpleNamespace(create=Mock(side_effect=create)))


def test_completed_cache_avoids_api_and_preserves_order(tmp_path):
    client = fake_client()
    texts = ["first", "second", "third", "fourth", "fifth"]
    vectors = cached_embeddings(client, texts, tmp_path, batch_size=2)
    assert len(vectors) == len(texts)
    assert [vector[0] for vector in vectors] == [float(sum(text.encode()) % 100 + 1) for text in texts]
    assert client.embeddings.create.call_count == 3
    assert all(len(call.kwargs["input"]) <= 2 for call in client.embeddings.create.call_args_list)
    second_client = fake_client()
    assert cached_embeddings(second_client, texts, tmp_path, batch_size=2) == vectors
    second_client.embeddings.create.assert_not_called()


def test_empty_input_requires_no_api(tmp_path):
    client = fake_client()
    assert cached_embeddings(client, [], tmp_path) == []
    client.embeddings.create.assert_not_called()


def test_failed_later_batch_resumes_completed_batches(tmp_path):
    client = fake_client()
    success = client.embeddings.create.side_effect
    call_count = 0

    def fail_second(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("temporary embedding outage")
        return success(**kwargs)

    client.embeddings.create.side_effect = fail_second
    texts = ["first", "second", "third"]
    with pytest.raises(RuntimeError, match="temporary embedding outage"):
        cached_embeddings(client, texts, tmp_path, batch_size=2)
    resumed_client = fake_client()
    result = cached_embeddings(resumed_client, texts, tmp_path, batch_size=2)
    assert len(result) == 3
    assert resumed_client.embeddings.create.call_count == 1
    assert resumed_client.embeddings.create.call_args.kwargs["input"] == ["third"]


def test_only_changed_batch_needs_new_embedding(tmp_path):
    client = fake_client()
    cached_embeddings(client, ["a", "b", "c", "d"], tmp_path, batch_size=2)
    client.embeddings.create.reset_mock()
    cached_embeddings(client, ["a", "b", "changed", "d"], tmp_path, batch_size=2)
    assert client.embeddings.create.call_count == 1
    assert client.embeddings.create.call_args.kwargs["input"] == ["changed", "d"]


def test_cache_key_distinguishes_text_order_and_batch_boundaries(tmp_path):
    client = fake_client()
    original = cached_embeddings(client, ["ab", "c"], tmp_path, batch_size=2)
    client.embeddings.create.reset_mock()
    changed = cached_embeddings(client, ["a", "bc"], tmp_path, batch_size=2)
    assert client.embeddings.create.call_count == 1
    assert changed != original
    client.embeddings.create.reset_mock()
    reverse = cached_embeddings(client, ["bc", "a"], tmp_path, batch_size=2)
    assert client.embeddings.create.call_count == 1
    assert reverse == list(reversed(changed))


def find_vector(value):
    if isinstance(value, list):
        if len(value) == DIMENSIONS and all(isinstance(item, (int, float)) for item in value):
            return value
        for item in value:
            found = find_vector(item)
            if found is not None:
                return found
    elif isinstance(value, dict):
        for item in value.values():
            found = find_vector(item)
            if found is not None:
                return found
    return None


@pytest.mark.parametrize("damage", ["truncated-json", "wrong-dimension", "zero-vector", "valid-vector-tampering"])
def test_corrupt_cache_is_rebuilt(tmp_path, damage):
    client = fake_client()
    original = cached_embeddings(client, ["financial report"], tmp_path)
    cache_files = list(tmp_path.rglob("*.json"))
    assert cache_files, "A completed embedding batch must be persisted"
    target = next(path for path in cache_files if find_vector(json.loads(path.read_text())) is not None)
    payload = json.loads(target.read_text())
    vector = find_vector(payload)
    if damage == "truncated-json":
        target.write_text('{"truncated":')
    else:
        if damage == "wrong-dimension":
            vector.pop()
        elif damage == "zero-vector":
            vector[:] = [0.0] * DIMENSIONS
        else:
            vector[0] += 1.0
        target.write_text(json.dumps(payload))
    client.embeddings.create.reset_mock()
    assert cached_embeddings(client, ["financial report"], tmp_path) == original
    assert client.embeddings.create.call_count == 1


@pytest.mark.parametrize("field,value", [("company", "Renamed Company"), ("fiscal_year", 2026), ("quarter", "3"), ("report_type", "earnings_release"), ("title", "Corrected report title")])
def test_changed_source_context_changes_embedding_and_cache(tmp_path, field, value):
    source = SourceDocument(document_id="doc", path="report.pdf", sha256="a" * 64, company="Example", fiscal_year=2025, quarter="4", report_type="annual_report", title="Annual report", url="https://example.com/report", pages=5)
    chunk = Chunk(chunk_id="chunk", document_id="doc", ordinal=0, text="Revenue rose 10%.", headings=("Results",), pages=(3,), source_refs=("#/texts/0",), kind="text")
    before = embedding_text(source, chunk)
    after = embedding_text(replace(source, **{field: value}), chunk)
    assert before != after
    client = fake_client()
    cached_embeddings(client, [before], tmp_path)
    cached_embeddings(client, [after], tmp_path)
    assert client.embeddings.create.call_count == 2


@pytest.mark.parametrize("batch_size", [0, -1, 65])
def test_invalid_batch_size_fails_before_api(tmp_path, batch_size):
    client = fake_client()
    with pytest.raises(ValueError):
        cached_embeddings(client, ["text"], tmp_path, batch_size=batch_size)
    client.embeddings.create.assert_not_called()
