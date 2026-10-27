# Issue tracker

For ticket implementation or spec review, use GitHub repository `Versionfm/agent-eval-harness`.

Read an issue with `gh issue view NUMBER --repo Versionfm/agent-eval-harness --json title,body,state`.
The first milestone is parent #1, tickets #2–8. `docs/TICKETS.md` records dependencies; GitHub is authoritative for status. `docs/SPEC.md` preserves the published specification.

Work lands through one pull request targeting `main`, with `Closes #1` and each completed ticket in its body. Keep it draft during implementation, then mark ready after verification and review. Issues close when that PR merges. Merging requires separate user authorization.
