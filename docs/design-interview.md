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

## Round 3 — awaiting answers

9. Agent construction: transparent custom loop or a framework-managed agent?
   Recommendation: a small Python tool loop with explicit model calls, tool dispatch, context management, and termination; keep provider integration replaceable.
10. Learning process: complete implementation followed by explanation, or incremental slices the user inspects and runs?
   Recommendation: incremental slices, each accompanied by an architecture explanation, observable experiment, and review checkpoint.
11. Evaluation authority: executable acceptance checks, qualitative Codex review, or a combination?
   Recommendation: executable checks determine functional success; Codex reviews diagnosis, trace, patch quality, and failure cases as separate judgments.
12. Comparison goal: measure model differences first or improvements to harness behavior first?
   Recommendation: keep tasks and model fixed while testing harness changes first; then compare models under a fixed harness.

Repository selection awaits read-only inspection of the user's GitHub apps. Specific task and scoring decisions will follow the selections above.
