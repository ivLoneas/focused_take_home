"""Exercise durable clarification threads through real browser event handlers."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "frontend" / "app.js"
THREADS_KEY = "financial-report-agent:threads:v1"
LEGACY_KEY = "financial-report-agent:runs:v1"


def result(status="answered", answer="Revenue 10"):
    return {"status": status, "answer": answer, "citations": [], "retrieval_attempts": 0,
            "metrics": {"total_tokens": 12, "cost_usd": .000001}}


HARNESS = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const options = JSON.parse(fs.readFileSync(0, 'utf8'));
const store = new Map(Object.entries(options.storage || {}));
const removed = [], requests = [], snapshots = [];
const timeoutDurations = [], pendingSnapshots = [];
const clone=value=>JSON.parse(JSON.stringify(value));
let server=clone(options.serverState || {active_thread_id:null,threads:[]});
let uuid=0,nodes,context,currentAction;
let bootstrapAttempts=0, releaseBootstrap=null, pendingReleased=false;
function makeNode(tag='div') {
  return {
    tagName:tag.toUpperCase(),children:[],dataset:{},attributes:{},listeners:{},
    disabled:false,hidden:false,value:'',maxLength:2000,open:false,
    classList:{add(){},remove(){},toggle(){}},
    get textContent(){return this._text||this.children.map(x=>typeof x==='string'?x:x.textContent||'').join('');},
    set textContent(value){this._text=String(value);this.children=[];},
    replaceChildren(...values){this._text='';this.children=values;},append(...values){this.children.push(...values);},
    addEventListener(name,callback){this.listeners[name]=callback;},
    setAttribute(name,value){this.attributes[name]=value;},getAttribute(name){return this.attributes[name];},
    querySelector(selector){return node(selector);},querySelectorAll(){return[];},focus(){},scrollIntoView(){},
  };
}
function node(id){if(!nodes.has(id))nodes.set(id,makeNode());return nodes.get(id);}
function flatten(root){return[root,...root.children.flatMap(x=>typeof x==='object'?flatten(x):[])];}
function response(payload,status=200,frames=null){
  let read=false;
  return{ok:status<400,status,json:async()=>clone(payload),body:frames?{getReader:()=>({
    async read(){if(read)return{done:true};read=true;return{done:false,value:new TextEncoder().encode(frames.map(x=>JSON.stringify(x)).join('\n')+'\n')};},
    cancel(){},releaseLock(){},
  })}:null};
}
async function fetchSession(url,init={}){
  const path=new URL(url,'http://localhost:8000').pathname;
  const method=init.method||'GET';const payload=init.body?JSON.parse(init.body):null;
  requests.push({url,path,method,payload,credentials:init.credentials,hasSignal:Boolean(init.signal)});
  if(currentAction?.expired)return response({detail:'Session expired. Reload to start a new session.'},401);
  if(path==='/api/session'&&method==='GET'){
    bootstrapAttempts++;
    if(options.pendingDraft&&!pendingReleased)await new Promise(resolve=>{releaseBootstrap=resolve;});
    if(bootstrapAttempts===1&&options.bootstrapFailure){
      if(options.bootstrapFailure==='network')throw TypeError('Network unavailable');
      if(options.bootstrapFailure==='timeout')throw Object.assign(Error('Connection timed out'),{name:'TimeoutError'});
      return response({detail:'Session unavailable'},503);
    }
    return response(server);
  }
  if(path==='/api/session/import'){
    if(options.importFailure){
      if(options.importFailure===409&&options.conflictState)server=clone(options.conflictState);
      return response({detail:'Legacy import unavailable'},options.importFailure);
    }
    if(server.threads.length)return response({detail:'Already imported'},409);
    server=clone(payload);return response(server);
  }
  if(currentAction?.mutationFailure && !path.includes('/run'))return response({detail:'Unavailable'},503);
  if(path==='/api/session/active-thread'){server.active_thread_id=payload.thread_id;return response(server);}
  if(path==='/api/session/threads'&&method==='DELETE'){server={active_thread_id:null,threads:[]};return response(server);}
  if(path.startsWith('/api/session/threads/')&&method==='DELETE'){
    const id=decodeURIComponent(path.split('/').pop());server.threads=server.threads.filter(t=>t.id!==id);
    if(server.active_thread_id===id)server.active_thread_id=null;return response(server);
  }
  if(path==='/api/session/run'||path==='/api/session/run/stream'){
    const action=currentAction;
    if(action.fail||action.storageFailure){
      const frames=[{type:'token',text:'partial'},...(action.fail==='incomplete'?[]:[{type:'error',detail:'Unavailable'}])];
      return path.endsWith('/stream')?response({},200,frames):response({detail:'Unavailable'},503);
    }
    let thread=payload.thread_id?server.threads.find(t=>t.id===payload.thread_id):null;
    if(!thread)thread={id:`thread-${++uuid}`,agent_id:payload.agent_id,created_at:new Date().toISOString(),updated_at:new Date().toISOString(),turns:[]};
    thread.turns.push({...clone(action.result),question:payload.question,created_at:new Date().toISOString()});
    thread.updated_at=new Date().toISOString();
    server.threads=[thread,...server.threads.filter(t=>t.id!==thread.id)].slice(0,20);server.active_thread_id=thread.id;
    const result={result:action.result,state:clone(server)};
    return path.endsWith('/stream')?response({},200,[{type:'result',...result}]):response(result);
  }
  throw Error(`Unexpected session request ${method} ${path}`);
}
async function initialize(){
  nodes=new Map();node('#agent-select').value='agent_v2';
  context={window:{scrollTo(){}},URL,TextDecoder,NodeFilter:{SHOW_TEXT:4},console,
    AbortSignal:{timeout(milliseconds){timeoutDurations.push(milliseconds);return new AbortController().signal;}},
    crypto:{randomUUID:()=>`browser-${++uuid}`},
    document:{querySelector:node,querySelectorAll:()=>[],createElement:makeNode,createTextNode:text=>({textContent:text}),
      createDocumentFragment:()=>makeNode(),createTreeWalker:()=>({nextNode:()=>null})},
    marked:{parse:text=>text},DOMPurify:{sanitize:text=>({textContent:text,querySelectorAll:()=>[]})},
    localStorage:{getItem:key=>store.get(key)||null,setItem:(key,value)=>store.set(key,value),removeItem:key=>{removed.push(key);store.delete(key);}},
    fetch:fetchSession,
  };
  vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
  vm.runInContext('renderAnswer=function(result,target=answer){target.textContent=result.answer;}',context);
  if(options.pendingDraft&&!pendingReleased){
    await Promise.resolve();
    node('#question').value=options.pendingDraft;
    pendingSnapshots.push(snapshot());
    pendingReleased=true;releaseBootstrap();
  }
  await vm.runInContext('bootstrapPromise',context);
}
function snapshot(){return{saved:clone(server),transcript:node('#answer').textContent,input:node('#question').value,
  placeholder:node('#question').placeholder,agent:node('#agent-select').value,agentDisabled:node('#agent-select').disabled,
  inputDisabled:node('#question').disabled,newLabel:node('#new-thread').textContent,
  buttonDisabled:node('#run-button').disabled,label:node('.button-label').textContent,help:node('#thread-context').textContent};}
(async()=>{try{
  await initialize();snapshots.push(snapshot());
  for(const action of options.actions||[]){currentAction=action;
    if('submit'in action){node('#question').value=action.submit;await node('#question-form').listeners.submit({preventDefault(){}});}
    else if('draft'in action)node('#question').value=action.draft;
    else if(action.new)await node('#new-thread').listeners.click({});
    else if(action.reload)await initialize();
    else if(action.clear)await node('#clear-history').listeners.click({});
    else if('open'in action||'remove'in action){
      const label='open'in action?'Open':'Remove';
      const matches=flatten(node('#history-list')).filter(x=>x.textContent===label&&x.listeners.click);
      await matches[action.open??action.remove].listeners.click({});
    }
    snapshots.push(snapshot());
  }
  console.log(JSON.stringify({snapshots,pendingSnapshots,timeoutDurations,requests,removed,storage:Object.fromEntries(store)}));
}catch(error){console.log(JSON.stringify({error:error.stack,snapshots,requests}));}})();
"""


