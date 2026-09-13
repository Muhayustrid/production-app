# GLM / Zcode implementation prompt

Copy the text below into Zcode with this project open. Sending it authorizes implementation of the local Work Order scope; merely reading this file does not.

---

Implement the Work Order workspace in `/Users/rotiropi/erpnext-new/apps/production_app`.

First read `AGENTS.md`, `IMPLEMENTATION_PLAN.md`, `TASKS.md`, and `PROJECT_STATE.md`, in that order. Follow their scope and business rules. The plan defines requirements, TASKS defines task dependencies/acceptance, and PROJECT_STATE records actual work. Later explicit user corrections take precedence; update the documents when a correction changes them.

Use the existing mockup at `/Users/rotiropi/mockup_production_app` as the UI source. Do not redesign it or edit that source repository. Implement only Work Order through native Manufacture. Do not implement the custom Stock Entry/handover page.

Confirmed rules: finished goods = good prepacking; raw materials remain based on planned quantity; overproduction follows current ERPNext settings; Leader Produksi is a name; Box 1/2 are decimal kg weights; good prepacking=0 must not be saved or finished. Zero reject/trial/sisa remains valid. Do not ask these decisions again.

Start from the first dependency-ready unfinished task in TASKS.md. One active task at a time. Set it IN_PROGRESS in PROJECT_STATE.md before editing. Complete its acceptance check, record real evidence, then continue to the next task without asking permission at every task boundary. Do not skip the transaction proof to build the UI first.

Before every final response, interruption handoff, or completed/blocked task, update PROJECT_STATE.md with changes, actual commands/results, blockers, and a precise next step. If resuming after context loss, read that file and inspect current changes; do not redo completed work blindly. Never mark DONE without the required verification. A skipped test is NOT RUN, never PASS.

Verify native methods and fields in the installed runtime before using them. The last observed backend is Docker container `erpnext-new-backend-1`, bench `/home/frappe/frappe-bench`, site `frontend`, with UI at `http://localhost:8081`. Verify host-to-container mapping before editing. Use `bench --site frontend ...` inside the verified runtime. Do not assume bench runs on the host or another historical site is correct.

Use available Zcode terminal/browser tools, not Codex-specific tool names. Follow applicable local repository instructions and available relevant skills. Use CodeGraph before searching code only when an index exists; if its command is unavailable, record that and use ordinary source search. Do not install tooling or generate an index merely to follow a preferred search path.

Reuse ERPNext document methods, the existing batch override in bakery_manufacturing, and the supplied Vue design. Do not edit ERPNext/Frappe core, duplicate batch logic, bypass permissions, force Completed, introduce a workflow engine, or create a second stock ledger. Keep abstractions and files proportional to actual ownership.

You may implement app code, scoped local migrations, and isolated tests needed by these tasks. Protect existing operational data and user changes. Back up the specific definitions before script/field cutover. Preserve useful native-form behavior. Do not change overproduction settings, delete unrelated scripts, make irreversible historical data conversions, commit, push, or deploy production.

If blocked, first record the concrete error and evidence in PROJECT_STATE.md. Stop dependent work and ask only for the missing decision/access outside the approved scope; do not invent facts, hide the failure, or expand into another feature. Continue authorized independent work only if its dependencies are satisfied.

Report to the user in Indonesian. Keep repository technical documentation consistent with its existing English text. End each work session with completed task IDs, verification results, unresolved issues, and the next task. Stop after T18 passes; Stock Entry/handover is a separate request.
