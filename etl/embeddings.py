"""Validated, bounded OpenAI embedding batches; retries belong to the SDK."""
import math

from etl.models import Chunk, SourceDocument

MODEL = "text-embedding-3-small"
DIMENSIONS = 1536


def embedding_text(source: SourceDocument, chunk: Chunk) -> str:
    period = f"FY{source.fiscal_year}" + (f" Q{source.quarter}" if source.quarter else "")
    return "\n".join([f"{source.company} | {period} | {source.report_type}", source.title,
                      " > ".join(chunk.headings), chunk.text])


def validate_vector(vector, dimensions):
    if len(vector) != dimensions or not all(math.isfinite(value) for value in vector) or not any(vector):
        raise ValueError("Invalid embedding vector: dimensions, finite values, or zero norm")


def embed_texts(client, texts: list[str], model: str = MODEL, dimensions: int = DIMENSIONS, batch_size: int = 64) -> list[list[float]]:
    """Validate and embed bounded batches, splitting requests that exceed the aggregate guard."""

    if dimensions <= 0 or not 1 <= batch_size <= 64:
        raise ValueError("Require positive dimensions and batch_size in 1..64")
    if not texts:
        return []
    if any(not isinstance(text, str) or not text.strip() for text in texts):
        raise ValueError("Embedding input must be nonempty text")
    # UTF-8 bytes conservatively bound tokens without downloading a tokenizer.
    if any(len(text.encode("utf-8")) > 8191 for text in texts):
        raise ValueError("Embedding input exceeds conservative 8191-byte token guard")
    vectors = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        # Bound aggregate input to well below the API's 300k-token request limit.
        if sum(len(text.encode("utf-8")) for text in batch) > 250_000:
            vectors.extend(embed_texts(client, batch, model, dimensions, max(1, batch_size // 2)))
            continue
        result = client.embeddings.create(input=batch, model=model, dimensions=dimensions, encoding_format="float")
        ordered = sorted(result.data, key=lambda item: item.index)
        if [item.index for item in ordered] != list(range(len(batch))):
            raise ValueError("Embedding response indices do not match the request")
        for item in ordered:
            validate_vector(item.embedding, dimensions)
            vectors.append(list(item.embedding))
    return vectors
