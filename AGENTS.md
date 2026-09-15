# Production App agent boundaries

- Read `IMPLEMENTATION_PLAN.md`, `TASKS.md`, and `PROJECT_STATE.md` before working on the Work Order workspace. They distinguish requirements, ordered tasks, and actual evidence.
- The current request is planning only. Do not create fields, remove scripts, or implement the plan until the user requests implementation. Later explicit user instructions take precedence.
- Scope is Work Order through Manufacture using good prepacking with planned raw materials. The custom Stock Entry/handover workflow is a separate task.
- Reuse the supplied mockup and native ERPNext documents/methods. Verify installed source before relying on behavior. Do not edit ERPNext/Frappe core or duplicate the `bakery_manufacturing` batch override.
- Box 1 and Box 2 are Float weights in kg. Leader Produksi is a person's name (Data). Use current native overproduction settings. Do not save prepacking or finish when good prepacking is zero; zero reject/trial/sisa remain valid.
- Preserve existing data and unrelated scripts. Retire an identified script only after its replacement is proven and its original definition is backed up.
- Follow the phase gates and acceptance criteria in the plan. Do not add speculative architecture or expand into excluded features.
- Where a `.codegraph/` index exists, use CodeGraph before text searches to locate or understand code. Do not create an index without a request.
- During implementation, select the next dependency-ready task from `TASKS.md`. Mark it in progress in `PROJECT_STATE.md` before edits and record evidence at completion, blockage, or handoff. Never mark work done from code inspection alone when its acceptance criterion requires execution.
- Keep one active task at a time. Do not start a dependent task before its gate passes. Continue ready work without repeated approval; pause dependent work only for a concrete blocker or a decision outside the approved scope.
- Do not depend on Codex-only tools. In Zcode, use available terminal/browser tools and installed project tooling. If a required capability is unavailable, record the precise limitation and do not claim verification.