def run_browser(actions=(), storage=None, server_state=None, **options):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for browser thread lifecycle tests")
    run = subprocess.run([node, "-e", HARNESS, str(APP)], input=json.dumps({"actions": actions, "storage": storage or {}, "serverState": server_state, **options}),
                         capture_output=True, text=True, check=True, timeout=15)
    output = json.loads(run.stdout)
    assert "error" not in output, output.get("error")
    return output


def test_clarification_reply_is_saved_in_same_thread_and_reload_restores_transcript():
    output = run_browser([
        {"submit": "What was revenue?", "result": result("needs_clarification", "Which company and fiscal year?")},
        {"submit": "Apple FY2025", "result": result()}, {"reload": True}, {"new": True},
        {"submit": "Amazon revenue?", "result": result()}, {"open": 1},
    ])
    first, reply, reload, new, fresh, reopened = output["snapshots"][1:]
    assert first["agentDisabled"] and first["input"] == "" and first["label"] == "Send clarification"
    assert "requested details" in (first["help"] + first.get("placeholder", "")).lower()
    runs = [request for request in output["requests"] if "/run" in request["path"]]
    assert runs[0]["payload"].get("thread_id") is None
    assert runs[1]["payload"] == {"agent_id": "agent_v2", "question": "Apple FY2025", "thread_id": first["saved"]["active_thread_id"]}
    assert runs[2]["payload"].get("thread_id") is None
    assert all(request["credentials"] == "include" for request in output["requests"])
    assert all("clarification_history" not in request["payload"] for request in runs)
    assert len(reply["saved"]["threads"]) == 1 and len(reply["saved"]["threads"][0]["turns"]) == 2
    assert reload["saved"]["active_thread_id"] == reply["saved"]["active_thread_id"]
    assert "What was revenue?" in reload["transcript"] and "Apple FY2025" in reload["transcript"]
    assert "Revenue 10" in reload["transcript"]
    assert new["saved"]["active_thread_id"] is None and not new["agentDisabled"]
    assert len(fresh["saved"]["threads"]) == 2
    assert "What was revenue?" in reopened["transcript"]
    assert THREADS_KEY not in output["storage"], "Ongoing transcripts belong to the server"


