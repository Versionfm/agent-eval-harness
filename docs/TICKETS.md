# First milestone tickets

Approved breakdown published to GitHub with the `ready-for-agent` label and native blocking dependencies. [Parent specification #1](https://github.com/Versionfm/agent-eval-harness/issues/1) remains unchanged. GitHub issues are authoritative for ticket status.

| Ticket | Deliverable | Blocked by |
| --- | --- | --- |
| [#2](https://github.com/Versionfm/agent-eval-harness/issues/2) | Admit a reproducible ML Tutor retrieval task | None |
| [#3](https://github.com/Versionfm/agent-eval-harness/issues/3) | Run a scripted repair through the complete attempt pipeline | #2 |
| [#4](https://github.com/Versionfm/agent-eval-harness/issues/4) | Preserve and explain failed or budget-limited attempts | #3 |
| [#5](https://github.com/Versionfm/agent-eval-harness/issues/5) | Run and measure a direct DeepSeek repair attempt | #4 |
| [#6](https://github.com/Versionfm/agent-eval-harness/issues/6) | Demonstrate LangGraph orchestration parity | #4 |
| [#7](https://github.com/Versionfm/agent-eval-harness/issues/7) | Inspect clean side-by-side attempt reports and separate review | #5, #6 |
| [#8](https://github.com/Versionfm/agent-eval-harness/issues/8) | Complete the first matched live harness comparison | #7 |

Start with #2. Once #4 completes, #5 and #6 can proceed independently. Each ticket includes executable acceptance criteria, a runnable experiment, and a user learning checkpoint. Implementation has not started as part of ticket publication.
