# Coding Agent Evaluation

Language for evaluating coding agents on repository bug-repair tasks.

## Language

**Bug-repair task**:
A coding task whose desired outcome is a code change that corrects specified faulty behavior.
_Avoid_: Diagnosis task, feature task

**Diagnosis**:
The agent's account of the cause of the faulty behavior. A diagnosis alone does not complete a bug-repair task.
_Avoid_: Repair, solution

**Task repository**:
The codebase given to the agent as the working environment for a bug-repair task.
_Avoid_: Harness repository

**Agent harness**:
The environment and control process through which a model acts on a coding task, including its tools, context, and execution lifecycle.
_Avoid_: Evaluation system

**Evaluation system**:
The independent process that assesses an agent's task attempt using its outcome and recorded activity.
_Avoid_: Agent harness

**Acceptance checks**:
Evaluator-controlled checks of whether a proposed repair satisfies the task's required behavior.
_Avoid_: Agent-written tests

**Attempt trace**:
The recorded observable activity of a task attempt, including available model responses, tool calls, tool results, and execution events. Reasoning summaries may be included; hidden model reasoning is not assumed available.
_Avoid_: Complete internal thinking

**Attempt**:
One execution of a coding agent against a specific task and starting repository state.
_Avoid_: Benchmark, experiment

**Functional verdict**:
The evaluator's result for a proposed repair against the task's acceptance checks.
_Avoid_: Agent completion

**Canonical check failure**:
A collected candidate patch was evaluated and one or more evaluator-controlled acceptance checks failed.
_Avoid_: Invalid patch

**Invalid patch**:
Candidate changes could not be safely collected or applied to the evaluator's starting repository state.
_Avoid_: Canonical check failure, invalid environment

**Invalid environment**:
The evaluation system could not produce valid acceptance-check results because its prepared environment or evaluator failed.
_Avoid_: Repair failure, invalid patch

**Termination reason**:
The recorded condition that ended an agent attempt, independently of whether its proposed repair works.
_Avoid_: Functional verdict

**Live viewer**:
An observational interface presenting available activity from an attempt that is currently executing.
_Avoid_: Agent controller, execution engine

**Recorded playback**:
A presentation of saved attempt evidence in its recorded order. Playback does not execute tools, invoke a model or resume the attempt.
_Avoid_: Agent resume, task rerun, deterministic execution replay

**Attempt event log**:
The ordered history of recorded observable events belonging to one attempt, shared by live inspection, recorded playback and reporting.
_Avoid_: UI-only history, execution checkpoint

**Intermediate candidate diff**:
The observed repository changes relative to an attempt's starting state at a recorded point before its final candidate is collected.
_Avoid_: Final candidate patch, continuous filesystem history

**Incomplete recording**:
Attempt evidence missing required records or artifacts under its recording contract. Incompleteness is separate from the attempt's termination reason and any independently established functional verdict.
_Avoid_: Agent repair failure, successful completion

**Attempt operation**:
One identifiable action within an attempt, such as a model request or tool invocation, whose recorded start and outcome belong together. A recorded start without an outcome leaves the operation unresolved in the available evidence.
_Avoid_: Completed action, whole attempt

**Recorded attempt state**:
The attempt information supported by recorded evidence at a selected point in its history. It is distinct from final totals or results that became available later.
_Avoid_: Final summary, inferred internal model state
