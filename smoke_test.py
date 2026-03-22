"""
smoke_test.py
Dependency-free smoke test for the pure math in scorer.py.
Tests all normalisation helpers and the EMA/alpha logic using only stdlib.
Run: python smoke_test.py

For the full pytest suite (requires pydantic):
  pip install pydantic pytest
  pytest tests/ -v
"""

import math
import sys

PASS = []
FAIL = []


def check(name: str, condition: bool, detail: str = ""):
    if condition:
        PASS.append(name)
        print(f"  PASS  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))


# ── Inline re-implementations (no pydantic needed) ───────────────────────────

METRIC_WEIGHTS = {
    "contract_fidelity":         0.25,
    "downstream_satisfaction":   0.25,
    "pre_healer_test_pass_rate": 0.20,
    "security_compliance_score": 0.20,
    "token_efficiency":          0.10,
}

ALPHA_CEIL, ALPHA_FLOOR, DECAY_RATE = 0.60, 0.05, 10.0

def compute_alpha(n):
    return ALPHA_FLOOR + (ALPHA_CEIL - ALPHA_FLOOR) * math.exp(-n / DECAY_RATE)

def _ema(old, new, alpha):
    return max(0.0, min(alpha * new + (1 - alpha) * old, 1.0))

def score(contract, downstream, pre_healer, security, token):
    return (METRIC_WEIGHTS["contract_fidelity"]         * contract
          + METRIC_WEIGHTS["downstream_satisfaction"]   * downstream
          + METRIC_WEIGHTS["pre_healer_test_pass_rate"] * pre_healer
          + METRIC_WEIGHTS["security_compliance_score"] * security
          + METRIC_WEIGHTS["token_efficiency"]          * token)

ROLE_TOKEN_BASELINES = {
    "backend_engineer": 1/50, "frontend_engineer": 1/60,
    "database_architect": 1/80, "qa_engineer": 1/70,
    "documentation_writer": 1/5, "security_reviewer": 1/120,
    "devops_engineer": 1/90, "cost_optimizer": 1/100,
    "healer_agent": 1/110, "default": 1/75,
}

def normalise_token_efficiency(output_units, tokens_consumed, role):
    if tokens_consumed == 0: return 0.0
    baseline = ROLE_TOKEN_BASELINES.get(role, ROLE_TOKEN_BASELINES["default"])
    x = 3.0 * (output_units / tokens_consumed / baseline - 1.0)
    return 1.0 / (1.0 + math.exp(-x))

def normalise_test_pass_rate(passing, total):
    if total <= 0: return 1.0
    return max(0.0, min(passing / total, 1.0))

def normalise_downstream_satisfaction(correction_requests):
    return max(0.0, 1.0 - correction_requests * 0.20)

SECURITY_PENALTIES = {"critical": 0.25, "high": 0.10, "medium": 0.04, "low": 0.01}
SECURITY_CAT_WEIGHTS = {"owasp": 0.40, "iam": 0.30, "secrets": 0.20, "deps": 0.10}

def normalise_security_score(findings):
    cat_scores = {}
    for cat, counts in findings.items():
        penalty = sum(SECURITY_PENALTIES.get(sev, 0) * n for sev, n in counts.items())
        cat_scores[cat] = max(0.0, 1.0 - penalty)
    if not cat_scores: return 1.0
    total_w = sum(SECURITY_CAT_WEIGHTS.get(c, 0) for c in cat_scores)
    if total_w == 0: return sum(cat_scores.values()) / len(cat_scores)
    return sum(SECURITY_CAT_WEIGHTS.get(c, 0) * s for c, s in cat_scores.items()) / total_w

def complexity_weight(nodes, edges, tokens, downstream, tier_w):
    aeg = min((nodes/20 + edges/40) / 2, 1.0)
    tok = min(tokens / 200_000, 1.0)
    ds  = min(downstream / 8, 1.0)
    return max(0.1, min((aeg + tok + tier_w + ds) / 4, 1.0))


# ── Tests ─────────────────────────────────────────────────────────────────────

print("\n── Metric weights ───────────────────────────────────────────")
check("weights sum to 1.0",
      abs(sum(METRIC_WEIGHTS.values()) - 1.0) < 1e-9)
check("no healer_intervention_depth",
      "healer_intervention_depth" not in METRIC_WEIGHTS)
check("no task_success_rate",
      "task_success_rate" not in METRIC_WEIGHTS)
check("no time_to_completion",
      "time_to_completion" not in METRIC_WEIGHTS)
check("pre_healer_test_pass_rate = 0.20",
      METRIC_WEIGHTS["pre_healer_test_pass_rate"] == 0.20)
check("security_compliance_score = 0.20",
      METRIC_WEIGHTS["security_compliance_score"] == 0.20)
check("contract_fidelity = 0.25",
      METRIC_WEIGHTS["contract_fidelity"] == 0.25)
check("downstream_satisfaction = 0.25",
      METRIC_WEIGHTS["downstream_satisfaction"] == 0.25)

print("\n── Composite score ──────────────────────────────────────────")
check("perfect input → 1.0",
      abs(score(1,1,1,1,1) - 1.0) < 1e-9)
check("zero input → 0.0",
      abs(score(0,0,0,0,0) - 0.0) < 1e-9)
check("only security=1 → 0.20",
      abs(score(0,0,0,1,0) - 0.20) < 1e-9)
check("only pre_healer=1 → 0.20",
      abs(score(0,0,1,0,0) - 0.20) < 1e-9)
check("only contract=1 → 0.25",
      abs(score(1,0,0,0,0) - 0.25) < 1e-9)
check("only downstream=1 → 0.25",
      abs(score(0,1,0,0,0) - 0.25) < 1e-9)
check("only token=1 → 0.10",
      abs(score(0,0,0,0,1) - 0.10) < 1e-9)

print("\n── EMA alpha ────────────────────────────────────────────────")
check("new agent alpha > 0.55",       compute_alpha(0.0) > 0.55)
check("established agent alpha < 0.10", compute_alpha(100.0) < 0.10)
a_vals = [compute_alpha(float(n)) for n in range(0, 100, 5)]
check("alpha monotone decreasing",    all(a >= b for a, b in zip(a_vals, a_vals[1:])))
check("alpha never below floor",       all(a >= ALPHA_FLOOR for a in a_vals))
check("alpha never above ceil",        all(a <= ALPHA_CEIL  for a in a_vals))

print("\n── EMA update ───────────────────────────────────────────────")
old = 0.5
new = _ema(old, 1.0, 0.6)
check("good engagement raises score",  new > old, f"new={new:.4f}")
new_bad = _ema(0.8, 0.0, 0.6)
check("bad engagement lowers score",   new_bad < 0.8, f"new={new_bad:.4f}")
check("score clamped to [0,1]",        0.0 <= _ema(0.99, 1.0, 0.8) <= 1.0)
check("low complexity moves less",
      _ema(0.5, 1.0, compute_alpha(30)*0.1) < _ema(0.5, 1.0, compute_alpha(30)*1.0))

print("\n── normalise_test_pass_rate ─────────────────────────────────")
check("100/100 = 1.0",   normalise_test_pass_rate(100, 100) == 1.0)
check("0/100 = 0.0",     normalise_test_pass_rate(0, 100)   == 0.0)
check("75/100 = 0.75",   abs(normalise_test_pass_rate(75, 100) - 0.75) < 1e-9)
check("0/0 = 1.0 (no tests)", normalise_test_pass_rate(0, 0) == 1.0)
check("result always in [0,1]",
      all(0 <= normalise_test_pass_rate(p, 100) <= 1 for p in range(0, 105, 5)))

print("\n── normalise_downstream_satisfaction ────────────────────────")
check("0 corrections = 1.0",  normalise_downstream_satisfaction(0) == 1.0)
check("1 correction = 0.8",   abs(normalise_downstream_satisfaction(1) - 0.8) < 1e-9)
check("5 corrections = 0.0",  normalise_downstream_satisfaction(5) == 0.0)
check("6 corrections = 0.0 (floor)", normalise_downstream_satisfaction(6) == 0.0)

print("\n── normalise_security_score ─────────────────────────────────")
clean = {"owasp": {"critical":0,"high":0,"medium":0,"low":0},
         "iam":   {"critical":0,"high":0,"medium":0,"low":0},
         "secrets": {"critical":0}, "deps": {"critical":0}}
check("zero findings = 1.0",
      normalise_security_score(clean) == 1.0)
check("critical owasp finding < 1.0",
      normalise_security_score({"owasp": {"critical":1}}) < 1.0)
check("4 critical findings = 0.0",
      normalise_security_score({"owasp": {"critical":4}}) == 0.0)
check("medium finding slightly reduces",
      0.9 < normalise_security_score({"owasp": {"critical":0,"high":0,"medium":1,"low":0}}) < 1.0)
check("empty findings = 1.0",
      normalise_security_score({}) == 1.0)

print("\n── normalise_token_efficiency ───────────────────────────────")
baseline = 1/50
score_at_baseline = normalise_token_efficiency(1.0, int(1.0/baseline), "backend_engineer")
check("at baseline → ~0.5",  abs(score_at_baseline - 0.5) < 0.02, f"got {score_at_baseline:.4f}")
check("2× baseline → > 0.9", normalise_token_efficiency(2.0, int(1.0/baseline), "backend_engineer") > 0.9)
check("0.5× baseline → < 0.2", normalise_token_efficiency(0.5, int(1.0/baseline), "backend_engineer") < 0.2)
check("zero tokens → 0.0",   normalise_token_efficiency(1.0, 0, "backend_engineer") == 0.0)
check("unknown role uses default", 0.0 <= normalise_token_efficiency(1.0, 75, "wizard_agent") <= 1.0)

print("\n── complexity_weight ────────────────────────────────────────")
w_trivial  = complexity_weight(2,  1,  3_000,   0, 0.20)  # PHI4 doc task
w_complex  = complexity_weight(18, 35, 195_000, 7, 1.00)  # GPT4O_O1 arch task
check("trivial build weight < 0.3",  w_trivial < 0.3,  f"got {w_trivial:.3f}")
check("complex build weight > 0.8",  w_complex > 0.8,  f"got {w_complex:.3f}")
check("weight always >= 0.1",        all(
    complexity_weight(n, n//2, n*1000, 1, t) >= 0.1
    for n in [2,5,10,20] for t in [0.2, 0.5, 0.8, 1.0]
))
check("weight always <= 1.0",        all(
    complexity_weight(n, n, n*10000, 8, t) <= 1.0
    for n in [2,5,10,20] for t in [0.2, 0.5, 0.8, 1.0]
))

# ── Summary ───────────────────────────────────────────────────────────────────
total = len(PASS) + len(FAIL)
print(f"\n{'─'*52}")
print(f"  {len(PASS)}/{total} passed", end="")
if FAIL:
    print(f"   {len(FAIL)} failed: {', '.join(FAIL)}")
    sys.exit(1)
else:
    print("  — all good")
    sys.exit(0)