# Design interview

## Confirmed

- Create a private GitHub repository for the harness project.
- Build a personal portfolio and research project, with learning harness engineering as an explicit goal.
- Evaluate bug repair on a small fixed task set, capturing diagnosis in the trace.
- Select another benchmark repository; the algo trading repository is excluded by the user.
- Give the agent full access to its task repository, comparable to repository access in Codex and Claude. Host access, credentials, external services, and evaluator boundaries have not been decided.
- Allow substantial learning time rather than imposing the proposed two-week deadline.
- Explore several inexpensive hosted models and local models on the user's 16 GB GPU. Model choices, spending limits, and verified local feasibility remain open.
- Stress-test the design through numbered decision rounds and document decisions as they are confirmed.
- Learn and build both the coding-agent harness and an independent evaluation system.
- Prefer small, understandable open-source repositories with introduced behavioral bugs; the user's existing apps are also candidates. Minimize time spent learning benchmark codebases.
- Keep canonical acceptance checks outside the agent's writable task copy. The agent delivers its observable reasoning, tool activity, and code diff for evaluator review.
- Use Codex as an evaluator/reviewer; the respective roles of executable checks and qualitative review still need clarification.
- First milestone: one reproducible repair attempt with trace, diff, independent verdict, elapsed time, and usage measurements. It must exercise a design that can support harder tasks.
- Build an explicit Python agent loop and a side-by-side LangGraph implementation for learning what the framework handles.
- Teach through incremental slices, with explanations, observable experiments, and user inspection before expansion.
- Executable acceptance checks determine functional success; Codex separately reviews diagnosis, tool use, patch quality, and failure cases.
- Produce reports of exposed reasoning summaries and tool calls, alongside patches and outcomes.
- Compare harness composition and behavior first with fixed tasks and models; model comparisons follow under a fixed harness.
- Use the user's ML Tutor (`Versionfm/prompt-engineering-group-project`) as the first task repository, with introduced behavioral bugs. Click is the intended second repository later.
- Share task inputs, prompts, model interface, tools, state definitions, budgets, and evaluation between the Python loop and LangGraph. Initially vary orchestration only; explain each LangGraph component's role.
- First task family: retrieval selection, with a source-validated behavioral defect and regression checks.
- Tools: file reading, text search, patch editing, and shell execution, with arguments, results, duration, and errors recorded.
- Shell commands start in the task repository within a disposable container. Canonical checks run in a fresh evaluator environment outside the agent's control.
- Reports: machine-readable traces plus clean, legible local HTML with event timeline, exposed reasoning summaries, tool results, code diff, acceptance results, and separate evaluator review. Compare implementations side by side.
- Connect one inexpensive hosted model first through a replaceable adapter, then add a local model.
- Initial context: task description, repository instructions, and a short file map; source discovery happens through tools.
- Stop on agent-declared completion or hard limits on turns, elapsed time, and tool-output size. Preserve partial traces and patches. Calibrate numeric limits with a smoke run.
- Milestone acceptance requires baseline-pass, defect-fail, known-repair-pass evidence and comparable traces/reports from both implementations. Agent failure is a valid measured outcome.

## Decision tree

Round 1 establishes independent roots:

1. Primary purpose and intended user.
2. Coding-task scope for the initial project.
3. Maximum execution authority during an evaluation.
4. Time and spending budget for the first milestone.

Once these roots are settled, subsequent rounds can decide task selection, evaluator access, scoring, reproducibility, agent integration, comparisons, reporting, and milestone acceptance.

## Round 1 — answered

1. Purpose: personal portfolio/research tool, reusable developer tool, or product for other users?
   Recommendation: personal portfolio/research tool with evidence others can reproduce.
2. Task scope: bug diagnosis, bug repair, feature implementation, or a mixture?
   Recommendation: bug repair, with diagnosis captured in the trace, using a small fixed task set.
3. Execution authority: offline sandbox, network-enabled sandbox, or access to external services?
   Recommendation: isolated repository copies with local commands; external service access simulated where practical; trading and publication excluded.
4. Budget: how much time and paid model usage should the first milestone consume?
   Recommendation: two weeks of part-time work and a user-confirmed hard spending cap.

The user's answers supersede the recommendations above. No implementation stack or evaluation architecture has been selected.

## Round 2 — answered

5. Learning scope: build the coding-agent runtime, its evaluation system, or both?
   Recommendation: both, beginning with one small tool-using agent and a separate evaluator.
6. Repository selection: use a curated existing open-source Python repository or create a purpose-built application with seeded faults?
   Recommendation: start with a modest, well-tested Python open-source repository and carefully introduced behavioral bugs, then add historical bugs later.
7. Repository access boundary: does full task-repository access coexist with evaluator-owned acceptance checks outside the agent's workspace?
   Recommendation: full read/write/command access to the task copy; keep canonical acceptance checks and scoring outside it.
8. First learning milestone: what concrete result should demonstrate useful progress?
   Recommendation: one reproducible bug-repair attempt with a saved tool trace, code diff, independent verdict, and latency/usage measurements.

The user's answers confirm both learning tracks, familiar and understandable task repositories, independent evaluation, and the milestone above. Cheap hosted and local models remain part of the intended benchmark scope.

## Round 3 — answered

9. Agent construction: transparent custom loop or a framework-managed agent?
   Recommendation: a small Python tool loop with explicit model calls, tool dispatch, context management, and termination; keep provider integration replaceable.
