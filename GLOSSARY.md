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
