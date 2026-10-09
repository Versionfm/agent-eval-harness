# Keep acceptance checks outside the agent's writable repository

The coding agent receives full read/write and command access to its task repository, including its ordinary tests. Canonical acceptance checks remain controlled by the evaluation system outside that writable copy, so changing task tests cannot redefine a successful repair. This preserves a realistic coding workflow while requiring separate evaluator setup and execution.
