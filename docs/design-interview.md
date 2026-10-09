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

## Round 2 — awaiting answers

5. Learning scope: build the coding-agent runtime, its evaluation system, or both?
   Recommendation: both, beginning with one small tool-using agent and a separate evaluator.
6. Repository selection: use a curated existing open-source Python repository or create a purpose-built application with seeded faults?
   Recommendation: use a modest existing Python repository with meaningful tests; candidate facts are being researched.
7. Repository access boundary: does full task-repository access coexist with evaluator-owned acceptance checks outside the agent's workspace?
   Recommendation: full read/write/command access to the task copy; keep canonical acceptance checks and scoring outside it.
8. First learning milestone: what concrete result should demonstrate useful progress?
   Recommendation: one reproducible bug-repair attempt with a saved tool trace, code diff, independent verdict, and latency/usage measurements.

Recommendations remain proposals until confirmed. Subsequent decisions depend on these answers.
