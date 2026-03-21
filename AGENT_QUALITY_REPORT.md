# Agent Quality Audit Report

Date: 2026-03-20
Scope: Root orchestration/system Python files only (excluded generated code under workspace/ and deployment/ as requested)

## Executive Summary

Your deployment/runtime problems are not random; they are structural.

Primary failure pattern:
1. Agents are optimized to "finish" and coordinate messaging, not to prove product correctness.
2. Verification gates check file existence/syntax, not runtime behavior, integration, or UX quality.
3. Prompts explicitly allow mocks and failing tests, which normalizes incomplete outputs.
4. Review coverage is narrow and misses critical frontend build/runtime and deployment preflight requirements.
5. Issue lifecycle and blocking semantics are inconsistent, so known defects do not reliably block release.

Result: pipelines can report success while shipping broken behavior and poor UI.

---

## Findings (Comprehensive)

## 1) Verification policy is artifact-based, not behavior-based (Critical)
Why this hurts quality:
- Agents can pass with the right filenames while app behavior is wrong.
- Missing runtime essentials (like React public assets) are not enforced.

Evidence:
- Frontend verification only requires `src/App.js`, pages/components folder, utils, README, and manifest; no `public/index.html`, no build/test pass requirement: [agent_orchestrator_v3.py](agent_orchestrator_v3.py#L735-L743)
- Deliverable check logic only counts files + required path groups + manifest: [agent_orchestrator_v3.py](agent_orchestrator_v3.py#L1133-L1161)

Fix:
- Add role-specific behavioral gates (e.g., frontend must pass `npm run build`; backend must pass smoke API checks).
- Add required frontend artifacts (`public/index.html`, `src/index.js`, CSS import target existence).

## 2) Success criteria explicitly tolerate failing tests (Critical)
Why this hurts quality:
- System incentivizes shipping broken code if tests “run”.

Evidence:
- QA criteria: tests can fail and still be acceptable: [agent_orchestrator_v3.py](agent_orchestrator_v3.py#L634-L665)
- Backend criteria: "Tests created (even if they fail due to external deps)": [general_agent.py](general_agent.py#L1606-L1609)

Fix:
- Define hard pass thresholds:
  - Tier 1: lint/syntax/build must pass.
  - Tier 2: minimum critical test subset must pass.
  - Tier 3: integration smoke checks must pass before deployment.

## 3) Prompt policy encourages mocks over integration correctness (High)
Why this hurts quality:
- Agents are told to continue with placeholders instead of resolving contract mismatches.
- Produces drift between frontend/backed expectations.

Evidence:
- Global rules: "MOCK MISSING DEPS": [general_agent.py](general_agent.py#L898)
- "Read upstream files if available, mock if not": [general_agent.py](general_agent.py#L916)
- "No External Testing": [general_agent.py](general_agent.py#L998)

Fix:
- Replace default mock-first policy with contract-first policy.
- Allow mocks only when explicitly annotated and behind feature flags.

## 4) Cross-layer context is weaker than claimed (High)
Why this hurts quality:
- File lists are passed instead of actual code context by default, so agents guess.

Evidence:
- Header claims "actual file contents": [agent_orchestrator_v3.py](agent_orchestrator_v3.py#L8)
- Implementation passes workspace + file list only: [agent_orchestrator_v3.py](agent_orchestrator_v3.py#L1070-L1077)
- Agent runtime explicitly sends only high-level context summary: [general_agent.py](general_agent.py#L1087-L1093)

Fix:
- Inject targeted upstream snippets automatically (API routes, DTOs, schema, shared constants).
- Build a contract packet per handoff (backend route map, frontend API client expectations, etc.).

## 5) QA gets intentionally reduced context (High)
Why this hurts quality:
- QA cannot reliably validate full system behavior with constrained context.

Evidence:
- QA special handling reduces context and asks it to discover files manually: [agent_orchestrator_v3.py](agent_orchestrator_v3.py#L1403-L1418)

Fix:
- Provide QA a deterministic manifest of artifacts and interface contracts.
- Auto-generate test matrix from ledger contracts.

## 6) Layer completion can succeed with skipped agents (Critical)
Why this hurts quality:
- Layer marked complete even when an agent is skipped for blocking issues.

Evidence:
- Skipped state recorded: [agent_orchestrator_v3.py](agent_orchestrator_v3.py#L1777-L1780)
- Only `ERROR:` outcomes fail a layer: [agent_orchestrator_v3.py](agent_orchestrator_v3.py#L1812-L1819)
- Then layer is reported completed: [agent_orchestrator_v3.py](agent_orchestrator_v3.py#L1821)

Fix:
- Treat `SKIPPED` as fail-fast unless explicit waiver.
- Require all roles in layer to return verified completion.

## 7) Blocking-issue semantics are inverted (Critical)
Why this hurts quality:
- Agents are blocked by issues they reported, not issues assigned to them.
- Critical fixes may not block intended owner.

Evidence:
- Blocking logic uses `reported_by == agent_role`: [issues_tracker.py](issues_tracker.py#L111-L118)
- Orchestrator relies on that blocking function: [agent_orchestrator_v3.py](agent_orchestrator_v3.py#L1768-L1774)

Fix:
- Block by `assigned_to == agent_role` (and/or dependency graph), not reporter.

## 8) Issue lifecycle is incomplete; resolution path is not enforced (High)
Why this hurts quality:
- Issues can remain open while pipeline still declares success.

Evidence:
- `resolve_issue()` exists: [issues_tracker.py](issues_tracker.py#L121-L152)
- No orchestrator enforcement that all high/critical issues are resolved before final success in second iteration: [agent_orchestrator_v3.py](agent_orchestrator_v3.py#L797-L889)

Fix:
- Add mandatory post-fix review gate and auto-close only after evidence-based verification.
- Block final success if any unresolved High/Critical issue exists.

## 9) Review coverage is too narrow for frontend/deployment quality (Critical)
Why this hurts quality:
- Reviewer checks a small set of patterns and misses real breakpoints (React build assets/imports, CSS, Docker buildability).

Evidence:
- Review checks are limited to README, API alignment, schema order, a few import checks, checkout completeness: [review_agent.py](review_agent.py#L102-L272)

Fix:
- Expand deterministic review checks:
  - Frontend: required CRA/Vite entry artifacts, unresolved imports, `npm run build`.
  - Backend: app boot + route registration smoke checks.
  - Deployment: Docker build preflight for each image.

## 10) Command output is truncated during agent loop (High)
Why this hurts quality:
- Critical test/build failure details may be cut off, leading to weak remediation.

Evidence:
- Tool result truncation to 10KB in agent loop: [general_agent.py](general_agent.py#L1376-L1382)

Fix:
- Store full command logs to files and provide summarized + tail + key error parser to model.

## 11) Prompt stack overweights process/comms vs product validation (High)
Why this hurts quality:
- Agents spend significant iterations on notebooks/blackboards and may still pass with weak product quality.

Evidence:
- Long mandatory communication phases and readiness checks emphasize messaging behavior: [general_agent.py](general_agent.py#L905-L1019), [general_agent.py](general_agent.py#L1279-L1316)

Fix:
- Keep communication requirements minimal and shift budget to compile/test/integration checks.
- Add iteration budget quotas (e.g., max 20% comms/tooling chatter before coding).

## 12) Security guidance includes deprecated/unsafe pattern examples (Medium)
Why this hurts quality:
- Example code can be copied by agents and introduce outdated crypto patterns.

Evidence:
- Uses `crypto.createCipher(...)` example: [agent_orchestrator_v3.py](agent_orchestrator_v3.py#L440)

Fix:
- Replace with `crypto.createCipheriv` + random IV + authenticated encryption patterns.

## 13) Director generation randomness is high for planning artifact (Medium)
Why this hurts quality:
- Higher variance in ledger and layers can produce inconsistent quality.

Evidence:
- Director calls with `temperature=0.7`: [director_agent.py](director_agent.py#L754), [director_agent.py](director_agent.py#L870)

Fix:
- Use lower temperature for planning/structure (e.g., `0.1-0.3`), reserve creativity for codegen roles.

## 14) Director auto-normalization may hide planning defects (Medium)
Why this hurts quality:
- Invalid or incomplete layer plans get auto-rewritten rather than surfaced as failures.

Evidence:
- Automatic role flatten/reorder/chunk rewrite of layers: [director_agent.py](director_agent.py#L114-L169)

Fix:
- Validate and fail loudly when layer intent is inconsistent, with explicit repair loop.

## 15) Early-stop in director can freeze a merely “valid” but low-quality ledger (Medium)
Why this hurts quality:
- Stable + valid does not imply complete or high-quality.

Evidence:
- Stops when no change count reached and validation passes: [director_agent.py](director_agent.py#L1040-L1041), [director_agent.py](director_agent.py#L1192-L1193)

Fix:
- Add quality completeness checks before early stop (contract coverage, test plan coverage, UI quality requirements).

## 16) Model deployment mismatch with current best available model (Medium)
Why this hurts quality:
- Agent runtime uses fixed `gpt-4o`; may underperform vs your currently available stronger model.

Evidence:
- Hardcoded model in `GeneralAgent`: [general_agent.py](general_agent.py#L1196)
- Legacy script also hardcodes `gpt-4o`: [backend-agent-test.py](backend-agent-test.py#L276)

Fix:
- Make model configurable per role and phase (`DIRECTOR_MODEL`, `EXECUTOR_MODEL`, `REVIEW_MODEL`).

## 17) Deployment agent overwrites generated artifacts each run (High)
Why this hurts quality:
- Can erase iterative improvements and prevents preserving corrected Docker/build configs.

Evidence:
- Unconditional writes in `generate_artifacts()`: [deployment_agent_azure.py](deployment_agent_azure.py#L85-L160)

Fix:
- Write only if missing, or use template sync with checksum + opt-in overwrite flag.

## 18) Deployment preflight checks are insufficient (Critical)
Why this hurts quality:
- Required frontend build assets/import targets are not pre-validated, causing late failure in Docker build.

Evidence:
- Local checks only verify minimal files (`package.json`, `app.js`), not frontend build prerequisites: [deployment_agent_azure.py](deployment_agent_azure.py#L393-L403)

Fix:
- Add preflight validation for frontend and backend build readiness:
  - `public/index.html`
  - required import targets exist
  - local `npm run build` dry-run (or static import resolution)

## 19) ACR naming is random per run, encouraging resource sprawl (Medium)
Why this hurts quality:
- Creates unnecessary registries and operational drift across iterations.

Evidence:
- Random suffix on registry naming: [deployment_agent_azure.py](deployment_agent_azure.py#L225)

Fix:
- Deterministic ACR naming + reuse existing registry by project/resource group.

## 20) Legacy/parallel script risk: old test harness can diverge behavior (Low)
Why this hurts quality:
- Multiple orchestration patterns increase confusion and inconsistent outcomes if wrong entrypoint is used.

Evidence:
- Separate legacy execution harness with independent loop and prompt stack: [backend-agent-test.py](backend-agent-test.py#L269-L367)

Fix:
- Deprecate/archive legacy runner; keep single orchestrator path and CI guard against stale entrypoints.

---

## Root Cause Map by Category

- Workflow design: #1, #2, #3, #6, #8, #11
- System architecture: #4, #5, #10, #14, #15
- Prompting/policy: #2, #3, #11, #12
- Model strategy: #13, #16
- Communication/coordination: #6, #7, #11
- Review & QA gates: #1, #2, #9, #18
- Deployment reliability: #17, #18, #19

---

## Prioritized Next Steps (Next Iteration Improvement Plan)

## Immediate (Today)
1. Enforce hard release gates in orchestrator:
   - Fail if any layer has `SKIPPED` role.
   - Fail if unresolved High/Critical issues remain.
2. Fix issue blocking semantics (`assigned_to`-based blocking).
3. Extend frontend verification policy to include `public/index.html` + build precheck.
4. Expand review checks for frontend build readiness and unresolved imports/CSS targets.

Impact: Very high
Complexity: Low-Medium

## Short Term (This Week)
1. Replace mock-first policy with contract-first policy.
2. Add per-role mandatory commands and parse pass/fail:
   - Frontend: `npm ci && npm run build`
   - Backend: boot + smoke API checks
3. Improve context handoff with contract bundles (API map, schema map, env contract).
4. Reduce communication overhead in prompts; increase implementation/test budget.
5. Make model selection configurable by phase and role.

Impact: Very high
Complexity: Medium

## Medium Term (This Sprint)
1. Introduce quality scorecard per run (build, tests, integration, UX rubric).
2. Add deterministic UI quality acceptance (layout sanity checks/screenshots + style baseline).
3. Add auto-remediation loop driven by structured failure parser (not raw truncated logs).
4. Stabilize director planning with lower temperature + strict schema validation + contract completeness checks.
5. Make deployment artifacts template-managed and non-destructive by default.

Impact: High
Complexity: Medium-High

---

## Top 10 Fixes (Action List)

1. Treat `SKIPPED` agent outcomes as pipeline failure.
2. Change blocking logic from reporter-based to assignee-based.
3. Block completion on unresolved High/Critical issues.
4. Require frontend build pass before verification success.
5. Require backend smoke checks before verification success.
6. Replace mock-first defaults with contract-first defaults.
7. Expand review agent to include frontend/deployment preflight checks.
8. Stop truncating critical command diagnostics without log fallback.
9. Make runtime model selection configurable and upgrade executor model policy.
10. Make deployment artifact generation non-destructive and add deterministic resource reuse.

---

## Suggested Implementation Sequence

Phase A (1-2 days): #1-#5 in Top 10
Phase B (2-4 days): #6-#8
Phase C (1 sprint): #9-#10 + scorecarding

This sequence gives the fastest improvement in first-pass correctness while reducing regressions in later deployment stages.