@pytest.mark.parametrize("failure", ["error", "incomplete"])
def test_failed_clarification_keeps_pending_thread_and_reply_retryable(failure):
    output = run_browser([
        {"submit": "Revenue?", "result": result("needs_clarification", "Which company?")},
        {"submit": "Apple", "fail": failure}, {"submit": "Apple", "result": result()},
    ])
    pending, failed, retried = output["snapshots"][1:]
    assert failed["saved"] == pending["saved"]
    assert failed["input"] == "Apple" and failed["agentDisabled"]
    assert "Revenue?" in failed["transcript"] and "Which company?" in failed["transcript"]
    assert len(retried["saved"]["threads"][0]["turns"]) == 2
    runs = [request for request in output["requests"] if "/run" in request["path"]]
    assert runs[1]["payload"] == runs[2]["payload"]


def test_first_request_failure_does_not_commit_thread():
    output = run_browser([{"submit": "Revenue?", "fail": "incomplete"}])
    saved = output["snapshots"][-1]["saved"]
    assert saved is None or saved["threads"] == []


def test_server_persistence_failure_preserves_pending_context_for_retry():
    output = run_browser([
        {"submit": "Revenue?", "result": result("needs_clarification", "Which company?")},
        {"submit": "Apple", "result": result(), "storageFailure": True},
        {"submit": "Apple", "result": result()},
    ])
    pending, failed, retried = output["snapshots"][1:]
    assert failed["saved"] == pending["saved"]
    assert failed["agentDisabled"] and failed["input"] == "Apple"
    runs = [request for request in output["requests"] if "/run" in request["path"]]
    assert runs[1]["payload"] == runs[2]["payload"]
    assert runs[2]["payload"]["thread_id"] == pending["saved"]["active_thread_id"]
    turns = retried["saved"]["threads"][0]["turns"]
    assert len(turns) == 2 and turns[-1]["question"] == "Apple"


def test_repeated_clarification_sends_only_server_thread_id():
    output = run_browser([
        {"submit": "Revenue?", "result": result("needs_clarification", "Which company?")},
        {"submit": "Apple", "result": result("needs_clarification", "Which fiscal year?")},
        {"submit": "FY2025", "result": result()},
    ])
    runs = [request for request in output["requests"] if "/run" in request["path"]]
    assert runs[-1]["payload"]["thread_id"] == runs[1]["payload"]["thread_id"]
    assert "clarification_history" not in runs[-1]["payload"]
    assert len(output["snapshots"][-1]["saved"]["threads"][0]["turns"]) == 3


