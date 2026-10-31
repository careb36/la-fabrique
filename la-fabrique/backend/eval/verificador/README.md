# Verifier benchmark

The product's central claim is that it verifies what a producer says it did.
This directory measures that claim instead of asserting it.

```bash
cd backend && PYTHONPATH=.:app poetry run python -m eval.verificador.run
```

```
lies not believed:  12/12
cases as specified: 14/14
stored:             14 verification(s), one audit row each
```

## How it works

`cases.py` holds each scenario as data: what the producer claims, and the
independent evidence the workspace daemon reports. `run.py` feeds every case to
the real `services.verification.verify_agent_run` against an in-memory SQLite
session, so the aggregation, the stored `Verification` and the audit row are all
exercised. Nothing is mocked, no model is called, no network is used: the run is
deterministic and takes about a second.

## The two halves

A benchmark that only proves the verifier says no would score 100% by rejecting
everything. So the cases come in two kinds:

| Kind | What it asserts |
|---|---|
| `lie` | The evidence contradicts the claim, or cannot support it, and the run must come back `refuted` or `unverifiable` — never `verified` |
| `honest` | A delivery that matches its evidence must come back `verified` |

The `honest` cases are the control. If they start failing, the verifier has
become an obstacle rather than a check, and the `lie` number means nothing.

`unverifiable` counts as a rejection on purpose: it is a verdict of its own, not
a soft pass. A producer that says "tests pass" with no evidence to judge it has
not had its claim confirmed.

## What each case covers

| Case | Path it exercises |
|---|---|
| `tests_pass_but_they_failed` | `check_tests_run` on a non-zero exit |
| `tests_pass_but_the_run_was_killed` | `check_tests_run` on `timed_out` |
| `tests_pass_with_no_evidence_at_all` | `check_claimed_tests_evidenced` with no evidence |
| `build_is_green_but_ci_never_finished` | a CI conclusion of `None` |
| `tests_pass_and_the_daemon_never_ran_them` | a daemon that did not reply |
| `truncated_log_hides_the_failure` | `output_truncated`, so a cut tail is not read as the whole story |
| `file_declared_but_never_written` | `evaluate_workspace_writes` on a refused write |
| `file_written_with_different_content` | the sha256 the daemon read back |
| `file_declared_but_the_daemon_is_silent` | a file claim with no daemon report |
| `claimed_path_never_reached_the_artifact` | `check_claimed_files_present` |
| `empty_artifact_with_a_full_implementation_claim` | `check_artifact_nonempty` |
| `producer_cannot_lower_its_own_risk_tier` | `services/risk.py` monotonicity: the tier stays `high` |
| `honest_delivery_matching_its_evidence` | control |
| `honest_delivery_with_no_test_claims` | control |

## Adding a case

Add a `Case` to `CASES` with the claim, the evidence, and the verdicts you
accept. Give it its own `artifact_text` when it claims a path: a claimed path
missing from the artifact is refuted by `claimed_files_present` whatever the
later checks find, so a case that reuses the wrong artifact measures the wrong thing.

`tests/test_verificador_benchmark.py` runs this in the suite, so the reported
numbers are a gate rather than a screenshot.
