"""Browser rendering boundary and evidence-only citation link behavior."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
LABEL = "10-K | apple | FY2025 Q4 | p. 32"
URL = "https://reports.example/apple.pdf?download=1#old"

HARNESS = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const options = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = new Map();
let replacement;
let parsed;
let sanitized;
let created = 0;
function element(id) {
  if (!nodes.has(id)) nodes.set(id, {
    value: '', maxLength: 2000, textContent: '', dataset: {}, childNodes: [], children: [],
    querySelector: element, querySelectorAll: () => [],
    addEventListener() {}, append(...items) { this.children.push(...items); },
    replaceChildren(...items) { this.children = items; if (id === '#answer') replacement = items[0]; },
    setAttribute(key, value) { this[key] = value; },
  });
  return nodes.get(id);
}
const fragment = {nodeType: 11, childNodes: [], querySelectorAll: () => []};
const context = {
  fetch:async()=>({ok:true,status:200,json:async()=>({active_thread_id:null,threads:[]})}),
  window: {}, URL, TextDecoder, AbortSignal, NodeFilter: {SHOW_TEXT: 4}, Node: {TEXT_NODE: 3},
  document: {
    querySelector: element, querySelectorAll: () => [], createElement: () => element(`new-${created++}`),
    createTreeWalker: () => ({nextNode: () => null}),
  },
  localStorage: {getItem: () => null, removeItem() {}, setItem() {}},
  marked: {parse(markdown) { parsed = markdown; return '<p>parsed safe markdown</p>'; }},
  DOMPurify: {sanitize(html, config) { sanitized = {html, config}; return fragment; }},
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
(async()=>{
await vm.runInContext('bootstrapPromise',context);
try {
  context.options = options;
  if (options.action === 'citation') {
    const result = vm.runInContext('citationUrl(options.label, options.urls)', context);
    console.log(JSON.stringify({result}));
  } else if (options.action === 'details') {
    vm.runInContext('renderResult(options.result)', context);
    const rendered = {
      summary: element('#sources-summary').textContent,
      sourceCount: element('#citations').children.length,
      responseTime: element('#response-time').textContent,
      firstTokenTime: element('#first-token-time').textContent,
      totalTokens: element('#total-tokens').textContent,
      estimatedCost: element('#estimated-cost').textContent,
    };
    element('#sources-details').open = true;
    vm.runInContext('setLoading(true)', context);
    const reset = {
      summary: element('#sources-summary').textContent,
      open: element('#sources-details').open,
      responseTime: element('#response-time').textContent,
    };
    const usageReset = {
      totalTokens: element('#total-tokens').textContent,
      estimatedCost: element('#estimated-cost').textContent,
    };
    vm.runInContext('renderResult(options.result); renderError("Failed")', context);
    const usageError = {
      totalTokens: element('#total-tokens').textContent,
      estimatedCost: element('#estimated-cost').textContent,
    };
    console.log(JSON.stringify({rendered, reset, usageReset, usageError}));
  } else {
    vm.runInContext('renderAnswer(options.result)', context);
    console.log(JSON.stringify({parsed, sanitized, fragmentInserted: replacement === fragment}));
  }
} catch(error) { console.log(JSON.stringify({error: error.message})); }
})();
"""


def evaluate(**options):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the browser rendering contract")
    run = subprocess.run([node, "-e", HARNESS, str(FRONTEND / "app.js")], input=json.dumps(options),
                         capture_output=True, text=True, check=True, timeout=15)
    return json.loads(run.stdout)


@pytest.mark.parametrize("key", [LABEL, "10-K | apple | FY2025 Q4 | pp. 30-35", " 10-k | APPLE | fy2025 q4 | p. 32 "])
def test_inline_citation_uses_retrieved_report_and_requested_page(key):
    output = evaluate(action="citation", label=LABEL, urls={key: URL})
    assert output == {"result": "https://reports.example/apple.pdf?download=1#page=32"}


def test_shorthand_citation_matches_known_document_tokens_in_different_order():
    output = evaluate(
        action="citation", label="Amazon 10-K FY2025 Q4 p. 37",
        urls={"10-K | amazon | FY2025 Q4 | p. 27": "https://reports.example/amazon.pdf?download=1#old"},
    )
    assert output == {"result": "https://reports.example/amazon.pdf?download=1#page=37"}


@pytest.mark.parametrize("label", ["Amazon 10-K FY2024 Q4 p. 37", "Apple 10-K FY2025 Q4 p. 37"])
def test_shorthand_with_different_document_tokens_remains_unlinked(label):
    assert evaluate(action="citation", label=label, urls={
        "10-K | amazon | FY2025 Q4 | p. 27": "https://reports.example/amazon.pdf",
    }) == {"result": None}


def test_document_with_conflicting_retrieved_report_urls_is_ambiguous():
    assert evaluate(action="citation", label="Amazon 10-K FY2025 Q4 p. 37", urls={
        "10-K | amazon | FY2025 Q4 | p. 27": "https://reports.example/amazon-a.pdf",
        "10-K | amazon | FY2025 Q4 | p. 37": "https://reports.example/amazon-b.pdf",
    }) == {"result": None}


