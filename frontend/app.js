"use strict";

const API_BASE_URL = window.AGENT_API_BASE_URL
  || `${window.location?.protocol === "https:" ? "https:" : "http:"}//${window.location?.hostname || "localhost"}:8000`;
const HISTORY_KEY = "financial-report-agent:runs:v1";
const THREADS_KEY = "financial-report-agent:threads:v1";
const IMPORTED_KEY = "financial-report-agent:session-imported:v1";
const MAX_THREADS = 20;
const MAX_CLARIFICATION_TURNS = 5;

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
const sourcesDetails = document.querySelector("#sources-details");
const sourcesSummary = document.querySelector("#sources-summary");
const responseTime = document.querySelector("#response-time");
const firstTokenTime = document.querySelector("#first-token-time");
const retrievalAttempts = document.querySelector("#retrieval-attempts");
const totalTokens = document.querySelector("#total-tokens");
const estimatedCost = document.querySelector("#estimated-cost");
const historyList = document.querySelector("#history-list");
const emptyHistory = document.querySelector("#empty-history");
const clearHistoryButton = document.querySelector("#clear-history");
const newThreadButton = document.querySelector("#new-thread");
const threadContext = document.querySelector("#thread-context");
const questionLabel = document.querySelector("#question-label");

let threads = [];
let activeThreadId = null;
let sessionReady = false;
let sessionLoading = false;
let isRunning = false;
let runStartedAt = null;
let firstTokenAt = null;

function newId() {
  return typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

function loadLegacyThreads() {
  const empty = { active_thread_id: null, threads: [] };
  try {
    const raw = localStorage.getItem(THREADS_KEY);
    if (raw !== null) {
      const saved = JSON.parse(raw);
      if (!saved || Array.isArray(saved) || !Array.isArray(saved.threads)) throw new TypeError("Invalid threads");
      const unique = new Map();
      saved.threads.filter(isSavedThread).forEach((thread) => {
        if (!unique.has(thread.id)) unique.set(thread.id, thread);
      });
      const valid = [...unique.values()].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)).slice(0, MAX_THREADS);
      return { active_thread_id: valid.some((thread) => thread.id === saved.active_thread_id) ? saved.active_thread_id : null,
        threads: valid };
    }
    const legacy = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    if (!Array.isArray(legacy)) return empty;
    const migrated = legacy.filter(isSavedRun).slice(0, MAX_THREADS).map((run) => ({
      id: newId(), agent_id: ["baseline", "agent_v2"].includes(run.agent_id) ? run.agent_id : "baseline",
      created_at: run.created_at || new Date().toISOString(), updated_at: run.created_at || new Date().toISOString(),
      turns: [run],
    }));
    const state = { active_thread_id: null, threads: migrated };
    return state;
  } catch {
    return empty;
  }
}

function isSavedRun(value) {
  return value && typeof value === "object"
    && typeof value.question === "string" && Boolean(value.question.trim())
    && typeof value.answer === "string"
    && ["answered", "needs_clarification", "out_of_domain"].includes(value.status)
    && Array.isArray(value.citations) && value.citations.every((source) => typeof source === "string")
    && (value.source_urls === undefined || (value.source_urls !== null && typeof value.source_urls === "object"
      && !Array.isArray(value.source_urls) && Object.values(value.source_urls).every((url) => typeof url === "string")));
}

function isSavedThread(value) {
  return value && typeof value.id === "string" && Boolean(value.id)
    && ["baseline", "agent_v2"].includes(value.agent_id)
    && typeof value.created_at === "string" && Number.isFinite(Date.parse(value.created_at))
    && typeof value.updated_at === "string" && Number.isFinite(Date.parse(value.updated_at))
    && Array.isArray(value.turns) && value.turns.length > 0 && value.turns.length <= MAX_CLARIFICATION_TURNS + 1
    && value.turns.every(isSavedRun)
    && value.turns.slice(0, -1).every((turn) => turn.status === "needs_clarification");
}

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, credentials: "include" });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const error = new Error(typeof payload.detail === "string" ? payload.detail : "The request failed.");
    error.status = response.status;
    throw error;
  }
  return response;
}

