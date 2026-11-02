"""Small offline fixtures for picture-enrichment contracts."""

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from docling_core.types.doc import BoundingBox, DoclingDocument, ImageRef, Size
from docling_core.types.doc.document import ProvenanceItem
from PIL import Image


@pytest.fixture
def picture_png() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (24, 16), "blue").save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def picture_client():
    response = SimpleNamespace(
        status="completed", output_text="Revenue increased from $10m to $12m.",
        usage=SimpleNamespace(input_tokens=1000, output_tokens=200, total_tokens=1200),
    )
    return SimpleNamespace(responses=SimpleNamespace(create=Mock(return_value=response)))


@pytest.fixture
def picture_document():
    document = DoclingDocument(name="financial-report")
    document.add_page(page_no=1, size=Size(width=612, height=792))
    document.add_title("Annual report")
    document.add_heading("Revenue", level=1)
    document.add_picture(
        image=ImageRef.from_pil(Image.new("RGB", (24, 16), "blue"), dpi=96),
        prov=ProvenanceItem(page_no=1, bbox=BoundingBox(l=0, t=0, r=24, b=16), charspan=(0, 0)),
    )
    return document