def test_periodless_citation_links_only_when_retrieved_document_is_unique():
    assert evaluate(action="citation", label="Apple 10-K, p. 32", urls={
        "10-K | apple | FY2025 Q4 | p. 26": URL,
    }) == {"result": "https://reports.example/apple.pdf?download=1#page=32"}


def test_periodless_citation_does_not_guess_between_retrieved_fiscal_years():
    assert evaluate(action="citation", label="Apple 10-K, p. 32", urls={
        "10-K | apple | FY2025 Q4 | p. 26": "https://reports.example/apple-2025.pdf",
        "10-K | apple | FY2024 Q4 | p. 26": "https://reports.example/apple-2024.pdf",
    }) == {"result": None}


@pytest.mark.parametrize("urls", [
    {}, {"10-K | amazon | FY2025 Q4 | p. 32": URL},
    {"10-K | apple | FY2024 Q4 | p. 32": URL},
    {LABEL: "javascript:alert(1)"}, {LABEL: "data:text/html,x"},
    {LABEL: "https://user:secret@reports.example/report.pdf"}, {LABEL: "/local/report.pdf"},
])
def test_missing_or_unsafe_citation_url_stays_unlinked(urls):
    assert evaluate(action="citation", label=LABEL, urls=urls) == {"result": None}


def test_markdown_is_parsed_and_sanitized_as_fragment_before_dom_insertion():
    markdown = "Revenue **grew** with *growth*.\n\n- One\n- Two\n\n|Year|Sales|\n|---|---|\n|2025|10|\n\n`code`\n<script>alert(1)</script>"
    output = evaluate(action="render", result={"answer": markdown, "citations": [], "source_urls": {}})
    assert output.get("parsed") == markdown
    assert output["sanitized"]["html"] == "<p>parsed safe markdown</p>"
    assert output["sanitized"]["config"]["RETURN_DOM_FRAGMENT"] is True
    assert output["fragmentInserted"] is True


def test_source_sidebar_counts_reports_once_and_resets_for_new_request():
    first = "10-K | apple | FY2025 Q4 | p. 32"
    second = "10-K | apple | FY2025 Q4 | p. 33"
    third = "10-Q | amazon | FY2025 Q3 | p. 4"
    output = evaluate(action="details", result={
        "answer": "10", "status": "answered", "citations": [first, second, third], "retrieval_attempts": 1,
        "source_urls": {first: URL, second: URL, third: "https://reports.example/amazon.pdf"},
        "metrics": {"response_ms": 2500, "first_token_ms": 500},
    })
    assert output["rendered"]["summary"] == "2 sources"
    assert output["rendered"]["sourceCount"] == 2
    assert "2.5" in output["rendered"]["responseTime"] and "s" in output["rendered"]["responseTime"]
    assert "0.5" in output["rendered"]["firstTokenTime"] and "s" in output["rendered"]["firstTokenTime"]
    assert output["reset"] == {"summary": "0 sources", "open": False, "responseTime": "—"}


def test_historical_result_without_metrics_shows_missing_time_as_dash():
    output = evaluate(action="details", result={
        "answer": "Which company?", "status": "needs_clarification", "citations": [], "retrieval_attempts": 0,
    })
    assert output["rendered"]["summary"] == "0 sources"
    assert output["rendered"]["responseTime"] == output["rendered"]["firstTokenTime"] == "—"


@pytest.mark.parametrize("metrics,tokens,cost", [
    ({"total_tokens": 1234, "cost_usd": .001234567}, "1,234", "$0.001235"),
    ({"total_tokens": 0, "cost_usd": 0}, "0", "$0.000000"),
    ({"total_tokens": None, "cost_usd": None}, "—", "—"),
    ({"total_tokens": "1234", "cost_usd": "0.2"}, "—", "—"),
    ({"total_tokens": -1, "cost_usd": -1}, "—", "—"),
    ({"total_tokens": True, "cost_usd": False}, "—", "—"),
    ({}, "—", "—"),
])
def test_sidebar_formats_usage_and_clears_it_on_loading_or_error(metrics, tokens, cost):
    output = evaluate(action="details", result={
        "answer": "10", "status": "answered", "citations": [], "retrieval_attempts": 0, "metrics": metrics,
    })
    assert output["rendered"]["totalTokens"] == tokens
    assert output["rendered"]["estimatedCost"] == cost
    assert output["usageReset"] == output["usageError"] == {"totalTokens": "—", "estimatedCost": "—"}


def test_page_bundles_markdown_and_sanitizer_before_app_without_remote_scripts():
    from html.parser import HTMLParser

    class Scripts(HTMLParser):
        def __init__(self):
            super().__init__()
            self.sources = []

        def handle_starttag(self, tag, attrs):
            if tag == "script":
                self.sources.append(dict(attrs).get("src", ""))

    parser = Scripts()
    parser.feed((FRONTEND / "index.html").read_text())
    source_paths = [path.split("?", 1)[0] for path in parser.sources]
    assert len(source_paths) >= 3 and source_paths[-1] == "app.js"
    assert any("marked" in path for path in parser.sources[:-1])
    assert any("purify" in path.lower() for path in parser.sources[:-1])
    assert all(path and not path.startswith(("http:", "https:", "//")) for path in parser.sources)
    assert all((FRONTEND / path).is_file() for path in source_paths)