function applySessionState(state) {
  if (!state || !Array.isArray(state.threads) || !state.threads.every(isSavedThread)) {
    throw new Error("Invalid session response.");
  }
  threads = state.threads;
  activeThreadId = state.active_thread_id;
  renderHistory();
  const thread = activeThread();
  if (thread) {
    agentSelect.value = thread.agent_id;
    renderThread(thread);
  } else {
    resultPanel.hidden = true;
    answer.replaceChildren();
    resetRunDetails();
  }
}

function sessionError(error, target = answer) {
  if (error.status === 401) {
    sessionReady = false;
    threads = [];
    activeThreadId = null;
    answer.replaceChildren();
    questionInput.value = "";
    updateCharacterCount();
    renderHistory();
    renderError("Connection expired. Choose Reconnect to continue.");
    threadContext.hidden = true;
    threadContext.textContent = error.message;
  } else {
    renderError(error instanceof Error ? error.message : "Unable to reach the service.", target);
  }
}

async function bootstrapSession() {
  sessionLoading = true;
  updateComposer();
  try {
    let state = await (await apiRequest("/api/session", { signal: AbortSignal.timeout(10000) })).json();
    let imported = false;
    let importFailed = false;
    try { imported = localStorage.getItem(IMPORTED_KEY) === "true"; } catch { /* Storage may be unavailable. */ }
    if (!imported && state.threads.length === 0) {
      const legacy = loadLegacyThreads();
      if (legacy.threads.length) {
        legacy.threads = legacy.threads.map((thread) => ({
          id: thread.id, agent_id: thread.agent_id, created_at: thread.created_at, updated_at: thread.updated_at,
          turns: thread.turns.map((turn) => ({
            question: turn.question, answer: turn.answer, status: turn.status, citations: turn.citations,
            retrieval_attempts: turn.retrieval_attempts ?? 0, source_urls: turn.source_urls || {},
            metrics: turn.metrics || null, created_at: turn.created_at || thread.created_at,
          })),
        }));
        try {
          state = await (await apiRequest("/api/session/import", {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(legacy),
            signal: AbortSignal.timeout(10000),
          })).json();
        } catch (error) {
          if (error.status === 401) throw error;
          if (error.status === 409) {
            state = await (await apiRequest("/api/session", { signal: AbortSignal.timeout(10000) })).json();
          } else {
            importFailed = true;
          }
        }
      }
    }
    applySessionState(state);
    sessionReady = true;
    if (!importFailed) {
      try { localStorage.setItem(IMPORTED_KEY, "true"); } catch { /* Session data is already saved on the server. */ }
    }
  } catch (error) {
    sessionReady = false;
    sessionError(error);
  } finally {
    sessionLoading = false;
    updateComposer();
  }
}

async function mutateSession(path, method, payload) {
  if (isRunning) return;
  isRunning = true;
  updateComposer();
  try {
    const response = await apiRequest(path, {
      method, ...(payload === undefined ? {} : {
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      }),
    });
    applySessionState(await response.json());
    questionInput.value = "";
    updateCharacterCount();
  } catch (error) {
    sessionError(error, messageBody("Agent"));
  } finally {
    setLoading(false);
  }
}

function activeThread() {
  return threads.find((thread) => thread.id === activeThreadId) || null;
}

function pendingClarification(thread) {
  return thread?.turns.at(-1)?.status === "needs_clarification";
}

function updateComposer() {
  const thread = activeThread();
  const continuing = pendingClarification(thread);
  const limitReached = continuing && thread.turns.length > MAX_CLARIFICATION_TURNS;
  agentSelect.disabled = isRunning || sessionLoading || !sessionReady || continuing;
  questionInput.disabled = isRunning;
  runButton.disabled = isRunning || sessionLoading || !sessionReady || limitReached;
  newThreadButton.disabled = isRunning || sessionLoading;
  newThreadButton.textContent = sessionReady ? "New question" : "Reconnect";
  clearHistoryButton.disabled = isRunning || sessionLoading || !sessionReady || threads.length === 0;
  questionLabel.textContent = continuing ? "Clarification reply" : "Question";
  buttonLabel.textContent = isRunning ? "Running analysis…" : sessionLoading ? "Connecting…"
    : (continuing ? "Send clarification" : "Run analysis");
  questionInput.placeholder = continuing ? "Add the requested details…" : "e.g. What was Apple's total net sales in FY2025?";
  threadContext.hidden = true;
  threadContext.textContent = sessionLoading ? "Connecting to your session. You can type your question while it loads."
    : !sessionReady ? "Session unavailable or expired. Choose Reconnect to try again."
    : limitReached
    ? "Clarification limit reached. Start a new question with all the details."
    : continuing ? "Add the requested details to continue this question thread."
      : thread ? "This question is complete. Submit another question to start a separate thread." : "";
  document.querySelectorAll("#history-list button, [data-question]").forEach((button) => {
    button.disabled = isRunning || sessionLoading || !sessionReady;
  });
}

