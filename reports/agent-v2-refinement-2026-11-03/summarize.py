"""Recompute descriptive metrics from the saved Promptfoo exports; no model calls."""

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RATES = {"jev": (0.042, 0, 0), "gpt-5-mini": (0.25, 0.025, 2), "gpt-5-nano": (0.05, 0.005, 0.4)}


def cost(model, values):
    name = next(prefix for prefix in RATES if model.startswith(prefix))
    inp, cached, out = RATES[name]
    return ((values["input_tokens"] - values.get("cached_input_tokens", 0)) * inp
            + values.get("cached_input_tokens", 0) * cached + values["output_tokens"] * out) / 1e6


def summarize(path):
    data = json.loads(path.read_text())
    grouped = defaultdict(list)
    for row in data["results"]["results"]:
        grouped[row["provider"]["label"]].append(row)
    summary = {}
    for label, rows in grouped.items():
        topics = {}
        by_model = defaultdict(Counter)
        totals = Counter()
        latencies, words = [], []
        grading_cost = 0
        failures = []
        cases = []
        for row in rows:
            values = row["testCase"]["vars"]
            response = row.get("response") or {}
            metadata = response.get("metadata", {})
            telemetry = metadata.get("telemetry", {})
            topic = topics.setdefault(values["topic"], Counter())
            topic.update(cases=1, strict_passes=int(row["success"]))
            topic["status_" + metadata.get("status", "error")] += 1
            if metadata.get("answer_latency_ms") is not None:
                latencies.append(metadata["answer_latency_ms"])
            output = response.get("output", "")
            words.append(len(output.split()))
            case = {"id": values["id"], "question": values["test"], "topic": values["topic"],
                    "strict_pass": row["success"], "status": metadata.get("status"),
                    "answer": output, "words": len(output.split()),
                    "retrieval_attempts": metadata.get("retrieval_attempts"),
                    "failed_checks": []}
            for component in (row.get("gradingResult") or {}).get("componentResults", []):
                metric = component.get("assertion", {}).get("metric", "unknown")
                topic[metric + "_passes"] += int(component.get("pass", False))
                if not component.get("pass", False):
                    case["failed_checks"].append({"metric": metric, "reason": component.get("reason")})
            if not row["success"]:
                failures.append(case)
            cases.append(case)
            for model, usage in telemetry.get("by_model", {}).items():
                by_model[model].update(usage)
            if telemetry and not telemetry.get("by_model"):
                by_model["gpt-5-mini"].update({key: telemetry[key] for key in ["input_tokens", "output_tokens", "cached_input_tokens"]})
            totals["embedding_input_tokens"] += telemetry.get("embedding_input_tokens", 0)
            gu = (row.get("gradingResult") or {}).get("tokensUsed", {})
            grading_cost += cost("gpt-5-mini", {"input_tokens": gu.get("prompt", 0), "output_tokens": gu.get("completion", 0), "cached_input_tokens": gu.get("cached", 0)})
        models_cost = sum(cost(model, usage) for model, usage in by_model.items())
        summary[label] = {
            "eval_id": data["evalId"], "cases": len(rows), "strict_passes": sum(r["success"] for r in rows),
            "mean_answer_latency_ms": statistics.mean(latencies),
            "median_answer_latency_ms": statistics.median(latencies),
            "p95_answer_latency_ms": sorted(latencies)[int((len(latencies)-1)*0.95)],
            "mean_answer_words": statistics.mean(words), "median_answer_words": statistics.median(words),
            "topics": {topic: dict(counts) for topic, counts in topics.items()},
            "usage_by_model": {model: dict(usage) for model, usage in by_model.items()},
            "estimated_models_usd": models_cost,
            "estimated_embeddings_usd": totals["embedding_input_tokens"] * 0.02 / 1e6,
            "estimated_grading_usd": grading_cost,
            "estimated_total_usd": models_cost + totals["embedding_input_tokens"] * 0.02 / 1e6 + grading_cost,
            "failures": failures, "case_answers": cases,
        }
    return summary


def main():
    paths = [
        "reports/agent-v2/promptfoo.json",
        "reports/baseline-2026-11-02-v2/promptfoo.json",
        "reports/agent-v2-refinement-2026-11-03/targeted.json",
        "reports/agent-v2-refinement-2026-11-03/candidate-2-full.json",
        "reports/agent-v2-refinement-2026-11-03/candidate-3-full.json",
        "reports/agent-v2-refinement-2026-11-03/candidate-3-behavior.json",
        "reports/agent-v2-refinement-2026-11-03/full-final.json",
        "reports/agent-v2-refinement-2026-11-03/behavior-final.json",
    ]
    result = {path: summarize(ROOT / path) for path in paths}
    (OUT / "evaluation-summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    for path, groups in result.items():
        for label, values in groups.items():
            print(path, label, values["strict_passes"], '/', values["cases"],
                  'mean latency seconds', round(values["mean_answer_latency_ms"] / 1000, 2),
                  'cost USD', round(values["estimated_total_usd"], 6))


if __name__ == "__main__":
    main()
