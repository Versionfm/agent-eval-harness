# Design interview

## Confirmed

- Create a private GitHub repository for the harness project.
- Explore a coding-agent evaluation harness, with the algo trading repository as the initial candidate environment.
- Stress-test the design through numbered decision rounds and document decisions as they are confirmed.

## Decision tree

Round 1 establishes independent roots:

1. Primary purpose and intended user.
2. Coding-task scope for the initial project.
3. Maximum execution authority during an evaluation.
4. Time and spending budget for the first milestone.

Once these roots are settled, subsequent rounds can decide task selection, evaluator access, scoring, reproducibility, agent integration, comparisons, reporting, and milestone acceptance.

## Round 1 — awaiting answers

1. Purpose: personal portfolio/research tool, reusable developer tool, or product for other users?
   Recommendation: personal portfolio/research tool with evidence others can reproduce.
2. Task scope: bug diagnosis, bug repair, feature implementation, or a mixture?
   Recommendation: bug repair, with diagnosis captured in the trace, using a small fixed task set.
3. Execution authority: offline sandbox, network-enabled sandbox, or access to external services?
   Recommendation: isolated repository copies with local commands; external service access simulated where practical; trading and publication excluded.
4. Budget: how much time and paid model usage should the first milestone consume?
   Recommendation: two weeks of part-time work and a user-confirmed hard spending cap.

Recommendations remain proposals until confirmed. No implementation decisions have been accepted yet.
