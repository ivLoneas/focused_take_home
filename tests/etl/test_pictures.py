"""OpenAI figure descriptions must be reproducible, attributed, and cached."""

import base64
import importlib
from io import BytesIO

import pytest
from docling_core.types.doc import DoclingDocument
from docling_core.types.doc.document import DocItemLabel
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from etl.chunking import chunk_blocks
from etl.parsing import IMAGE_PROMPT, document_blocks


def picture_api():
    return importlib.import_module("etl.pictures")


def test_request_uses_luna_responses_png_and_measured_usage(picture_client, picture_png, tmp_path):
    description, usage = picture_api().cached_description(picture_client, picture_png, tmp_path)
    assert description == "Revenue increased from $10m to $12m."
    request = picture_client.responses.create.call_args.kwargs
    assert request["model"] == "gpt-6-luna"
    assert request["reasoning"] == {"effort": "none"}
    assert 0 < request["max_output_tokens"] <= 2048
    content = [part for message in request["input"] for part in message["content"]]
    assert any(part["type"] == "input_text" and part["text"] == IMAGE_PROMPT for part in content)
    image = next(part for part in content if part["type"] == "input_image")
    assert image["detail"] == "high"
    assert image["image_url"].startswith("data:image/png;base64,")
    assert base64.b64decode(image["image_url"].split(",", 1)[1]) == picture_png
    assert usage == {"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200,
                     "api_calls": 1, "cost_usd": pytest.approx(0.0002)}


def test_valid_cache_avoids_api_and_preserves_original_usage(picture_client, picture_png, tmp_path):
    first = picture_api().cached_description(picture_client, picture_png, tmp_path)
    picture_client.responses.create.reset_mock()
    second = picture_api().cached_description(picture_client, picture_png, tmp_path)
    assert second == first
    assert second[1]["api_calls"] == 1
    picture_client.responses.create.assert_not_called()


@pytest.mark.parametrize("changed", ["bytes", "model", "prompt", "detail"])
def test_each_cache_key_component_invalidates_reuse(picture_client, picture_png, tmp_path, changed):
    picture_api().cached_description(picture_client, picture_png, tmp_path)
    options = {}
    if changed == "bytes":
        stream = BytesIO()
        metadata = PngInfo()
        metadata.add_text("render-revision", "different PNG bytes, identical pixels")
        Image.new("RGB", (24, 16), "blue").save(stream, format="PNG", pnginfo=metadata)
        picture_png = stream.getvalue()
    else:
        options[changed] = {"model": "test-model", "prompt": IMAGE_PROMPT + " Include legend.", "detail": "low"}[changed]
    picture_api().cached_description(picture_client, picture_png, tmp_path, **options)
    assert picture_client.responses.create.call_count == 2


@pytest.mark.parametrize("damage", ["truncated", "tampered-description", "wrong-image-payload"])
def test_corrupt_or_mismatched_cache_retries_api(picture_client, picture_png, tmp_path, damage):
    expected = picture_api().cached_description(picture_client, picture_png, tmp_path)
    path = next(tmp_path.rglob("*.json"))
    if damage == "truncated":
        path.write_text('{"truncated":')
    elif damage == "tampered-description":
        payload = path.read_text()
        assert expected[0] in payload
        path.write_text(payload.replace(expected[0], "Invented financial claim."))
    else:
        other = tmp_path / "different"
        picture_api().cached_description(picture_client, picture_png, other, prompt="Different prompt")
        path.write_bytes(next(other.rglob("*.json")).read_bytes())
    picture_client.responses.create.reset_mock()
    assert picture_api().cached_description(picture_client, picture_png, tmp_path) == expected
    picture_client.responses.create.assert_called_once()


@pytest.mark.parametrize("output", ["", " \n\t", None])
def test_empty_response_raises_without_publishing_valid_cache(picture_client, picture_png, tmp_path, output):
    picture_client.responses.create.return_value.output_text = output
    with pytest.raises((ValueError, RuntimeError)):
        picture_api().cached_description(picture_client, picture_png, tmp_path)
    picture_client.responses.create.return_value.output_text = "A visible bar chart."
    assert picture_api().cached_description(picture_client, picture_png, tmp_path)[0] == "A visible bar chart."
    assert picture_client.responses.create.call_count == 2


@pytest.mark.parametrize("image", [None, b""])
def test_missing_png_rejected_without_api(picture_client, tmp_path, image):
    with pytest.raises(ValueError):
        picture_api().cached_description(picture_client, image, tmp_path)
    picture_client.responses.create.assert_not_called()


def test_provider_error_propagates_without_poisoning_cache(picture_client, picture_png, tmp_path):
    picture_client.responses.create.side_effect = RuntimeError("provider unavailable")
    with pytest.raises(RuntimeError, match="provider unavailable"):
        picture_api().cached_description(picture_client, picture_png, tmp_path)
    picture_client.responses.create.side_effect = None
    assert picture_api().cached_description(picture_client, picture_png, tmp_path)[0]
    assert picture_client.responses.create.call_count == 2


@pytest.mark.parametrize("status", ["failed", "incomplete"])
def test_noncompleted_response_is_not_cached_as_valid(picture_client, picture_png, tmp_path, status):
    picture_client.responses.create.return_value.status = status
    with pytest.raises((ValueError, RuntimeError)):
        picture_api().cached_description(picture_client, picture_png, tmp_path)
    picture_client.responses.create.return_value.status = "completed"
    assert picture_api().cached_description(picture_client, picture_png, tmp_path)[0]
    assert picture_client.responses.create.call_count == 2


def test_enrichment_survives_docling_serialization_and_chunk_provenance(picture_client, picture_document, tmp_path):
    usage = picture_api().enrich_pictures(picture_document, picture_client, tmp_path)
    picture = picture_document.pictures[0]
    assert picture.meta.description.text == "Revenue increased from $10m to $12m."
    restored = DoclingDocument.model_validate(picture_document.export_to_dict())
    blocks = document_blocks(restored)
    block = next(block for block in blocks if block.kind == "picture")
    assert block.ref == picture.self_ref
    assert block.pages == (1,)
    assert block.headings == ("Annual report", "Revenue")
    assert "[Generated image description; verify against source]" in block.text
    chunks = chunk_blocks("doc", blocks)
    assert chunks[0].source_refs == (picture.self_ref,)
    assert chunks[0].pages == (1,)
    assert picture.meta.description.text in chunks[0].text
    assert usage["cost_usd"] == pytest.approx(0.0002)


def test_picture_without_image_retains_caption_without_fabrication(picture_client, tmp_path):
    doc = DoclingDocument(name="report")
    caption = doc.add_text(DocItemLabel.CAPTION, "Figure: operating margin")
    picture = doc.add_picture(caption=caption)
    usage = picture_api().enrich_pictures(doc, picture_client, tmp_path)
    picture_client.responses.create.assert_not_called()
    assert picture.meta is None or picture.meta.description is None
    assert "Figure: operating margin" in "\n".join(block.text for block in document_blocks(doc))
    assert usage["api_calls"] == 0 and usage["cost_usd"] == 0
