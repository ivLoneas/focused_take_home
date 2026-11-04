"""Run the real buildless stream reader against fragmented browser response bytes."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parents[2] / "frontend" / "app.js"
RESULT = {"status": "answered", "answer": "£10\n<script>", "citations": ["Report p. 1"], "retrieval_attempts": 1}

HARNESS = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const options = JSON.parse(fs.readFileSync(0, 'utf8'));
const elements = new Map();
const listeners = new Map();
const writes = [];
let created = 0;
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    value: '', maxLength: 2000, textContent: '', dataset: {}, hidden: false,
    querySelector: (selector) => element(selector),
    addEventListener(name, callback) { listeners.set(`${id}:${name}`, callback); },
    replaceChildren() {}, append() {},
  });
  return elements.get(id);
}
const context = {
  window: {}, document: {
    querySelector: element, querySelectorAll: () => [],
    createElement: () => element(`created-${created++}`),
  },
  localStorage: {getItem: () => null, removeItem() {}, setItem(key, value) { writes.push(JSON.parse(value)); }},
  crypto: {randomUUID: () => 'saved-run'},
  TextDecoder, console, AbortSignal,
  URL,
};
vm.createContext(context);
let serverState = {active_thread_id:null,threads:[]};
let records = options.records;
if(options.submit) {
  records = records.split('\n').map(line => {
    if(!line.trim()) return line;
    const event=JSON.parse(line);
    if(event.type==='result') {
      event.result.metrics={...event.result.metrics,response_ms:1,first_token_ms:records.includes('"type": "token"')?0:null};
      serverState={active_thread_id:'server-thread',threads:[{id:'server-thread',agent_id:'agent_v2',
        created_at:'2026-11-04T10:00:00Z',updated_at:'2026-11-04T10:00:00Z',
        turns:[{...event.result,question:'Apple revenue?',created_at:'2026-11-04T10:00:00Z'}]}]};
      event.state=serverState;
    }
    return JSON.stringify(event);
  }).join('\n');
}
const bytes = Buffer.from(records, 'utf8');
const chunks = options.fragmented ? Array.from(bytes, byte => Uint8Array.of(byte)) : [new Uint8Array(bytes)];
let position = 0;
const response = {ok: true, body: {getReader: () => ({
  async read() {
    if (options.submit && writes.some(value => value.threads?.some(thread => thread.turns?.length))) {
      throw Error('Thread committed before stream completion');
    }
    if (!options.fragmented && position === 1 && options.progressive) {
      if (element('#answer').textContent !== options.progressive) throw Error('Answer not rendered before next read');
    }
    if (position < chunks.length) return {done: false, value: chunks[position++]};
    return {done: true};
  },
  releaseLock() {}, cancel() {},
})}};
context.response = response;
if (options.targeted) {
  element('#answer').textContent = 'Original question and clarification';
  context.pendingAnswer = element('#pending-answer');
}
let request;
let disabledDuringFetch;
context.fetch = async (url, init={}) => {
  if(new URL(url).pathname === '/api/session') return {ok:true,status:200,json:async()=>({active_thread_id:null,threads:[]})};
  request = {url, payload: JSON.parse(init.body)};
  disabledDuringFetch = ['#run-button', '#agent-select', '#question'].every(id => element(id).disabled);
  return response;
};
(async () => {
  vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
  vm.runInContext('renderAnswer = function(result, target=answer) { target.textContent = result.answer; }', context);
  await vm.runInContext('bootstrapPromise',context);
  if(options.targeted) element('#answer').textContent = 'Original question and clarification';
  if (options.submit) {
    element('#agent-select').value = 'agent_v2';
    element('#question').value = 'Apple revenue?';
    await listeners.get('#question-form:submit')({preventDefault() {}});
    console.log(JSON.stringify({
      request, disabledDuringFetch, writes, state:serverState,
      disabledAfter: ['#run-button', '#agent-select', '#question'].some(id => element(id).disabled),
      status: element('#response-status').dataset.status,
    }));
    return;
  }
  try {
    const result = await vm.runInContext(options.targeted ? 'readRunStream(response, pendingAnswer)' : 'readRunStream(response)', context);
    console.log(JSON.stringify({result, answer: element('#answer').textContent,
      ...(options.targeted ? {pending: element('#pending-answer').textContent} : {})}));
  } catch (error) {
    console.log(JSON.stringify({error: error.message, answer: element('#answer').textContent}));
  }
})();
"""


