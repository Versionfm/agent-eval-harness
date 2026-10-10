# Agent Eval Harness

A project for learning harness engineering and evaluating coding agents on realistic bug-repair tasks. The benchmark repository is still to be selected; the algo trading repository has been ruled out.

## Status

Design interview in progress. There is no harness implementation or verified benchmark result yet.

The project is a personal portfolio and research tool intended to produce reproducible evidence. It will build both a coding-agent harness and its evaluation system, with an explicit Python loop and a side-by-side LangGraph implementation. It will evaluate bug repair while capturing diagnosis, and explore inexpensive hosted models and local models on a 16 GB GPU. The agent will have full access to its task repository, while canonical acceptance checks remain outside that writable copy.

The first milestone is one reproducible repair attempt on the user's ML Tutor repository, with a tool trace, code diff, independent verdict, elapsed time, and model usage. It should exercise the same path used for later, harder tasks. Acceptance checks determine functional success; Codex review provides separate qualitative judgments. Reports will expose available reasoning summaries and tool activity. Learning proceeds through incremental slices, comparing harness behavior before comparing models.

See [the design interview](docs/design-interview.md) for confirmed scope and open questions.

The proposed [implementation design](docs/DESIGN.md) and [learning sequence](docs/LEARNING_PLAN.md) are ready for the final shared-understanding check. Initial model: direct DeepSeek Flash with thinking enabled at low effort; Qwen is a later comparison.
