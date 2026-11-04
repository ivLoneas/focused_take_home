"""Exercise developer commands without services, credentials, or model calls."""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def checkout(tmp_path):
    project = tmp_path / "project with spaces"
    project.mkdir()
    for relative in ("Makefile", "scripts/dev.sh"):
        source = ROOT / relative
        assert source.is_file(), f"Missing developer entry point: {relative}"
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (project / ".env.example").write_text("OPENAI_API_KEY=\nTYPESAFE_API_KEY=\n")
    (project / "frontend").mkdir()
    report = project / "reports/model-refresh-2026-11-03/full.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"evalId": "eval-saved-example", "results": {}}))
    python = project / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    dump = project / "data/dumps/retrieval_database.dump"
    dump.parent.mkdir(parents=True)
    dump.write_text("prepared database snapshot")
    bin_dir = project / "bin"
    bin_dir.mkdir()
    log = project / "commands.jsonl"
    fake = bin_dir / "fake-command"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json, os, signal, sys, time\n"
        "from pathlib import Path\n"
        "name = Path(sys.argv[0]).name\n"
        "args = sys.argv[1:]\n"
        "def record(event, **extra):\n"
        "    with open(os.environ['COMMAND_LOG'], 'a') as out:\n"
        "        out.write(json.dumps(dict(event=event, name=name, args=args, **extra)) + '\\n')\n"
        "record('call')\n"
        "if name == 'docker':\n"
        "    if 'pg_restore' in args:\n"
        "        record('restore_input', contents=sys.stdin.read())\n"
        "    sys.exit(int(os.environ.get('FAKE_DOCKER_EXIT', '0')))\n"
        "if name == 'promptfoo' and args and args[0] == 'show':\n"
        "    sys.exit(0 if os.environ.get('FAKE_REPORT_EXISTS') else 1)\n"
        "if name == 'uv' and args[:2] == ['run', 'python']:\n"
        "    if '-m' not in args:\n"
        "        os.execv(sys.executable, [sys.executable, *args[2:]])\n"
        "    role = 'frontend' if 'http.server' in args else 'backend'\n"
        "    def stop(signum, frame):\n"
        "        record('child_stop', role=role)\n"
        "        sys.exit(0)\n"
        "    signal.signal(signal.SIGTERM, stop)\n"
        "    signal.signal(signal.SIGINT, stop)\n"
        "    record('child_start', role=role, pid=os.getpid())\n"
        "    failure = os.environ.get('FAKE_' + role.upper() + '_EXIT')\n"
        "    if failure is not None:\n"
        "        time.sleep(0.3)\n"
        "        sys.exit(int(failure))\n"
        "    while True:\n"
        "        time.sleep(0.05)\n"
    )
    fake.chmod(0o755)
    for name in ("uv", "docker", "npm"):
        (bin_dir / name).symlink_to(fake)
    promptfoo = project / "evals/node_modules/.bin/promptfoo"
    promptfoo.parent.mkdir(parents=True)
    promptfoo.symlink_to(fake)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "COMMAND_LOG": str(log)}

    def events():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    return project, env, events


def run_make(checkout, *arguments):
    project, env, _ = checkout
    return subprocess.run(
        ["make", *arguments], cwd=project, env=env, capture_output=True, text=True, timeout=10, check=False
    )


def test_default_help_has_no_side_effects(checkout):
    project, _, events = checkout
    result = run_make(checkout)
    assert result.returncode == 0, result.stderr
    for command in ("setup", "app", "report", "eval"):
        assert command in result.stdout
    assert events() == []
    assert not (project / ".env").exists()


@pytest.mark.parametrize("existing", [False, True])
def test_setup_installs_dependencies_without_overwriting_configuration(checkout, existing):
    project, _, events = checkout
    original = "OPENAI_API_KEY=keep-this-value\n"
    if existing:
        (project / ".env").write_text(original)
    result = run_make(checkout, "setup")
    assert result.returncode == 0, result.stderr
    assert (project / ".env").read_text() == (
        original if existing else (project / ".env.example").read_text()
    )
    calls = {(event["name"], tuple(event["args"])) for event in events()}
    assert ("uv", ("sync",)) in calls
    assert ("npm", ("--prefix", "evals", "ci")) in calls


def wait_for_children(events, count):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        started = [event for event in events() if event["event"] == "child_start"]
        if len(started) >= count:
            return started
        time.sleep(0.02)
    pytest.fail(f"Expected {count} app children; observed {events()}")


@pytest.mark.parametrize("stop_signal", [signal.SIGTERM, signal.SIGINT])
def test_app_signal_stops_both_started_services(checkout, stop_signal):
    project, env, events = checkout
    process = subprocess.Popen(
        ["bash", "scripts/dev.sh", "app"], cwd=project, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
    )
    try:
        wait_for_children(events, 2)
        process.send_signal(stop_signal)
        process.communicate(timeout=5)
        stopped = {event["role"] for event in events() if event["event"] == "child_stop"}
        assert stopped == {"backend", "frontend"}
        docker = [event for event in events() if event["name"] == "docker"]
        assert any("up" in event["args"] and "--wait" in event["args"] for event in docker)
        assert not any("down" in event["args"] or "--volumes" in event["args"] for event in docker)
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