def read_stream(records, *, fragmented=False, progressive=None, submit=False, targeted=False):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to exercise the browser JavaScript stream reader")
    execution = subprocess.run(
        [node, "-e", HARNESS, str(APP_JS)],
        input=json.dumps({"records": records, "fragmented": fragmented, "progressive": progressive,
                          "submit": submit, "targeted": targeted}),
        capture_output=True, text=True, check=True, timeout=15,
    )
    return json.loads(execution.stdout)


def saved_turn(output):
    assert output["state"]["threads"], "No completed turn was saved"
    return output["state"]["threads"][0]["turns"][-1]


@pytest.mark.parametrize("fragmented", [False, True])
def test_reader_handles_coalesced_or_byte_fragmented_utf8_records(fragmented):
    records = "\n".join(json.dumps(frame, ensure_ascii=False) for frame in [
        {"type": "token", "text": "£10\n"}, {"type": "token", "text": "<script>"},
        {"type": "result", "result": RESULT},
    ]) + "\n"
    output = read_stream(records, fragmented=fragmented, progressive=None if fragmented else RESULT["answer"])
    assert output == {"result": RESULT, "answer": RESULT["answer"]}


def test_reader_accepts_final_complete_record_without_trailing_newline():
    output = read_stream(json.dumps({"type": "result", "result": RESULT}))
    assert output.get("result") == RESULT


def test_stream_reader_targets_pending_bubble_without_replacing_existing_transcript():
    records = "\n".join(json.dumps(frame) for frame in [
        {"type": "token", "text": "Revenue 10"}, {"type": "result", "result": RESULT},
    ]) + "\n"
    output = read_stream(records, targeted=True)
    assert output["answer"] == "Original question and clarification"
    assert output["pending"] == "Revenue 10"


@pytest.mark.parametrize("records", [
    "", '{"type":"token","text":"partial"}\n', '{"type":"result","result":',
    '{"type":"error","detail":"Stream unavailable"}\n',
])
def test_reader_rejects_empty_interrupted_malformed_or_error_streams(records):
    output = read_stream(records)
    assert "error" in output and "result" not in output
    assert output["error"] != "readRunStream is not defined"


def test_reader_safely_renders_text_and_app_only_saves_after_reader_completes():
    source = APP_JS.read_text()
    assert "readRunStream(response" in source
    assert "/api/session/run/stream" in source
    assert ".innerHTML" not in source
    assert "financial-report-agent:threads:v1" in source


def test_submit_streams_v2_and_saves_only_completed_result():
    records = "\n".join(json.dumps(frame) for frame in [
        {"type": "token", "text": RESULT["answer"]}, {"type": "result", "result": RESULT},
    ]) + "\n"
    output = read_stream(records, submit=True)
    assert output["request"]["url"].endswith("/api/session/run/stream")
    assert output["request"]["payload"] == {"agent_id": "agent_v2", "question": "Apple revenue?"}
    assert output["disabledDuringFetch"] is True and output["disabledAfter"] is False
    assert output["status"] == "answered"
    saved = saved_turn(output)
    assert saved["answer"] == RESULT["answer"]
    assert saved["citations"] == RESULT["citations"]
    assert output["state"]["threads"][0]["agent_id"] == "agent_v2"
    assert saved["metrics"]["response_ms"] >= 0
    assert 0 <= saved["metrics"]["first_token_ms"] <= saved["metrics"]["response_ms"]


@pytest.mark.parametrize("terminal", ["", '{"type":"error","detail":"Stream failed"}\n'])
def test_submit_does_not_save_failed_or_incomplete_stream_and_restores_controls(terminal):
    output = read_stream('{"type":"token","text":"partial"}\n' + terminal, submit=True)
    assert not any(value.get("threads") for value in output["writes"] if isinstance(value, dict))
    assert output["status"] == "error"
    assert output["disabledDuringFetch"] is True and output["disabledAfter"] is False


def test_static_stream_outcome_has_response_time_without_first_token_time():
    result = {"status": "needs_clarification", "answer": "Which company?", "citations": [], "retrieval_attempts": 0}
    output = read_stream(json.dumps({"type": "result", "result": result}) + "\n", submit=True)
    assert output["status"] == "needs_clarification"
    metrics = saved_turn(output)["metrics"]
    assert metrics["response_ms"] >= 0 and metrics["first_token_ms"] is None


def test_submit_merges_measured_backend_usage_with_browser_timing_in_history():
    result = {**RESULT, "metrics": {"total_tokens": 1234, "cost_usd": .000123}}
    output = read_stream(json.dumps({"type": "result", "result": result}) + "\n", submit=True)
    metrics = saved_turn(output)["metrics"]
    assert metrics["total_tokens"] == 1234 and metrics["cost_usd"] == .000123
    assert metrics["response_ms"] >= 0 and metrics["first_token_ms"] is None
