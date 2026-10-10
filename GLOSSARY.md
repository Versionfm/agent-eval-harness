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
