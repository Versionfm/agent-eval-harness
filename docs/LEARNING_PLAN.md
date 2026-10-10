# Learning and implementation sequence

Status: active. Slices 1–5 have deterministic implementations and inspectable evidence; the matched live-model comparison is still pending provider preflight and review. Each slice includes a short explanation, an experiment the user can run, and an inspection checkpoint before expansion.

| Slice | Build and observe | Completion evidence |
| --- | --- | --- |
| 1. Task and independent checks | Read the retrieval call chain, pin ML Tutor, create one defect and evaluator-owned checks. | **Complete:** baseline and repair pass all nine checks; defect fails title retrieval, tutor context, and input-order independence in Docker. |
| 2. Tools and trace | Run repository tools in a disposable container and capture successful, failed, truncated, and timed-out results. | **Complete:** ordered tool events expose errors; full output files remain alongside model-visible truncation. |
| 3. Explicit Python loop | Follow model → tool → model transitions with scripted responses, then a small DeepSeek smoke call. | **Scripted path complete:** state, dispatch, request accounting, deadlines, retries, and provider-field preservation have offline coverage; live smoke remains for ticket #5. |
| 4. Independent verdict and report | Evaluate a proposed patch in a fresh environment and inspect clean HTML. | **Complete:** correct, incorrect, invalid, environment-failed, interrupted, and budget-stopped attempts keep separate outcomes and artifacts. |
| 5. LangGraph counterpart | Express the same model/tool functions as nodes with state updates and conditional edges. | **Scripted parity complete:** actual task/evaluator Docker runs compare correct repair, error recovery plus common request-budget stop, reasoning-field continuation, and a separately configured graph-step stop. The runnable checkpoint writes paired reports and `comparison.json`; no paid live call is used. |
| 6. First live comparison | Run `python -m agent_eval_harness.run_matched_comparison` after admission and scripted parity pass. | **Coordinator complete; live evidence pending:** the provider smoke gates both attempts, one shared ledger covers smoke and both per-attempt ceilings, each orchestrator gets a fresh defect baseline, and the renderer compares retained artifacts. The live command still needs the private credential-file path; inspect actual traces and independent checks before recording a separate review. See [the reproduction and walkthrough](MATCHED_RUN.md). |
| 7. Controlled harness experiments | Change one context/recovery/persistence choice at a time. | Explain behavior changes using traces and measurements on fixed tasks/models. |
| 8. Broader benchmarks | Add tasks/repeats, Qwen, a local model after measured feasibility, and another repository. | Compare harness variants separately from model variants and report cost per successful task when enough observations exist. |

The first milestone ends after slice 6. An agent need not solve the task for the milestone to succeed, but the harness and evaluator must be demonstrated trustworthy. Slices 7–8 extend the same architecture.

For the failure/recovery learning checkpoint, run `python3 -m agent_eval_harness.run_failure_recovery` as documented in the README. The intended observation is a tool error followed by recovery, then `model_call_budget` with a collected patch that passes canonical checks. Inspect the `trace.jsonl`, full-output artifact, candidate patch, and report before continuing.

Preflight facts to verify before live work: usable Docker runtime, pinned ML Tutor tests, DeepSeek account access, tool-call round trip, and latency/usage recording. API key setup happens privately; the task container never receives it.
