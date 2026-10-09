# Agent Eval Harness

A project for learning harness engineering and evaluating coding agents on realistic bug-repair tasks. The benchmark repository is still to be selected; the algo trading repository has been ruled out.

## Status

Design interview in progress. There is no harness implementation or verified benchmark result yet.

The project is a personal portfolio and research tool intended to produce reproducible evidence. It will build both a coding-agent harness and its evaluation system, evaluate bug repair while capturing diagnosis, and explore inexpensive hosted models and local models on a 16 GB GPU. The agent will have full access to its task repository, while canonical acceptance checks remain outside that writable copy.

The first milestone is one reproducible repair attempt with a tool trace, code diff, independent verdict, elapsed time, and model usage. It should exercise the same path used for later, harder tasks. Framework choice, review criteria, model integration, and the benchmark repository remain under discussion.

See [the design interview](docs/design-interview.md) for confirmed scope and open questions.
