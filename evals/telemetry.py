"""Compatibility exports for existing evaluation telemetry consumers."""

from agents.telemetry import RunMetrics, record_embedding_response

__all__ = ["RunMetrics", "record_embedding_response"]
