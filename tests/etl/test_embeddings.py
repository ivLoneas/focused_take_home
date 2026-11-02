"""Embedding requests are isolated from credentials and network calls."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from etl.embeddings import embed_texts


def response(*vectors):
    return SimpleNamespace(data=[SimpleNamespace(index=index, embedding=vector) for index, vector in enumerate(vectors)])


def test_batches_and_preserves_order_when_api_returns_reordered_items():
    first = response([1.0, 2.0], [3.0, 4.0])
    first.data.reverse()
    client = SimpleNamespace(embeddings=SimpleNamespace(create=Mock(side_effect=[first, response([5.0, 6.0])])))
    vectors = embed_texts(client, ["first", "second", "third"], model="test-model", dimensions=2, batch_size=2)
    assert vectors == [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]
    calls = client.embeddings.create.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["input"] == ["first", "second"]
    assert calls[1].kwargs["input"] == ["third"]
    assert calls[0].kwargs["model"] == "test-model"
    assert calls[0].kwargs["dimensions"] == 2


def test_empty_input_makes_no_request():
    client = SimpleNamespace(embeddings=SimpleNamespace(create=Mock()))
    assert embed_texts(client, []) == []
    client.embeddings.create.assert_not_called()


@pytest.mark.parametrize("vector", [[1.0], [1.0, 2.0, 3.0], [0.0, 0.0], [float("nan"), 1.0], [float("inf"), 1.0], [float("-inf"), 1.0]])
def test_rejects_malformed_embedding_vectors(vector):
    client = SimpleNamespace(embeddings=SimpleNamespace(create=Mock(return_value=response(vector))))
    with pytest.raises(ValueError):
        embed_texts(client, ["text"], dimensions=2)


@pytest.mark.parametrize("indices", [[0], [0, 0], [0, 2], [-1, 0], [0, 1, 2]])
def test_rejects_missing_duplicate_or_out_of_range_response_indices(indices):
    result = SimpleNamespace(data=[SimpleNamespace(index=index, embedding=[1.0, 2.0]) for index in indices])
    client = SimpleNamespace(embeddings=SimpleNamespace(create=Mock(return_value=result)))
    with pytest.raises(ValueError):
        embed_texts(client, ["one", "two"], dimensions=2)


@pytest.mark.parametrize("kwargs", [{"batch_size": 0}, {"batch_size": -1}, {"dimensions": 0}, {"dimensions": -1}])
def test_invalid_request_parameters_fail_before_network(kwargs):
    client = SimpleNamespace(embeddings=SimpleNamespace(create=Mock()))
    with pytest.raises(ValueError):
        embed_texts(client, ["text"], **kwargs)
    client.embeddings.create.assert_not_called()


def test_api_errors_propagate_instead_of_silently_losing_chunks():
    client = SimpleNamespace(embeddings=SimpleNamespace(create=Mock(side_effect=RuntimeError("provider unavailable"))))
    with pytest.raises(RuntimeError, match="provider unavailable"):
        embed_texts(client, ["text"])
