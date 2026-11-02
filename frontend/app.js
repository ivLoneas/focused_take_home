"use strict";

const API_BASE_URL = window.AGENT_API_BASE_URL || "http://localhost:8000";
const HISTORY_KEY = "financial-report-agent:runs:v1";
const MAX_HISTORY_ITEMS = 20;

const form = document.querySelector("#question-form");
const agentSelect = document.querySelector("#agent-select");
const questionInput = document.querySelector("#question");
const characterCount = document.querySelector("#character-count");
const runButton = document.querySelector("#run-button");
const buttonLabel = runButton.querySelector(".button-label");
const resultPanel = document.querySelector("#result-panel");
const responseStatus = document.querySelector("#response-status");
const answer = document.querySelector("#answer");
const citations = document.querySelector("#citations");
const retrievalAttempts = document.querySelector("#retrieval-attempts");
const historyList = document.querySelector("#history-list");
const emptyHistory = document.querySelector("#empty-history");
const clearHistoryButton = document.querySelector("#clear-history");

let history = loadHistory();

function loadHistory() {
  try {
    const saved = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    if (!Array.isArray(saved)) {
      throw new TypeError("Stored history is not an array");
    }
    return saved.filter(isSavedRun).slice(0, MAX_HISTORY_ITEMS);
  } catch {
    localStorage.removeItem(HISTORY_KEY);
    return [];
  }
}

function isSavedRun(value) {
  return value && typeof value === "object"
    && typeof value.question === "string"
    && typeof value.answer === "string"
    && typeof value.status === "string"
    && Array.isArray(value.citations);
}

function saveHistory() {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
}

function setLoading(loading) {
  runButton.disabled = loading;
  agentSelect.disabled = loading;
  questionInput.disabled = loading;
  buttonLabel.textContent = loading ? "Running analysis…" : "Run analysis";
  if (loading) {
    resultPanel.hidden = false;
    setStatus("loading", "Retrieving evidence…");
    answer.textContent = "The baseline agent is analyzing the question and checking report context.";
    citations.replaceChildren();
    retrievalAttempts.textContent = "—";
  }
}

function setStatus(status, label) {
  responseStatus.dataset.status = status;
  responseStatus.textContent = label;
}

function statusLabel(status) {
  const labels = {
    answered: "Answered",
    needs_clarification: "Needs clarification",
    out_of_domain: "Out of domain",
  };
  return labels[status] || "Complete";
}

function renderResult(result) {
  resultPanel.hidden = false;
  setStatus(result.status, statusLabel(result.status));
  answer.textContent = result.answer;
  retrievalAttempts.textContent = String(result.retrieval_attempts);
  citations.replaceChildren();

  if (result.citations.length === 0) {
    const item = document.createElement("li");
    item.className = "muted-citation";
    item.textContent = "No sources returned for this outcome.";
    citations.append(item);
  } else {
    result.citations.forEach((source) => {
      const item = document.createElement("li");
      item.textContent = source;
      citations.append(item);
    });
  }
}

function renderError(message) {
  resultPanel.hidden = false;
  setStatus("error", "Unable to run");
  answer.textContent = message;
  citations.replaceChildren();
  retrievalAttempts.textContent = "—";
}

function addToHistory(question, result) {
  history.unshift({
    id: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`,
    created_at: new Date().toISOString(),
    agent_id: agentSelect.value,
    question,
    ...result,
  });
  history = history.slice(0, MAX_HISTORY_ITEMS);
  saveHistory();
  renderHistory();
}

function createHistoryButton(label, className, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

function renderHistory() {
  historyList.replaceChildren();
  emptyHistory.hidden = history.length > 0;
  clearHistoryButton.disabled = history.length === 0;

  history.forEach((run) => {
    const item = document.createElement("li");
    item.className = "history-item";

    const copy = document.createElement("div");
    copy.className = "history-copy";
    const title = document.createElement("strong");
    title.textContent = run.question;
    const summary = document.createElement("p");
    summary.textContent = run.answer;
    const meta = document.createElement("span");
    const date = new Date(run.created_at);
    meta.textContent = `${statusLabel(run.status)} · ${Number.isNaN(date.valueOf()) ? "Saved run" : date.toLocaleString()}`;
    copy.append(title, summary, meta);

    const actions = document.createElement("div");
    actions.className = "history-actions";
    actions.append(
      createHistoryButton("Reuse", "text-button", () => {
        questionInput.value = run.question;
        updateCharacterCount();
        questionInput.focus();
        window.scrollTo({ top: 0, behavior: "smooth" });
      }),
      createHistoryButton("Remove", "text-button danger", () => {
        history = history.filter((candidate) => candidate.id !== run.id);
        saveHistory();
        renderHistory();
      }),
    );
    item.append(copy, actions);
    historyList.append(item);
  });
}

function updateCharacterCount() {
  characterCount.textContent = `${questionInput.value.length} / ${questionInput.maxLength}`;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = questionInput.value;
  if (!question.trim()) {
    renderError("Enter a focused financial-report question before running the agent.");
    questionInput.focus();
    return;
  }

  setLoading(true);
  try {
    const agent_id = agentSelect.value;
    const response = await fetch(`${API_BASE_URL}/api/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent_id, question }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(typeof payload.detail === "string" ? payload.detail : "The agent request failed.");
    }
    renderResult(payload);
    addToHistory(question, payload);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to reach the agent service.";
    renderError(message);
  } finally {
    setLoading(false);
  }
});

questionInput.addEventListener("input", updateCharacterCount);

document.querySelectorAll("[data-question]").forEach((button) => {
  button.addEventListener("click", () => {
    questionInput.value = button.dataset.question;
    updateCharacterCount();
    questionInput.focus();
  });
});

clearHistoryButton.addEventListener("click", () => {
  history = [];
  localStorage.removeItem(HISTORY_KEY);
  renderHistory();
});

updateCharacterCount();
renderHistory();