function setLoading(loading) {
  isRunning = loading;
  updateComposer();
  if (loading) {
    resultPanel.hidden = false;
    setStatus("loading", "Retrieving evidence…");
    answer.textContent = "The agent is analyzing the question and checking report context.";
    resetRunDetails();
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
  renderRunDetails(result);
  renderAnswer(result);
}

function renderRunDetails(result) {
  resultPanel.hidden = false;
  setStatus(result.status, statusLabel(result.status));
  retrievalAttempts.textContent = String(result.retrieval_attempts);
  responseTime.textContent = formatDuration(result.metrics?.response_ms);
  firstTokenTime.textContent = formatDuration(result.metrics?.first_token_ms);
  const tokens = result.metrics?.total_tokens;
  totalTokens.textContent = Number.isInteger(tokens) && tokens >= 0 ? tokens.toLocaleString("en-US") : "—";
  const cost = result.metrics?.cost_usd;
  estimatedCost.textContent = typeof cost === "number" && Number.isFinite(cost) && cost >= 0
    ? (cost > 0 && cost < 0.000001 ? "<$0.000001" : `$${cost.toFixed(6)}`) : "—";
  renderSources(result);
}

function formatDuration(milliseconds) {
  return typeof milliseconds === "number" && Number.isFinite(milliseconds) && milliseconds >= 0
    ? `${(milliseconds / 1000).toFixed(2)} s` : "—";
}

function resetRunDetails() {
  citations.replaceChildren();
  sourcesDetails.open = false;
  sourcesSummary.textContent = "0 sources";
  responseTime.textContent = "—";
  firstTokenTime.textContent = "—";
  retrievalAttempts.textContent = "—";
  totalTokens.textContent = "—";
  estimatedCost.textContent = "—";
}

function reportLabel(label) {
  return label.trim().replace(/\s*\|?\s*pp?\.\s*\d+(?:\s*[-–,]\s*\d+)*\s*$/i, "").trim();
}

function normalizeLabel(label) {
  return label.trim().toLowerCase().replace(/\s*\|\s*/g, "|").replace(/\s+/g, " ");
}

function reportKey(label) {
  return normalizeLabel(reportLabel(label)).split(/[^\p{L}\p{N}]+/u).filter(Boolean).sort().join(" ");
}

function safeHttpUrl(value) {
  if (typeof value !== "string" || /[\u0000-\u001f]/.test(value)) return null;
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url : null;
  } catch {
    return null;
  }
}

function citationUrl(label, sourceUrls = {}) {
  const entries = Object.entries(sourceUrls);
  const exact = entries.find(([source]) => normalizeLabel(source) === normalizeLabel(label));
  let url = exact ? safeHttpUrl(exact[1]) : null;
  if (!exact) {
    const key = reportKey(label);
    let matches = entries.filter(([source]) => reportKey(source) === key);
    if (!matches.length) {
      const identifiers = key.split(" ");
      if (identifiers.length >= 3) {
        matches = entries.filter(([source]) => {
          const available = new Set(reportKey(source).split(" "));
          return identifiers.every((identifier) => available.has(identifier));
        });
      }
    }
    const urls = matches.map(([, value]) => safeHttpUrl(value)).filter(Boolean);
    const reports = new Set(urls.map((value) => { value.hash = ""; return value.href; }));
    if (reports.size === 1) url = urls[0];
  }
  if (!url) return null;
  const page = label.trim().match(/pp?\.\s*(\d+)(?:\s*[-–,]\s*\d+)*$/i);
  if (page && Number(page[1]) > 0) url.hash = `page=${Number(page[1])}`;
  return url.href;
}

