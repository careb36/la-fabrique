#!/usr/bin/env bash
# End-to-end run of the company loop against a real stack.
#
# Starts the backend, the workspace daemon and a fake LLM proxy against a
# Postgres and a NATS you provide (docker compose up postgres nats, or any
# local pair), then drives one company through the loop and checks each
# step from the outside, through the API:
#
#   1. init_company plans the foundation sprint; its one documentation task
#      is too short for the text checks, is sent back twice and then blocked
#      for a person; the sprint closes anyway, with its retrospective, and the
#      ScrumMaster's proposal is adopted (autonomy level 3).
#      Every task is advised by a fake Copilot CLI (e2e-copilot) on the
#      daemon's PATH; the advice reaches the agents' prompts and the sprint
#      list counts the tasks as advised.
#   2. The blocked task is listed in the inbox.
#   3. An Architect joins the team (after the foundation sprint, so that one
#      stays as planned). start_sprint with carry_over_ids gives the blocked
#      task another attempt beside a new task; the new attempt's prompts
#      carry "Previous attempt"; the new task is delivered, reviewed, sent
#      back once, briefed by the Architect and approved; the sprint closes.
#   4. The inbox no longer lists the original task.
#   5. A person carries the blocked attempt into a third sprint (the company
#      would not, on its own); it blocks again, and this time the ScrumMaster's
#      triage is told how the company's second attempts went. The procedure
#      adopted after the foundation sprint is measured over the two sprints
#      since and kept, and the proposal prompt lists what earlier procedures
#      did. The Architect, asked again, is told how its earlier brief went.
#   6. A ticket reported through the public form is triaged by the Support
#      agent beside the reporter's choice; a support admin decides, the
#      agent's record counts the decision, and the next ticket's prompt
#      carries that record.
#   7. A run from another producer gets the Reviewer agent's suggestion.
#   8. A task whose file marks authentication is approved by QA and still
#      waits for a person (the risk tier, at autonomy level 3 too); a
#      Manager accepts it.
#   9. Every task's history is legal, read by app/history_check.py, which
#      shares no code with the readers it checks.
#  10. QA only reviewed delivered work (the fake model's order check).
#
# Environment (defaults in brackets):
#   E2E_POSTGRES_HOST [127.0.0.1]  E2E_POSTGRES_PORT [5432]
#   E2E_POSTGRES_USER [factory]    E2E_POSTGRES_PASSWORD [$POSTGRES_PASSWORD]
#   E2E_POSTGRES_DB [factory_e2e]  (dropped and recreated on every run)
#   E2E_NATS_URL [nats://127.0.0.1:4222]
#   E2E_BACKEND_PORT [18000]       E2E_LLM_PORT [15100]
#   E2E_PYTHON [python]            the backend's interpreter (poetry env)
#   E2E_WORKDIR [mktemp]           logs and the project folder
#   E2E_TIMEOUT [300]              seconds to wait for each sprint to close
#
# Exit status is 0 only when every check passed. Logs stay in E2E_WORKDIR.
set -u
REPO=$(cd "$(dirname "$0")/../.." && pwd)
PG_HOST=${E2E_POSTGRES_HOST:-127.0.0.1}
PG_PORT=${E2E_POSTGRES_PORT:-5432}
PG_USER=${E2E_POSTGRES_USER:-factory}
PG_PASSWORD=${E2E_POSTGRES_PASSWORD:-${POSTGRES_PASSWORD:-}}
PG_DB=${E2E_POSTGRES_DB:-factory_e2e}
NATS_URL=${E2E_NATS_URL:-nats://127.0.0.1:4222}
# Keeps this run's JetStream streams and consumers apart from a stack that
# shares the same broker. Without it both use the work-queue stream
# FABRIQUE_TASKS with the consumer name "task-worker", so each silently takes
# and discards the other's task assignments.
NATS_NAMESPACE=${E2E_NATS_NAMESPACE:-e2e}
BACKEND_PORT=${E2E_BACKEND_PORT:-18000}
LLM_PORT=${E2E_LLM_PORT:-15100}
PY=${E2E_PYTHON:-python}
TIMEOUT=${E2E_TIMEOUT:-300}
WORK=${E2E_WORKDIR:-$(mktemp -d -t fabrique-e2e-XXXXXX)}
mkdir -p "$WORK/project" "$WORK/audit"
echo "# E2E project" > "$WORK/project/README.md"
API=http://127.0.0.1:$BACKEND_PORT
PROMPTS=$WORK/fake_llm.prompts.log
VIOLATIONS=$WORK/fake_llm.violations.log
: > "$PROMPTS"; : > "$VIOLATIONS"  # a reused E2E_WORKDIR starts clean
FAILED=0

check() {  # check <description> <shell test...>
  local what=$1; shift
  if "$@"; then echo "  ok   $what"; else echo "  FAIL $what"; FAILED=1; fi
}

# A bare /health is not enough: any other server on this port satisfies it.
# The agent server that also binds 127.0.0.1 on a shared host answers
# {"status":"ok"} there, so a plain `curl -sf` read "backend is up" while
# every /v1 call returned 404. Assert our payload, and name the collision
# explicitly instead of blaming the backend.
port_busy() { (echo > "/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
healthy() { curl -sf -m 2 "$API/health" | "$PY" -c 'import sys, json; sys.exit(json.load(sys.stdin).get("status") != "healthy")' 2>/dev/null; }

if port_busy "$BACKEND_PORT"; then
  echo "port $BACKEND_PORT is already in use by another process."
  echo "the e2e stack cannot start: set E2E_BACKEND_PORT to a free port."
  exit 2
fi

# A fresh database: the backend creates its own schema at startup.
"$PY" - "$PG_HOST" "$PG_PORT" "$PG_USER" "$PG_PASSWORD" "$PG_DB" <<'EOF' || { echo "could not recreate the database"; exit 2; }
import sys
import psycopg2
host, port, user, password, db = sys.argv[1:]
conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname="postgres")
conn.autocommit = True
with conn.cursor() as cur:
    cur.execute(f'DROP DATABASE IF EXISTS "{db}"')
    # UTF8 whatever the cluster default is: sprint names carry em dashes.
    cur.execute(f"CREATE DATABASE \"{db}\" ENCODING 'UTF8' TEMPLATE template0 LC_COLLATE 'C' LC_CTYPE 'C'")
conn.close()
EOF

rm -f "$PROMPTS"
# A console assistant the daemon can run, under its own name so a real
# Copilot or Claude CLI on this machine is never asked.
ADVICE="Fake Copilot advice: keep each module beside its test."
mkdir -p "$WORK/bin"
printf '#!/bin/sh\necho "%s"\n' "$ADVICE" > "$WORK/bin/e2e-copilot"
chmod +x "$WORK/bin/e2e-copilot"
FAKE_LLM_PORT=$LLM_PORT FAKE_LLM_PROMPTS=$PROMPTS FAKE_LLM_VIOLATIONS=$VIOLATIONS "$PY" "$REPO/scripts/e2e/fake_llm.py" > "$WORK/llm.log" 2>&1 & LPID=$!
PATH="$WORK/bin:$PATH" CONSOLE_ASSISTANT_COMMANDS=e2e-copilot \
  NATS_URL=$NATS_URL NATS_NAMESPACE=$NATS_NAMESPACE WORKSPACE_ROOT="$WORK/project" "$PY" "$REPO/vscode-daemon/daemon.py" > "$WORK/daemon.log" 2>&1 & DPID=$!
cleanup() { kill ${BPID:-} $DPID $LPID 2>/dev/null; wait 2>/dev/null; }
trap cleanup EXIT
# The backend asks the daemon once, at startup, which assistants it can run.
for _ in $(seq 1 30); do grep -q "Daemon ready" "$WORK/daemon.log" 2>/dev/null && break; sleep 1; done
grep -q "Daemon ready" "$WORK/daemon.log" || { echo "daemon did not come up; see $WORK/daemon.log"; exit 2; }
(
  cd "$REPO/backend" && exec env \
    POSTGRES_HOST=$PG_HOST POSTGRES_PORT=$PG_PORT POSTGRES_USER=$PG_USER POSTGRES_PASSWORD=$PG_PASSWORD POSTGRES_DB=$PG_DB \
    NATS_URL=$NATS_URL NATS_NAMESPACE=$NATS_NAMESPACE LLM_PROXY_URL=http://127.0.0.1:$LLM_PORT NEO4J_URI=bolt://127.0.0.1:1 \
    AUTH_REQUIRED=false JWT_SECRET_KEY=e2e-secret-e2e-secret-e2e-secret-e2e \
    CONSOLE_ASSISTANTS_ENABLED=true COPILOT_CLI_COMMAND_TEMPLATE='e2e-copilot -p {prompt}' CLAUDE_CLI_COMMAND_TEMPLATE= \
    SUPPORT_AGENT_ENABLED=true SUPPORT_AGENT_INTERVAL_SECONDS=2 \
    REVIEWER_AGENT_ENABLED=true REVIEWER_AGENT_INTERVAL_SECONDS=2 \
    AUTO_SELF_IMPROVEMENT_ENABLED=false AGENT_GRAPH_ENABLED=false AUDIT_LOG_PATH="$WORK/audit" \
    PYTHONPATH=.:app "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT"
) > "$WORK/backend.log" 2>&1 & BPID=$!

for _ in $(seq 1 60); do healthy && break; sleep 1; done
healthy || { echo "backend did not come up; see $WORK/backend.log"; exit 2; }
echo "stack up: $API (logs in $WORK)"

api() { curl -s "$@"; }
json() { "$PY" -c "import sys, json; d = json.load(sys.stdin); print($1)"; }
sprint_status() { api "$API/v1/sprints?company_id=$CID" | json "next((s['status'] for s in d if s['id'] == $1), '')"; }
board() { api "$API/v1/sprints/$1/board" | json "' '.join(f\"{i['title']}={i['status']}\" for c in d['columns'].values() for i in c)"; }
wait_sprint() {  # wait_sprint <sprint id>
  local start=$SECONDS
  while (( SECONDS - start < TIMEOUT )); do
    [ "$(sprint_status "$1")" = "completed" ] && return 0
    sleep 3
  done
  return 1
}
wait_value() {  # wait_value <seconds> <expected> <command...>: true once the command prints <expected>
  local deadline=$((SECONDS + $1)) expected=$2; shift 2
  while (( SECONDS < deadline )); do [ "$("$@")" = "$expected" ] && return 0; sleep 2; done
  [ "$("$@")" = "$expected" ]
}
# A sprint reads "completed" moments before the close writes the rest (the
# retrospective, the procedures' outcomes and proposals), so those checks wait.
messages_of_kind() { api "$API/v1/messages?company_id=$CID&kind=$1" | json "len(d['messages'])"; }
retry_decisions() { api "$API/v1/messages?company_id=$CID&kind=decision" | json "sum(1 for m in d['messages'] if m['body'].startswith('Triage decision: another attempt'))"; }
active_procedures() { api "$API/v1/procedures?company_id=$CID" | json "sum(1 for p in d['procedures'] if p['status'] == 'active')"; }
procedure_result() { api "$API/v1/procedures?company_id=$CID" | json "next(((p['outcome'] or {}).get('result', '') for p in d['procedures'] if p['title'] == '$1'), '')"; }
prompt_seen() { if [ "$(grep -c "$1" "$PROMPTS")" -ge 1 ]; then echo yes; else echo no; fi; }
advice_counts() { api "$API/v1/sprints?company_id=$CID" | json "next((a['advised']['total'], a['advised']['done'], a['unadvised']['total']) for s in d if s['id'] == $1 for a in [s['console_advice']])"; }
brief_counts() { api "$API/v1/sprints?company_id=$CID" | json "next((a['advised']['total'], a['advised']['done'], a['advised']['rework']) for s in d if s['id'] == $1 for a in [s['architect_advice']])"; }

echo "1. init_company → foundation sprint"
COMPANY=$(api -X POST "$API/v1/init_company" -H 'Content-Type: application/json' -d "{
  \"company_name\": \"E2E Co\", \"project_path\": \"$WORK/project\", \"autonomy_level\": 3,
  \"agents\": [{\"role\": \"Developer\", \"name\": \"Dev Ana\"}, {\"role\": \"QA\", \"name\": \"QA Quinn\"}, {\"role\": \"ScrumMaster\", \"name\": \"Sam\"}]}")
CID=$(echo "$COMPANY" | json "d.get('company_id', '')")
S0=$(echo "$COMPANY" | json "d.get('sprint_id', '')")
[ -n "$CID" ] && [ -n "$S0" ] || { echo "init_company failed: $COMPANY"; exit 2; }
check "the foundation sprint closes" wait_sprint "$S0"
echo "     board: $(board "$S0")"
check "its task is blocked for a person" test "$(board "$S0")" = "Create testing strategy document=blocked"
check "the quality gate asked for rework twice" test "$(api "$API/v1/messages?company_id=$CID&kind=request" | json "len(d['messages'])")" = 2
check "the ScrumMaster posted the retrospective" wait_value 60 1 messages_of_kind retrospective
check "the ScrumMaster answered the escalation" wait_value 60 1 retry_decisions
check "a procedure was proposed and adopted (autonomy 3)" wait_value 60 1 active_procedures

echo "2. the inbox"
BLOCKED_ID=$(api "$API/v1/inbox?company_id=$CID" | json "d['blocked_tasks'][0]['id'] if d['blocked_tasks'] else ''")
check "lists the blocked task" test -n "$BLOCKED_ID"

echo "3. start_sprint with carry_over_ids"
# The company hires an Architect after its foundation sprint, which stays as planned.
check "an Architect joins the team" test "$(api -X POST "$API/v1/agents" -H 'Content-Type: application/json' -d "{\"company_id\": $CID, \"role\": \"Architect\", \"name\": \"Ari\"}" | json "d.get('role', '')")" = Architect
NEW=$(api -X POST "$API/v1/start_sprint" -H 'Content-Type: application/json' -d "{
  \"company_id\": $CID, \"sprint_name\": \"Sprint 1\", \"start_date\": \"2026-01-02\", \"scope_size\": \"S\",
  \"backlog_items\": [{\"title\": \"Add parser\", \"description\": \"A function with a test.\", \"assignee\": \"Developer\"}],
  \"carry_over_ids\": [${BLOCKED_ID:-0}]}")
S1=$(echo "$NEW" | json "d.get('sprint_id', '')")
check "the sprint starts with two tasks" test "$(echo "$NEW" | json "len(d.get('backlog_item_ids', []))")" = 2
check "Sprint 1 closes" wait_sprint "$S1"
echo "     board: $(board "$S1")"
check "the new task is done and the retried one blocked again" test "$(board "$S1")" = "Add parser=done Create testing strategy document=blocked"
check "a console assistant advised both tasks, and one of them got done" test "$(advice_counts "$S1")" = "(2, 1, 0)"
check "its advice reached the new task's prompt" test "$(prompt_seen "## Task: Add parser.*External Console Assistant Notes.*$ADVICE")" = yes
check "the Architect briefed the new task after its rework, and it got done" test "$(brief_counts "$S1")" = "(1, 1, 0)"
check "its brief reached the next attempt's prompt" test "$(prompt_seen "## Task: Add parser.*Reuse the existing module layout")" = yes
check "the sprint list counts it as a briefed second attempt, not done" test "$(api "$API/v1/sprints?company_id=$CID" | json "next(s['second_attempts'] for s in d if s['id'] == $S1)")" = "{'total': 1, 'done': 0, 'briefed': 1, 'briefed_done': 0}"
check "the retried task's prompts carry the previous attempt" test "$(grep -c '## Previous attempt' "$PROMPTS")" -ge 1
check "and the ScrumMaster's brief" test "$(grep -c 'Brief for the next attempt: Write the full document' "$PROMPTS")" -ge 1
check "files were written to the project" test -f "$WORK/project/src/add_parser.py" -a -f "$WORK/project/tests/test_add_parser.py"
check "the delivery was verified" test "$(api "$API/v1/agent_runs?company_id=$CID" | json "sum(1 for r in d['agent_runs'] if r['status'] == 'verified')")" -ge 1

echo "4. the inbox after the carry-over"
check "no longer lists the original task" test "$(api "$API/v1/inbox?company_id=$CID" | json "[t['id'] for t in d['blocked_tasks']]")" != "[$BLOCKED_ID]"
check "lists the new attempt" test "$(api "$API/v1/inbox?company_id=$CID" | json "len(d['blocked_tasks'])")" = 1
check "counts no run of the company's own for a person" test "$(api "$API/v1/inbox?company_id=$CID" | json "d['pending_runs']")" = 0

echo "5. a third attempt, carried by a person"
ATTEMPT2=$(api "$API/v1/inbox?company_id=$CID" | json "d['blocked_tasks'][0]['id'] if d['blocked_tasks'] else ''")
NEW2=$(api -X POST "$API/v1/start_sprint" -H 'Content-Type: application/json' -d "{
  \"company_id\": $CID, \"sprint_name\": \"Sprint 2\", \"start_date\": \"2026-01-03\", \"scope_size\": \"S\",
  \"backlog_items\": [{\"title\": \"Add formatter\", \"description\": \"A function with a test.\", \"assignee\": \"Developer\"}],
  \"carry_over_ids\": [${ATTEMPT2:-0}]}")
S2=$(echo "$NEW2" | json "d.get('sprint_id', '')")
check "the sprint starts with two tasks" test "$(echo "$NEW2" | json "len(d.get('backlog_item_ids', []))")" = 2
check "Sprint 2 closes" wait_sprint "$S2"
echo "     board: $(board "$S2")"
check "the new task is done and the carried one blocked a third time" test "$(board "$S2")" = "Add formatter=done Create testing strategy document=blocked"
check "its triage was told how earlier second attempts went" test "$(grep -c 'How second attempts went in this company' "$PROMPTS")" -ge 1
check "with the numbers counted from the boards" test "$(grep -c '0 of 1 tasks carried into another sprint got done. With a brief from you: 0 of 1; without one: 0 of 0.' "$PROMPTS")" -ge 1
check "the procedure adopted after the foundation sprint was measured and kept" wait_value 60 kept procedure_result "Cover edge cases"
check "the proposal prompt listed what earlier procedures did" wait_value 60 yes prompt_seen '"Cover edge cases" (Developer, v1): kept, rework per task'
check "the Architect, asked again, was told how its earlier brief went" test "$(prompt_seen "Task: Add formatter.*earlier briefs.*Tasks you briefed: 1 of 1 got done, 0.00 rework requests per task")" = yes
check "the sprint list counts the briefed third attempt, not done" test "$(api "$API/v1/sprints?company_id=$CID" | json "next(s['second_attempts'] for s in d if s['id'] == $S2)")" = "{'total': 1, 'done': 0, 'briefed': 1, 'briefed_done': 0}"
check "the inbox lists only the latest attempt" test "$(api "$API/v1/inbox?company_id=$CID" | json "[t['sprint_id'] for t in d['blocked_tasks']]")" = "[$S2]"

echo "6. the help desk"
# Authentication is off, so every caller acts as a support admin.
report_bug() {  # report_bug <title> [extra JSON fields]
  api -X POST "$API/v1/support/report_bug" -H 'Content-Type: application/json' -d "{
  \"title\": \"$1\", \"description\": \"It spins forever.\", \"severity\": \"low\", \"reporter_email\": \"ana@e2e.test\"${2:+, $2}}" | json "d.get('ticket_num', '')"; }
ticket() { api "$API/v1/support/tickets/$1" | json "$2"; }
T1=$(report_bug "Board does not load" '"category": "bug"')
check "the Support agent triages a ticket from the public form" wait_value 60 "Support agent high" ticket "$T1" "d['triaged_by'], d['suggested_severity']"
check "beside the reporter's choice, which stays as reported" test "$(ticket "$T1" "d['severity'], d['category'], d['suggested_category']")" = "low bug bug"
check "and writes the reporter a first reply" test "$(ticket "$T1" "bool(d['agent_reply'])")" = True
check "its first prompt has no record yet" test "$(prompt_seen "TICKET $T1 .*How your earlier suggestions")" = no
DECIDED=$(api -X PATCH "$API/v1/support/tickets/$T1" -H 'Content-Type: application/json' -d '{"status": "in_progress", "severity": "high", "category": "incident"}' | json "d.get('decided_severity'), d.get('decided_category')")
check "a support admin decides impact and category" test "$DECIDED" = "high incident"
check "the decision sits beside both claims" test "$(ticket "$T1" "d['severity'], d['suggested_category'], d['decided_category'], d['decided_by']")" = "low bug incident support admin"
record_row() { api "$API/v1/support/agent_record" | json "[(f, t['decided'], t['agent_agreed'], t['agent_unusable'], t['reporter_chose'], t['reporter_agreed']) for f, t in sorted(d.items())]"; }
check "the agent's record counts it against the agent and the reporter" test "$(record_row)" = "[('category', 1, 0, 0, 1, 0), ('severity', 1, 1, 0, 1, 0)]"
DECIDED_AT=$(ticket "$T1" "d['decided_at']")
RESAVED=$(api -X PATCH "$API/v1/support/tickets/$T1" -H 'Content-Type: application/json' -d '{"status": "waiting", "severity": "high"}' | json "d.get('status', '')")
check "saving the same decision again does not decide anew" test "$RESAVED" = waiting -a "$(ticket "$T1" "d['decided_at']")" = "$DECIDED_AT"
T2=$(report_bug "Sprint page is blank")
check "a reporter who chose no category has none" test "$(ticket "$T2" "d['category']")" = None
check "the next ticket is triaged" wait_value 60 "Support agent high" ticket "$T2" "d['triaged_by'], d['suggested_severity']"
check "with that record in its prompt" test "$(prompt_seen "TICKET $T2 .*severity: yours matched 1 of 1; the reporter's own choice matched 0 of 1.*category: yours matched 0 of 1")" = yes

echo "7. the Reviewer agent"
# A run from another producer waits for a person; the agent suggests, beside the approval.
ingest_run() {  # ingest_run <external_ref> <claims JSON>
  api -X POST "$API/v1/agent_runs" -H 'Content-Type: application/json' -d "{
  \"company_id\": $CID, \"external_ref\": \"$1\", \"producer\": \"github\", \"agent_role\": \"Developer\",
  \"claims\": $2, \"artifact\": \"diff --git a/app.py b/app.py\\n+print('hi')\\n\"}" | json "d['id']"; }
run_field() { api "$API/v1/agent_runs/$1?company_id=$CID" | json "$2"; }
R1=$(ingest_run "pr-101" '{"files": ["app.py"], "summary": "Adds a greeting"}')
VERDICT=$(api -X POST "$API/v1/agent_runs/$R1/verify" -H 'Content-Type: application/json' -d "{\"company_id\": $CID, \"evidence\": {}}" | json "d['verdict']")
check "the Reviewer agent suggests on a run from another producer" wait_value 60 "Reviewer agent approved" run_field "$R1" "d['reviewed_by'], d['suggested_decision']"
check "beside no approval: a person still decides" test "$(api "$API/v1/agent_runs?company_id=$CID&exclude_in_house=true" | json "next(r['latest_approval'] for r in d['agent_runs'] if r['id'] == $R1)")" = None
check "its prompt carried the Verifier's verdict as an observation, and no record yet" test "$(prompt_seen "RUN pr-101 v1 .*Verifier's verdict: $VERDICT")" = yes -a "$(prompt_seen "RUN pr-101 v1 .*How your earlier suggestions")" = no
DECISION=$(api -X POST "$API/v1/agent_runs/$R1/approve" -H 'Content-Type: application/json' -d "{\"company_id\": $CID, \"approver_name\": \"ana\", \"decision\": \"rejected\", \"feedback\": \"Not this sprint\", \"rejection_category\": \"scope\"}" | json "d['decision']")
check "a Manager decides against it, and the suggestion stays beside the decision" test "$DECISION" = rejected -a "$(run_field "$R1" "d['suggested_decision']")" = approved
reviewer_record() { api "$API/v1/agent_runs/reviewer_record?company_id=$CID" | json "d['decided'], d['agent_agreed'], d['agent_unusable'], d['verifier_called'], d['verifier_agreed']"; }
case "$VERDICT" in verified) EXPECTED="1 0 0 1 0";; refuted) EXPECTED="1 0 0 1 1";; *) EXPECTED="1 0 0 0 0";; esac
check "the agent's record counts the miss, beside the Verifier's verdict ($VERDICT)" test "$(reviewer_record)" = "$EXPECTED"
R2=$(ingest_run "pr-102" '{"files": ["app.py"], "summary": "Adds a farewell"}')
check "the next run is reviewed" wait_value 60 "Reviewer agent approved" run_field "$R2" "d['reviewed_by'], d['suggested_decision']"
check "with that record in its prompt" test "$(prompt_seen "RUN pr-102 v1 .*yours matched 0 of 1")" = yes

