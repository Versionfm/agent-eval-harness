# Use separate disposable task and evaluator environments

Run each coding-agent attempt in a disposable container with a writable task repository and prepared dependencies. Shell commands start in that repository. Run canonical acceptance checks in a fresh evaluator environment outside the agent's control, applying the proposed patch to a clean task baseline. This introduces container setup work in exchange for repeatable execution and an evaluation verdict the agent cannot redefine by editing its local checks.
