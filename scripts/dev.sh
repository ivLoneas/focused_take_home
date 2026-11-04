#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project_root"

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        printf 'Missing requirement: %s. See README.md prerequisites.\n' "$1" >&2
        exit 1
    fi
}

require_promptfoo() {
    require_command node
    if [[ ! -x evals/node_modules/.bin/promptfoo ]]; then
        printf 'Promptfoo is not installed. Run npm --prefix evals ci or make setup.\n' >&2
        exit 1
    fi
    export PROMPTFOO_CONFIG_DIR="${PROMPTFOO_CONFIG_DIR:-$project_root/.cache/promptfoo}"
    export PROMPTFOO_DISABLE_TELEMETRY=1
}

start_database() {
    require_command docker
    docker compose up -d --wait postgres
}

case "${1:-}" in
    setup)
        require_command uv
        require_command npm
        uv sync
        npm --prefix evals ci
        if [[ ! -e .env && ! -L .env ]]; then
            cp .env.example .env
            printf 'Created .env. Add your OPENAI_API_KEY and TYPESAFE_API_KEY.\n'
        else
            printf 'Kept existing .env.\n'
        fi
        ;;
    db-restore)
        start_database
        docker compose exec -T postgres pg_restore \
            -U rag -d rag --single-transaction --exit-on-error --no-owner --no-acl \
            < data/dumps/retrieval_database.dump
        ;;
    app)
        require_command uv
        start_database
        backend_pid=
        frontend_pid=
        cleanup() {
            trap - EXIT INT TERM
            for child in "$backend_pid" "$frontend_pid"; do
                if [[ -n "$child" ]]; then
                    kill -TERM "$child" 2>/dev/null || true
                fi
            done
            for child in "$backend_pid" "$frontend_pid"; do
                if [[ -n "$child" ]]; then
                    wait "$child" 2>/dev/null || true
                fi
            done
        }
        trap cleanup EXIT
        trap 'exit 130' INT
        trap 'exit 143' TERM

        uv run python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 &
        backend_pid=$!
        uv run python -m http.server 5173 --bind 127.0.0.1 --directory frontend &
        frontend_pid=$!
        printf 'App: http://localhost:5173\nAPI: http://localhost:8000/docs\nPress Ctrl-C to stop the app servers.\n'

        # Bash 3.2 on macOS does not provide wait -n.
        while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
            sleep 0.2
        done
        if ! kill -0 "$backend_pid" 2>/dev/null; then
            wait "$backend_pid"
        else
            wait "$frontend_pid"
        fi
        ;;
    report)
        report_file="${REPORT:-reports/model-refresh-2026-11-03/full.json}"
        report_port="${REPORT_PORT:-15500}"
        if [[ ! -f "$report_file" ]]; then
            printf 'Report file is missing: %s\n' "$report_file" >&2
            exit 1
        fi
        if [[ ! "$report_port" =~ ^[0-9]+$ ]] || (( 10#$report_port < 1 || 10#$report_port > 65535 )); then
            printf 'REPORT_PORT must be an integer from 1 to 65535.\n' >&2
            exit 1
        fi
        require_promptfoo
        eval_id=$(node -e '
            try {
                const report = JSON.parse(require("node:fs").readFileSync(process.argv[1], "utf8"));
                if (typeof report.evalId !== "string" || !/^eval-[A-Za-z0-9_.:-]+$/.test(report.evalId)) {
                    throw new Error("missing or invalid evalId");
                }
                process.stdout.write(report.evalId);
            } catch (error) {
                console.error("Invalid Promptfoo report: " + error.message);
                process.exit(1);
            }
        ' "$report_file")
        if ! evals/node_modules/.bin/promptfoo show eval "$eval_id" >/dev/null 2>&1; then
            evals/node_modules/.bin/promptfoo import "$report_file"
        fi
        printf 'Saved report: http://localhost:%s/eval/%s\nPress Ctrl-C to stop the viewer.\n' "$report_port" "$eval_id"
        exec evals/node_modules/.bin/promptfoo view --no --port "$report_port"
        ;;
    eval)
        require_promptfoo
        if [[ ! -x .venv/bin/python ]]; then
            printf 'Python dependencies are not installed. Run make setup.\n' >&2
            exit 1
        fi
        mkdir -p reports
        export PYTHONPATH="$project_root"
        export PROMPTFOO_PYTHON="$project_root/.venv/bin/python"
        cd evals
        exec node_modules/.bin/promptfoo eval \
            -c promptfooconfig.aligned_comparison.yaml --env-file ../.env \
            --no-cache --no-share --max-concurrency 4 -o ../reports/comparison.json
        ;;
    *)
        printf 'Usage: bash scripts/dev.sh {setup|db-restore|app|report|eval}\n' >&2
        exit 2
        ;;
esac