function reportLink(label, href) {
  const link = document.createElement("a");
  link.textContent = label;
  link.href = href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function renderAnswer(result, target = answer) {
  const fragment = DOMPurify.sanitize(marked.parse(result.answer), {
    RETURN_DOM_FRAGMENT: true,
    ALLOWED_TAGS: ["p", "br", "strong", "em", "blockquote", "ul", "ol", "li", "h1", "h2", "h3", "h4",
      "h5", "h6", "pre", "code", "table", "thead", "tbody", "tr", "th", "td", "a", "hr", "del"],
    ALLOWED_ATTR: ["href", "title", "start", "colspan", "rowspan"],
  });
  fragment.querySelectorAll("a").forEach((link) => {
    const url = safeHttpUrl(link.getAttribute("href"));
    if (url) {
      link.href = url.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    } else {
      link.replaceWith(document.createTextNode(link.textContent));
    }
  });
  target.replaceChildren(fragment);
  const walker = document.createTreeWalker(target, NodeFilter.SHOW_TEXT);
  const nodes = [];
  let node;
  while ((node = walker.nextNode())) {
    if (!node.parentElement.closest("a, code, pre")) nodes.push(node);
  }
  nodes.forEach((textNode) => {
    const matches = [...textNode.textContent.matchAll(/\[([^\]\n]+)\]/g)];
    if (!matches.length) return;
    const content = document.createDocumentFragment();
    let position = 0;
    matches.forEach((match) => {
      content.append(document.createTextNode(textNode.textContent.slice(position, match.index)));
      const href = citationUrl(match[1], result.source_urls);
      if (href) {
        const link = reportLink(match[0], href);
        link.className = "citation-link";
        content.append(link);
      } else {
        content.append(document.createTextNode(match[0]));
      }
      position = match.index + match[0].length;
    });
    content.append(document.createTextNode(textNode.textContent.slice(position)));
    textNode.replaceWith(content);
  });
}

function renderSources(result) {
  citations.replaceChildren();
  const sources = new Map();
  result.citations.forEach((label) => {
    const href = citationUrl(label, result.source_urls);
    const key = href ? href.split("#")[0] : normalizeLabel(reportLabel(label));
    if (!sources.has(key)) sources.set(key, { label: reportLabel(label), href });
  });
  sourcesSummary.textContent = `${sources.size} ${sources.size === 1 ? "source" : "sources"}`;

  if (sources.size === 0) {
    const item = document.createElement("li");
    item.className = "muted-citation";
    item.textContent = "No sources returned for this outcome.";
    citations.append(item);
  } else {
    sources.forEach(({ label, href }) => {
      const item = document.createElement("li");
      if (href) item.append(reportLink(label, href));
      else item.textContent = label;
      citations.append(item);
    });
  }
}

function renderError(message, target = answer) {
  resultPanel.hidden = false;
  setStatus("error", "Unable to run");
  target.textContent = message;
  resetRunDetails();
}

function messageBody(role) {
  const message = document.createElement("section");
  message.className = `thread-message ${role === "You" ? "user-message" : "assistant-message"}`;
  const label = document.createElement("p");
  label.className = "message-label";
  label.textContent = role;
  const body = document.createElement("div");
  body.className = "message-body";
  message.append(label, body);
  answer.append(message);
  return body;
}

function renderThread(thread) {
  renderRunDetails(thread.turns.at(-1));
  answer.replaceChildren();
  thread.turns.forEach((turn) => {
    messageBody("You").textContent = turn.question;
    renderAnswer(turn, messageBody("Agent"));
  });
}

async function openThread(thread) {
  await mutateSession("/api/session/active-thread", "PUT", { thread_id: thread.id });
}

async function newQuestion() {
  if (isRunning || sessionLoading) return;
  if (!sessionReady) {
    await bootstrapSession();
    return;
  }
  await mutateSession("/api/session/active-thread", "PUT", { thread_id: null });
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
  emptyHistory.hidden = threads.length > 0;
  clearHistoryButton.disabled = isRunning || threads.length === 0;

  threads.forEach((thread) => {
    const run = thread.turns.at(-1);
    const item = document.createElement("li");
    item.className = "history-item";

    const copy = document.createElement("div");
    copy.className = "history-copy";
    const title = document.createElement("strong");
    title.textContent = thread.turns[0].question;
    const summary = document.createElement("p");
    summary.textContent = run.answer;
    const meta = document.createElement("span");
    const date = new Date(thread.updated_at);
    meta.textContent = `${statusLabel(run.status)} · ${thread.turns.length} ${thread.turns.length === 1 ? "turn" : "turns"} · ${date.toLocaleString()}`;
    copy.append(title, summary, meta);

    const actions = document.createElement("div");
    actions.className = "history-actions";
    actions.append(
      createHistoryButton("Open", "text-button", () => openThread(thread)),
      createHistoryButton("Remove", "text-button danger", () =>
        mutateSession(`/api/session/threads/${encodeURIComponent(thread.id)}`, "DELETE")),
    );
    item.append(copy, actions);
    historyList.append(item);
  });
}