def saved_thread(turns=1, status="needs_clarification"):
    return {"id": "saved-thread", "agent_id": "agent_v2", "created_at": "2026-11-04T10:00:00Z",
            "updated_at": "2026-11-04T10:00:00Z", "turns": [
                {"question": f"Original {index}", **result(status, "Which company?"), "created_at": "2026-11-04T10:00:00Z"}
                for index in range(turns)
            ]}


def test_pending_thread_restores_agent_lock_and_limit_with_new_question_escape():
    thread = saved_thread(turns=6)
    output = run_browser([{"new": True}], server_state={"active_thread_id": thread["id"], "threads": [thread]})
    restored, fresh = output["snapshots"]
    assert restored["agentDisabled"] and restored["buttonDisabled"]
    assert "new" in restored["help"].lower()
    assert not fresh["agentDisabled"] and not fresh["buttonDisabled"]
    assert fresh["saved"]["active_thread_id"] is None and len(fresh["saved"]["threads"]) == 1


def test_five_prior_clarifications_still_allow_last_bounded_reply():
    thread = saved_thread(turns=5)
    output = run_browser(server_state={"active_thread_id": thread["id"], "threads": [thread]})
    assert output["snapshots"][0]["agentDisabled"] and not output["snapshots"][0]["buttonDisabled"]


def test_legacy_runs_migrate_once_without_deleting_original_storage():
    legacy = [{"id": "old", "agent_id": "baseline", "question": "Old revenue?", **result(),
               "created_at": "2026-11-01T10:00:00Z"}]
    output = run_browser([{"reload": True}], {LEGACY_KEY: json.dumps(legacy)})
    saved = output["snapshots"][-1]["saved"]
    assert len(saved["threads"]) == 1 and saved["threads"][0]["turns"][0]["question"] == "Old revenue?"
    assert LEGACY_KEY in output["storage"] and LEGACY_KEY not in output["removed"]
    assert output["storage"]["financial-report-agent:session-imported:v1"] == "true"
    assert sum(request["path"] == "/api/session/import" for request in output["requests"]) == 1


@pytest.mark.parametrize("stored", ["not json", "[]", '{"active_thread_id":null,"threads":[{}]}'])
def test_corrupt_thread_storage_recovers_without_crashing(stored):
    output = run_browser([{"submit": "Fresh question", "result": result()}], {THREADS_KEY: stored})
    assert len(output["snapshots"][-1]["saved"]["threads"]) == 1


def test_thread_limit_retains_twenty_most_recently_updated_threads():
    threads = []
    for index in range(21):
        thread = saved_thread(status="answered")
        thread["id"] = f"saved-{index}"
        thread["updated_at"] = f"2026-10-{index + 1:02d}T10:00:00Z"
        threads.append(thread)
    output = run_browser([{"submit": "Newest question", "result": result()}], server_state={"active_thread_id": None, "threads": threads[:20]})
    saved = output["snapshots"][-1]["saved"]["threads"]
    assert len(saved) == 20 and saved[0]["turns"][0]["question"] == "Newest question"
    assert "saved-19" not in {thread["id"] for thread in saved}


def test_failed_server_mutation_keeps_current_thread_visible():
    output = run_browser([
        {"submit": "Revenue?", "result": result("needs_clarification", "Which company?")},
        {"new": True, "mutationFailure": True},
    ])
    before, after = output["snapshots"][1:]
    assert after["saved"] == before["saved"]
    assert "Revenue?" in after["transcript"] and after["agentDisabled"]


def test_session_expiry_discards_stale_display_and_requires_reload():
    output = run_browser([
        {"submit": "Revenue?", "result": result("needs_clarification", "Which company?")},
        {"submit": "Apple", "expired": True},
    ])
    expired = output["snapshots"][-1]
    assert "Revenue?" not in expired["transcript"]
    assert "expired" in (expired["transcript"] + expired["help"]).lower()
    assert expired["buttonDisabled"]
    assert not expired["inputDisabled"]


