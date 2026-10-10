# Learning and implementation sequence

Status: active. Slice 1 is complete and admitted; inspect its task manifest, three-run evidence, and HTML summary before moving to slice 2. Each slice includes a short explanation, an experiment the user can run, and an inspection checkpoint before expansion.

| Slice | Build and observe | Completion evidence |
| --- | --- | --- |
| 1. Task and independent checks | Read the retrieval call chain, pin ML Tutor, create one defect and evaluator-owned checks. | **Complete:** baseline and repair pass all nine checks; defect fails title retrieval, tutor context, and input-order independence in Docker. |
| 2. Tools and trace | Run repository tools in a disposable container and capture successful, failed, and truncated results. | Commands begin in the repo; outputs/errors are traceable; evaluator files and credentials are absent. |
| 3. Explicit Python loop | Follow model → tool → model transitions with scripted responses, then a small DeepSeek smoke call. | Understand state, dispatch, stopping, retries, and provider reasoning preservation. |
| 4. Independent verdict and report | Evaluate a proposed patch in a fresh environment and inspect clean HTML. | Both a correct patch and incorrect patch receive meaningful results; partial attempts remain inspectable. |
| 5. LangGraph counterpart | Express the same model/tool functions as nodes with state updates and conditional edges. | Scripted parity checks pass; explain which responsibilities LangGraph supplies and which remain ours. |
| 6. First live comparison | Run both orchestrators on the admitted task with matched configuration. | Reproducible manifests, traces, diffs, verdicts, usage, and side-by-side report; review outcomes with the user. |
| 7. Controlled harness experiments | Change one context/recovery/persistence choice at a time. | Explain behavior changes using traces and measurements on fixed tasks/models. |
| 8. Broader benchmarks | Add tasks/repeats, Qwen, a local model after measured feasibility, and another repository. | Compare harness variants separately from model variants and report cost per successful task when enough observations exist. |

The first milestone ends after slice 6. An agent need not solve the task for the milestone to succeed, but the harness and evaluator must be demonstrated trustworthy. Slices 7–8 extend the same architecture.

Preflight facts to verify before live work: usable Docker runtime, pinned ML Tutor tests, DeepSeek account access, tool-call round trip, and latency/usage recording. API key setup happens privately; the task container never receives it.