@pytest.mark.parametrize("failed_role", ["backend", "frontend"])
def test_app_propagates_child_failure_and_stops_other_service(checkout, failed_role):
    project, env, events = checkout
    env[f"FAKE_{failed_role.upper()}_EXIT"] = "7"
    process = subprocess.Popen(
        ["bash", "scripts/dev.sh", "app"], cwd=project, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
    )
    try:
        process.communicate(timeout=5)
        assert process.returncode == 7
        surviving_role = "frontend" if failed_role == "backend" else "backend"
        assert any(event.get("role") == surviving_role and event["event"] == "child_stop" for event in events())
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def test_app_does_not_start_servers_when_database_startup_fails(checkout):
    project, env, events = checkout
    env["FAKE_DOCKER_EXIT"] = "9"
    result = subprocess.run(
        ["bash", "scripts/dev.sh", "app"], cwd=project, env=env,
        capture_output=True, text=True, timeout=5, check=False,
    )
    assert result.returncode == 9
    assert not any(event["event"] == "child_start" for event in events())


def test_report_opens_saved_export_without_running_an_evaluation(checkout):
    _, _, events = checkout
    result = run_make(checkout, "report")
    assert result.returncode == 0, result.stderr
    calls = [event["args"] for event in events() if event["name"] == "promptfoo"]
    assert any(args[0] == "import" and args[1].endswith("model-refresh-2026-11-03/full.json") for args in calls)
    assert any(args[0] == "view" and "15500" in args for args in calls)
    assert not any(args[0] == "eval" or "--force" in args for args in calls)
    assert "15500" in result.stdout and "eval-saved-example" in result.stdout


def test_report_rejects_a_missing_file_before_starting_viewer(checkout):
    _, _, events = checkout
    result = run_make(checkout, "report", "REPORT=reports/missing report.json")
    assert result.returncode != 0
    assert "missing" in (result.stdout + result.stderr).lower()
    assert not any(event["name"] == "promptfoo" for event in events())


@pytest.mark.parametrize("port", ["0", "65536", "invalid"])
def test_report_rejects_invalid_port_before_starting_viewer(checkout, port):
    _, _, events = checkout
    result = run_make(checkout, "report", f"REPORT_PORT={port}")
    assert result.returncode != 0
    assert "REPORT_PORT" in (result.stdout + result.stderr)
    assert not any(event["name"] == "promptfoo" for event in events())


def test_report_reuses_existing_evaluation_without_reimporting(checkout):
    _, env, events = checkout
    env["FAKE_REPORT_EXISTS"] = "1"
    result = run_make(checkout, "report")
    assert result.returncode == 0, result.stderr
    calls = [event["args"] for event in events() if event["name"] == "promptfoo"]
    assert any(args[0] == "view" for args in calls)
    assert not any(args[0] == "import" or "--force" in args for args in calls)


@pytest.mark.parametrize("contents", ["not JSON", '{"results": {}}'])
def test_report_rejects_invalid_json_or_missing_eval_id_before_starting_viewer(checkout, contents):
    project, _, events = checkout
    report = project / "reports/invalid report.json"
    report.write_text(contents)
    result = run_make(checkout, "report", "REPORT=reports/invalid report.json")
    assert result.returncode != 0
    assert not any(event["name"] == "promptfoo" for event in events())


def test_eval_runs_paired_suite_with_fresh_results(checkout):
    _, _, events = checkout
    result = run_make(checkout, "eval")
    assert result.returncode == 0, result.stderr
    call = next(event for event in events() if event["name"] == "promptfoo")
    args = call["args"]
    assert args[0] == "eval"
    for option, value in (
        ("-c", "promptfooconfig.aligned_comparison.yaml"),
        ("--env-file", "../.env"),
        ("--max-concurrency", "4"),
        ("-o", "../reports/comparison.json"),
    ):
        assert args[args.index(option) + 1] == value
    assert "--no-cache" in args and "--no-share" in args


def test_database_restore_is_atomic_and_preserves_existing_database(checkout):
    _, _, events = checkout
    result = run_make(checkout, "db-restore")
    assert result.returncode == 0, result.stderr
    calls = [event["args"] for event in events() if event["name"] == "docker" and event["event"] == "call"]
    assert "--wait" in calls[0] and "postgres" in calls[0]
    restore = next(args for args in calls if "pg_restore" in args)
    for flag in ("--single-transaction", "--exit-on-error", "--no-owner", "--no-acl"):
        assert flag in restore
    assert not any(argument in {"--clean", "--create", "--volumes", "down"} for args in calls for argument in args)
    assert not any("DROP" in argument.upper() for args in calls for argument in args)
    assert any(event["event"] == "restore_input" and event["contents"] == "prepared database snapshot" for event in events())
