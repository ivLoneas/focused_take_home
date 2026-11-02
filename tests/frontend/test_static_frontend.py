"""Static contracts for the buildless, browser-only interface."""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = PROJECT_ROOT / "frontend"


class Markup(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.text.append(value)

    def elements(self, tag: str) -> list[dict[str, str | None]]:
        return [attrs for element_tag, attrs in self.tags if element_tag == tag]

    def by_id(self, element_id: str) -> tuple[str, dict[str, str | None]] | None:
        return next(((tag, attrs) for tag, attrs in self.tags if attrs.get("id") == element_id), None)


@pytest.fixture
def html() -> str:
    return (FRONTEND / "index.html").read_text(encoding="utf-8")


@pytest.fixture
def markup(html: str) -> Markup:
    parsed = Markup()
    parsed.feed(html)
    return parsed


@pytest.fixture
def javascript() -> str:
    return (FRONTEND / "app.js").read_text(encoding="utf-8")


@pytest.fixture
def css() -> str:
    return (FRONTEND / "styles.css").read_text(encoding="utf-8")


def test_frontend_is_buildless_and_references_local_css_and_javascript(markup: Markup):
    stylesheets = [
        attrs.get("href")
        for attrs in markup.elements("link")
        if attrs.get("rel") == "stylesheet"
    ]
    scripts = [attrs.get("src") for attrs in markup.elements("script") if attrs.get("src")]

    assert "styles.css" in stylesheets or "./styles.css" in stylesheets
    assert "app.js" in scripts or "./app.js" in scripts
    assert not any(value.startswith(("http://", "https://")) for value in [*stylesheets, *scripts] if value)
    assert not (FRONTEND / "package.json").exists()


def test_page_presents_a_focused_question_form_and_baseline_only_selector(markup: Markup):
    form = markup.by_id("question-form")
    select = markup.by_id("agent-select")
    question = markup.by_id("question")
    options = markup.elements("option")

    assert form is not None and form[0] == "form"
    assert select is not None and select[0] == "select"
    assert select[1].get("name") == "agent_id"
    assert len(options) == 1
    assert options[0].get("value") == "baseline"
    assert question is not None and question[0] in {"textarea", "input"}
    assert question[1].get("name") == "question"
    assert "required" in question[1]
    assert int(question[1]["maxlength"]) > 0
    assert any(attrs.get("type") == "submit" for attrs in markup.elements("button"))


def test_controls_have_programmatic_labels_and_results_are_announced(markup: Markup):
    label_targets = {attrs.get("for") for attrs in markup.elements("label")}
    status = markup.by_id("response-status")

    assert {"agent-select", "question"} <= label_targets
    assert status is not None
    assert status[1].get("aria-live") in {"polite", "assertive"}
    assert status[1].get("role") in {"status", "alert"}


def test_page_explains_the_baseline_decision_and_retrieval_flow(markup: Markup):
    copy = " ".join(markup.text).lower()

    assert "financial report" in copy
    assert "out of domain" in copy or "out-of-domain" in copy
    assert "clarif" in copy
    assert "retriev" in copy
    assert "3" in copy
    assert "chat" not in copy or "not a chat" in copy or "not a general chat" in copy


def test_page_has_dedicated_answer_citation_attempt_and_history_regions(markup: Markup):
    required_ids = {
        "answer",
        "citations",
        "retrieval-attempts",
        "history-list",
        "clear-history",
    }

    assert all(markup.by_id(element_id) is not None for element_id in required_ids)


@pytest.mark.parametrize("status", ["answered", "needs_clarification", "out_of_domain"])
def test_javascript_handles_all_agent_statuses(javascript: str, status: str):
    assert status in javascript


def test_run_request_sends_only_agent_id_and_current_question(javascript: str):
    compact = re.sub(r"\s+", " ", javascript)
    payload = re.search(
        r"body\s*:\s*JSON\.stringify\(\s*\{(?P<body>[^{}]*)\}\s*\)",
        compact,
    )

    assert "fetch(" in javascript
    assert "/api/run" in javascript
    assert payload is not None
    fields = set(re.findall(r"\b(agent_id|question|history|messages|conversation|session_id)\b", payload["body"]))
    assert fields == {"agent_id", "question"}


def test_javascript_exposes_loading_success_and_error_states(javascript: str):
    lower = javascript.lower()

    assert "loading" in lower
    assert "error" in lower or "unable" in lower
    assert ".disabled" in javascript
    assert "response.ok" in javascript or re.search(r"response\.status\s*[!<>=]", javascript)
    assert "finally" in javascript


def test_history_is_browser_only_and_corrupt_storage_is_recovered_safely(javascript: str):
    assert "localStorage.getItem" in javascript
    assert "localStorage.setItem" in javascript
    assert re.search(r"try\s*\{[\s\S]*?JSON\.parse[\s\S]*?\}\s*catch", javascript)
    assert "document.cookie" not in javascript
    assert "/history" not in javascript
    assert "/session" not in javascript


def test_saved_runs_can_be_reused_removed_and_cleared(javascript: str):
    lower = javascript.lower()

    assert "reuse" in lower
    assert "remove" in lower or "delete" in lower
    assert "clear-history" in javascript
    assert "localStorage.removeItem" in javascript or "localStorage.setItem" in javascript


def test_rendered_history_uses_safe_text_insertion(javascript: str):
    """Saved/model text must not be injected as executable markup."""

    assert ".innerHTML" not in javascript
    assert ".textContent" in javascript


def test_styles_are_responsive_and_keyboard_focus_is_visible(css: str, markup: Markup):
    viewport = next((attrs for attrs in markup.elements("meta") if attrs.get("name") == "viewport"), None)

    assert viewport is not None and "width=device-width" in (viewport.get("content") or "")
    assert "@media" in css and "max-width" in css
    assert ":focus-visible" in css
    assert re.search(r"(?:textarea|input|select)[^{]*\{[^}]*font-size\s*:", css, re.DOTALL)