def test_nonempty_server_history_skips_legacy_import_and_keeps_backup():
    thread = saved_thread(status="answered")
    backup = json.dumps({"active_thread_id": "local", "threads": []})
    output = run_browser(storage={THREADS_KEY: backup}, server_state={"active_thread_id": thread["id"], "threads": [thread]})
    assert not any(request["path"] == "/api/session/import" for request in output["requests"])
    assert output["storage"][THREADS_KEY] == backup
    assert output["storage"]["financial-report-agent:session-imported:v1"] == "true"


@pytest.mark.parametrize("failure", [503, "network", "timeout"])
def test_bootstrap_failure_keeps_draft_editable_and_reconnect_preserves_it(failure):
    output = run_browser([{"draft": "Apple FY2025 revenue?"}, {"new": True}], bootstrapFailure=failure)
    failed, drafted, reconnected = output["snapshots"]
    assert not failed["inputDisabled"] and failed["buttonDisabled"]
    assert failed["newLabel"] == "Reconnect"
    assert drafted["input"] == reconnected["input"] == "Apple FY2025 revenue?"
    assert not reconnected["inputDisabled"] and not reconnected["buttonDisabled"]
    assert reconnected["newLabel"] == "New question"
    assert output["timeoutDurations"] and all(duration == 10000 for duration in output["timeoutDurations"])
    assert all(request["hasSignal"] for request in output["requests"] if request["path"] == "/api/session")


def test_pending_bootstrap_allows_typing_and_preserves_draft_after_thread_restore():
    thread = saved_thread()
    output = run_browser(server_state={"active_thread_id": thread["id"], "threads": [thread]},
                         pendingDraft="Apple FY2025")
    pending = output["pendingSnapshots"][0]
    restored = output["snapshots"][0]
    assert not pending["inputDisabled"] and pending["buttonDisabled"]
    assert "analysis" not in pending["label"].lower()
    assert "connect" in pending["label"].lower() or "session" in pending["label"].lower()
    assert restored["input"] == "Apple FY2025" and not restored["inputDisabled"]
    assert restored["agentDisabled"] and not restored["buttonDisabled"]


@pytest.mark.parametrize("status", [422, 503])
def test_failed_legacy_import_is_nonfatal_and_keeps_backup_for_retry(status):
    legacy = [{"id": "old", "agent_id": "baseline", "question": "Old revenue?", **result(),
               "created_at": "2026-11-01T10:00:00Z"}]
    backup = json.dumps(legacy)
    output = run_browser(storage={LEGACY_KEY: backup}, importFailure=status)
    ready = output["snapshots"][0]
    assert not ready["inputDisabled"] and not ready["buttonDisabled"]
    assert output["storage"][LEGACY_KEY] == backup
    assert output["storage"].get("financial-report-agent:session-imported:v1") != "true"
    assert "import" not in (ready["transcript"] + ready["help"]).lower()


def test_import_conflict_restores_server_state_instead_of_locking_composer():
    thread = saved_thread()
    conflict = {"active_thread_id": thread["id"], "threads": [thread]}
    backup = json.dumps({"active_thread_id": None, "threads": [saved_thread(status="answered")]})
    output = run_browser(storage={THREADS_KEY: backup}, importFailure=409, conflictState=conflict)
    ready = output["snapshots"][0]
    assert not ready["inputDisabled"] and not ready["buttonDisabled"]
    assert "Original 0" in ready["transcript"]
    assert sum(request["path"] == "/api/session" for request in output["requests"]) == 2


def test_import_expired_session_stays_unready_but_question_remains_editable():
    backup = json.dumps({"active_thread_id": None, "threads": [saved_thread(status="answered")]})
    output = run_browser(storage={THREADS_KEY: backup}, importFailure=401)
    expired = output["snapshots"][0]
    assert expired["buttonDisabled"] and not expired["inputDisabled"]
    assert expired["newLabel"] == "Reconnect"


def test_agent_run_has_no_bootstrap_timeout_signal():
    output = run_browser([{"submit": "Revenue?", "result": result()}])
    requests = output["requests"]
    assert all(request["hasSignal"] for request in requests if request["path"] == "/api/session")
    assert not any(request["hasSignal"] for request in requests if "/run" in request["path"])
