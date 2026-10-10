# Live tracker implementation tickets

Status: user-approved breakdown, published and verified. Parent: [specification #10](https://github.com/Versionfm/agent-eval-harness/issues/10). All eight child issues are open with `ready-for-agent`; 12 native blocking relationships match the approved plan. Parent content, state, labels, assignments, milestone, comments and sub-issue summary were verified unchanged.

| Slice | Published ticket | Blocked by |
| --- | --- | --- |
| T1 | [#11 — Follow one scripted Python attempt in the browser](https://github.com/Versionfm/agent-eval-harness/issues/11) | None |
| T2 | [#12 — Inspect interrupted attempts and stop safely on recording failure](https://github.com/Versionfm/agent-eval-harness/issues/12) | [#11](https://github.com/Versionfm/agent-eval-harness/issues/11) |
| T3 | [#13 — Inspect Python phases, model calls and tool evidence in the workbench](https://github.com/Versionfm/agent-eval-harness/issues/13) | [#11](https://github.com/Versionfm/agent-eval-harness/issues/11) |
| T4 | [#14 — Play back new and legacy attempts with matching report evidence](https://github.com/Versionfm/agent-eval-harness/issues/14) | [#12](https://github.com/Versionfm/agent-eval-harness/issues/12), [#13](https://github.com/Versionfm/agent-eval-harness/issues/13) |
| T5 | [#15 — Follow actual LangGraph nodes through the same workbench](https://github.com/Versionfm/agent-eval-harness/issues/15) | [#13](https://github.com/Versionfm/agent-eval-harness/issues/13) |
| T6 | [#16 — Inspect repository changes after successful and failed tools](https://github.com/Versionfm/agent-eval-harness/issues/16) | [#12](https://github.com/Versionfm/agent-eval-harness/issues/12), [#13](https://github.com/Versionfm/agent-eval-harness/issues/13) |
| T7 | [#17 — Reconnect and catch up without slowing the attempt](https://github.com/Versionfm/agent-eval-harness/issues/17) | [#11](https://github.com/Versionfm/agent-eval-harness/issues/11) |
| T8 | [#18 — Demonstrate both trackers under the ten-cent shared ceiling](https://github.com/Versionfm/agent-eval-harness/issues/18) | [#14](https://github.com/Versionfm/agent-eval-harness/issues/14), [#15](https://github.com/Versionfm/agent-eval-harness/issues/15), [#16](https://github.com/Versionfm/agent-eval-harness/issues/16), [#17](https://github.com/Versionfm/agent-eval-harness/issues/17) |

## Execution frontier

T1 ([#11](https://github.com/Versionfm/agent-eval-harness/issues/11)) is the initial frontier on a base containing the existing harness implementation. After it completes, T2 (#12), T3 (#13) and T7 (#17) can proceed independently. Later blockers are recorded natively on GitHub and explicitly in each issue body.

The original harness PR is not merged by this publication. No implementation has started and no paid provider calls have run. When implementation is authorized, use one Luna subagent with xhigh effort per ticket and retain root orchestration/integration review. The demonstration retains the combined USD 0.10 estimated ceiling.

The [approved proposal](TICKET_PROPOSAL.md) preserves the original slice descriptions and acceptance criteria. GitHub issue bodies contain resolved real issue references.
