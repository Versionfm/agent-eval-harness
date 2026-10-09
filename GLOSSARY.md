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