echo "8. a high-risk delivery waits for a person"
# Its file name marks authentication (services/risk.py): QA's approval does
# not close it, at autonomy level 3 too; a Manager accepts it.
NEW3=$(api -X POST "$API/v1/start_sprint" -H 'Content-Type: application/json' -d "{
  \"company_id\": $CID, \"sprint_name\": \"Sprint 3\", \"start_date\": \"2026-01-04\", \"scope_size\": \"S\",
  \"backlog_items\": [{\"title\": \"Add login check\", \"description\": \"A function with a test.\", \"assignee\": \"Developer\"}]}")
S3=$(echo "$NEW3" | json "d.get('sprint_id', '')")
RISKY=$(echo "$NEW3" | json "d.get('backlog_item_ids', [''])[0]")
check "Sprint 3 closes around the held task" wait_sprint "$S3"
check "QA approved it, and it waits for a person" test "$(board "$S3")" = "Add login check=blocked"
check "the inbox lists it as a high-risk hold" test "$(api "$API/v1/inbox?company_id=$CID" | json "[(t['title'], t['risk_hold'], 'authentication: src/add_login_check.py' in t['reason']) for t in d['blocked_tasks'] if t['sprint_id'] == $S3]")" = "[('Add login check', True, True)]"
ACCEPTED=$(api -X PATCH "$API/v1/backlog/$RISKY" -H 'Content-Type: application/json' -d '{"status": "done", "comment": "High-risk delivery accepted by a person."}' | json "d.get('status', '')")
check "a Manager accepts it" test "$ACCEPTED" = done -a "$(board "$S3")" = "Add login check=done"

echo "9. every task's history, read independently"
# app/history_check.py imports none of the production readers it checks.
HISTORY=$(cd "$REPO/backend" && POSTGRES_HOST=$PG_HOST POSTGRES_PORT=$PG_PORT POSTGRES_USER=$PG_USER \
  POSTGRES_PASSWORD=$PG_PASSWORD POSTGRES_DB=$PG_DB PYTHONPATH=.:app "$PY" app/history_check.py 2>&1)
check "no illegal history (done without approval or verified delivery, carried twice, stray decision)" test "$(echo "$HISTORY" | tail -1)" = "0 illegal history(ies)"
echo "$HISTORY" | grep -v "illegal history" | sed 's/^/       /'

echo "10. the loop's order, seen from the model"
check "QA only reviewed delivered work, the files that delivery wrote" test ! -s "$VIOLATIONS"
[ -s "$VIOLATIONS" ] && sed 's/^/       /' "$VIOLATIONS"

echo "backend errors (Neo4j aside): $(grep '"level": "ERROR"' "$WORK/backend.log" | grep -vc Neo4j)"
if [ "$FAILED" = 0 ]; then echo "E2E PASSED"; else echo "E2E FAILED (logs in $WORK)"; fi
exit $FAILED