function updateCharacterCount() {
  characterCount.textContent = `${questionInput.value.length} / ${questionInput.maxLength}`;
}

async function readRunStream(response, target = answer, onState = () => {}) {
  if (!response.body) {
    throw new Error("Streaming is unavailable in this browser.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let buffer = "";
  let text = "";
  let result = null;

  function readRecord(line) {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (event.type === "error") {
      const error = new Error(event.detail || "The agent stream failed.");
      error.status = event.status;
      throw error;
    }
    if (result) throw new Error("Unexpected data after the completed result.");
    if (event.type === "token" && typeof event.text === "string") {
      text += event.text;
      if (firstTokenAt === null && runStartedAt !== null && event.text) {
        firstTokenAt = Date.now();
        firstTokenTime.textContent = formatDuration(firstTokenAt - runStartedAt);
      }
      target.textContent = text;
      setStatus("loading", "Writing answer…");
    } else if (event.type === "result" && event.result
      && typeof event.result.answer === "string"
      && ["answered", "needs_clarification", "out_of_domain"].includes(event.result.status)
      && Array.isArray(event.result.citations)
      && Number.isInteger(event.result.retrieval_attempts)) {
      result = event.result;
      if (event.state) onState(event.state);
    } else {
      throw new Error("Invalid agent stream response.");
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let boundary;
      while ((boundary = buffer.indexOf("\n")) !== -1) {
        readRecord(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 1);
      }
      if (done) break;
    }
    if (buffer.trim()) readRecord(buffer);
    if (!result) throw new Error("The response was interrupted. Please try again.");
    return result;
  } catch (error) {
    await reader.cancel();
    throw error;
  } finally {
    reader.releaseLock();
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (isRunning || sessionLoading || !sessionReady) return;
  const question = questionInput.value;
  if (!question.trim()) {
    renderError("Enter a focused financial-report question before running the agent.");
    questionInput.focus();
    return;
  }

  const selected = activeThread();
  const continuingThread = pendingClarification(selected) ? selected : null;
  const agent_id = continuingThread ? continuingThread.agent_id : agentSelect.value;
  const request = { agent_id, question };
  if (continuingThread) {
    request.thread_id = continuingThread.id;
  }
  runStartedAt = Date.now();
  firstTokenAt = null;
  setLoading(true);
  if (continuingThread) renderThread(continuingThread);
  else answer.replaceChildren();
  messageBody("You").textContent = question;
  const pendingAnswer = messageBody("Agent");
  pendingAnswer.textContent = "Analyzing the question and checking report evidence…";
  resetRunDetails();
  setStatus("loading", "Retrieving evidence…");
  try {
    const streaming = agent_id === "agent_v2";
    const endpoint = streaming ? "/api/session/run/stream" : "/api/session/run";
    const response = await apiRequest(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    let state;
    if (streaming) {
      await readRunStream(response, pendingAnswer, (completedState) => { state = completedState; });
    } else {
      state = (await response.json()).state;
    }
    applySessionState(state);
    questionInput.value = "";
    updateCharacterCount();
  } catch (error) {
    sessionError(error, pendingAnswer);
  } finally {
    runStartedAt = null;
    setLoading(false);
  }
});

questionInput.addEventListener("input", updateCharacterCount);

document.querySelectorAll("[data-question]").forEach((button) => {
  button.addEventListener("click", async () => {
    if (isRunning || !sessionReady) return;
    if (pendingClarification(activeThread())) await newQuestion();
    questionInput.value = button.dataset.question;
    updateCharacterCount();
    questionInput.focus();
  });
});

clearHistoryButton.addEventListener("click", () => mutateSession("/api/session/threads", "DELETE"));

newThreadButton.addEventListener("click", newQuestion);

updateCharacterCount();
renderHistory();
const bootstrapPromise = bootstrapSession();