10. Learning process: complete implementation followed by explanation, or incremental slices the user inspects and runs?
   Recommendation: incremental slices, each accompanied by an architecture explanation, observable experiment, and review checkpoint.
11. Evaluation authority: executable acceptance checks, qualitative Codex review, or a combination?
   Recommendation: executable checks determine functional success; Codex reviews diagnosis, trace, patch quality, and failure cases as separate judgments.
12. Comparison goal: measure model differences first or improvements to harness behavior first?
   Recommendation: keep tasks and model fixed while testing harness changes first; then compare models under a fixed harness.

13. First task repository: the user's prompt-engineering-group-project or a small external library such as Click?
   Recommendation: prompt-engineering-group-project, using offline retrieval/citation/history behavior; reserve Click for a second repository.

## Repository candidate facts

Read-only GitHub inspection found:

- `Versionfm/prompt-engineering-group-project`: four functional app modules and nine unit-test modules. README describes API-key-free unit tests; inspected tutor/source tests use fake chat and synthetic section fixtures. Candidate offline behaviors include retrieval selection, citation matching, history propagation, and evaluation parsing. Recommended familiar starting point, subject to a pinned revision and reproduced baseline tests.
- `Versionfm/bank-statement-assistant`: richer test coverage, but the complete app requires PostgreSQL, workers, model serving, and frontend setup. Isolated parser/validation/reporting tasks could be offline but require carefully bounded synthetic fixtures.
- `Versionfm/vibecoders-p1`: minimal prompt CLI and an empty tests directory; building task acceptance infrastructure would dominate the initial benchmark work.
- `pallets/click`: compact Python CLI library with no declared runtime dependencies in current project metadata; useful independent second repository.

No candidate has been cloned or executed during this interview. Counts describe inspected files, not test cases. Specific task and scoring decisions will follow repository selection.

## Round 4 — answered

14. Comparison boundary: should the explicit loop and LangGraph share tools, task inputs, model interface, state meaning, budgets, and evaluation?
   Recommendation: yes; vary orchestration first and introduce framework-specific capabilities as later experiments.
15. First task family: retrieval, citation matching, or conversation history?
   Recommendation: retrieval selection, with a nontrivial behavioral defect and independent acceptance checks. Task specifics require source inspection.
16. Initial tool surface: a general shell alone or named repository tools plus a shell?
   Recommendation: file reading, text search, patch editing, and shell execution, each producing structured trace events.
17. Initial report form: raw trace only, Markdown, or navigable HTML?
   Recommendation: machine-readable trace plus a local HTML report linking timeline events, tool results, diff, checks, and separate evaluator judgments.
18. Execution environment: isolated task directory or a container boundary?
   Recommendation: disposable container with a writable task repository, prepared dependencies, and evaluator execution outside the agent's control.

The user has confirmed the direction but not a complete implementation design. Continue the interview until remaining branches are resolved and shared understanding is explicitly confirmed.

## Round 5 — answered

19. First model integration: one hosted model, one local model, or both immediately?
   Recommendation: begin with one inexpensive hosted model behind a replaceable adapter, then validate a local model before comparisons. Exact models require current availability and hardware checks.
20. What repository context should the agent receive initially?
   Recommendation: task description, repository instructions, and a short file map; let the agent inspect relevant source through tools rather than preload the whole repository.
21. How should an attempt stop?
   Recommendation: agent-declared completion plus hard limits on model turns, wall time, and output/tool-result size; preserve partial artifacts on failure. Specific limits should be calibrated by a smoke run.
22. What must happen before implementation is considered complete for the first milestone?
   Recommendation: prove the clean baseline passes, the introduced defect fails independent checks, a known repair passes, and both harnesses produce comparable traces and reports; an agent failure remains a valid measured outcome.

Detailed context management, provider access, task packaging, and execution policies will follow these answers. Implementation remains pending final confirmation of shared understanding.

## Hosted model proposal — not yet confirmed

Official OpenAI documentation checked on 2026-10-10 supports `gpt-5.4-mini` as an initial candidate: coding-oriented positioning, function calling, structured outputs, and a documented snapshot `gpt-5.4-mini-2026-03-17`. Standard text pricing is USD 0.75 per million input tokens, USD 0.075 per million cached input tokens, and USD 4.50 per million output tokens. A hypothetical attempt totaling 100,000 uncached input tokens and 10,000 billed output tokens costs USD 0.12 at those rates; this is illustrative, not a predicted attempt cost.

Source: https://developers.openai.com/api/docs/models/gpt-5.4-mini

Account access, live tool-call reliability, usage, and latency have not been verified. Model selection remains a proposal until the user confirms it.

## Round 6 — awaiting answers

23. Initial hosted model: accept the proposed GPT-5.4 mini snapshot?
   Recommendation: yes, with low reasoning effort initially and the same settings in both orchestrators. Record every setting in attempt metadata.
24. Context overflow policy: stop at the context budget or compact and continue?
   Recommendation: first stop explicitly with preserved artifacts; introduce traceable context compaction as a later controlled harness experiment.
25. Network boundary: should the task container have internet access?
   Recommendation: prepare dependencies before the run, disable task-container networking, and make model requests from the outer harness. Keep API credentials outside the task container.
26. Error recovery policy: silently retry, expose every failure to the agent, or distinguish provider errors from tool errors?
   Recommendation: bounded, logged retries for transient provider failures; return tool errors to the agent as structured results. Record all failed requests and retries in usage/trace data when available.
