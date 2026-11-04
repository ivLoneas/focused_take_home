.DEFAULT_GOAL := help

REPORT ?= reports/model-refresh-2026-11-03/full.json
REPORT_PORT ?= 15500
export REPORT REPORT_PORT

.PHONY: help setup db-restore app report eval

help:
	@printf '%s\n' \
	  'make setup       Install dependencies; create .env if missing' \
	  'make db-restore  Restore the prepared index into an empty Docker database' \
	  'make app         Start PostgreSQL, API, and frontend; Ctrl-C stops app servers' \
	  'make report      Serve the latest committed evaluation without model calls' \
	  '                 Override REPORT=path/to/export.json REPORT_PORT=15500' \
	  'make eval        Run fresh paired evals (uses API credits)'

setup db-restore app report eval:
	@bash scripts/dev.sh $@
