## Problem Statement

The user wants to learn both coding-agent harness engineering and independent evaluation through a project they can understand, inspect, and extend. Existing frameworks hide enough orchestration that using them alone would not explain how model calls, tools, context, state, recovery, and stopping interact. Conversely, building only a custom loop would not show what LangGraph supplies.

The user needs observable, comparable attempts on familiar code, with trustworthy correctness checks and clean reports. They want to understand harness composition before comparing inexpensive hosted and local models. An artificial demonstration that bypasses realistic repository operations, independent evaluation, or later extension would not meet that goal.

## Solution

Build a Python coding-agent harness and an independent evaluation system. Implement the same workflow twice: an explicit Python loop and a LangGraph state graph. Share task inputs, prompts, model adapter, tools, context policy, budgets, and evaluation, varying orchestration first.

Start with one introduced retrieval bug in the user's ML Tutor repository. Give the agent full access to a disposable task repository inside a container, with file reading, search, patch editing, and shell execution. Capture its observable activity and final patch. Evaluate that patch against canonical acceptance checks in a fresh environment outside the agent's control.

Use DeepSeek Flash through the direct DeepSeek API, with thinking enabled at low effort. Produce machine-readable attempt artifacts and a clean, legible HTML report, including side-by-side comparisons. Teach and implement through incremental slices, each with an explanation, an observable experiment, and a user inspection checkpoint.

## User Stories

1. As a learner, I want to see an explicit coding-agent loop, so that I understand how a model becomes an agent through tools and control flow.
2. As a learner, I want a LangGraph implementation beside the explicit loop, so that I can identify the responsibilities the framework handles.
3. As a learner, I want each LangGraph component mapped to its Python counterpart, so that state, nodes, edges, reducers, and execution have concrete meanings.
4. As a learner, I want implementation delivered in understandable slices, so that I can inspect and run each concept before expanding the system.
5. As a learner, I want experiments that expose success and failure, so that I can learn from actual behavior rather than explanations alone.
6. As a learner, I want tasks from a familiar, compact application, so that learning the benchmark repository does not dominate learning the harness.
7. As a task curator, I want a pinned repository revision, so that each attempt begins from the same source state.
8. As a task curator, I want a controlled behavioral defect, so that I know what the task measures.
9. As a task curator, I want clean-source, defective-source, and known-repair checks, so that I can establish task validity before scoring agents.
10. As a task curator, I want synthetic inputs and fake tutor model responses, so that task correctness is independent of external services and private data.
11. As a coding agent, I want a public description of symptoms and required behavior, so that I can investigate without receiving the solution.
12. As a coding agent, I want repository instructions and a short file map, so that I have enough orientation to begin source discovery.
13. As a coding agent, I want to read files, so that I can inspect the implementation and existing tests.
14. As a coding agent, I want to search repository text, so that I can locate relevant behavior efficiently.
15. As a coding agent, I want to apply patches, so that I can repair behavior and add useful tests.
16. As a coding agent, I want shell commands to start in the task repository, so that I can run its checks and development commands.
17. As a coding agent, I want full read/write access to my task copy, so that I can work through a realistic coding workflow.
18. As a coding agent, I want structured tool errors, so that I can adapt after unsuccessful actions.
19. As a learner, I want tool arguments, results, errors, and durations recorded, so that I can understand what the agent actually did.
20. As a learner, I want exposed reasoning and explanations recorded when available, so that I can review the agent's stated diagnosis and decisions.
21. As an experimenter, I want provider-specific conversation fields preserved, so that multi-turn thinking and tool calls remain valid in both orchestrators.
22. As an experimenter, I want the same tools and prompts in both implementations, so that comparisons isolate orchestration differences.
23. As an experimenter, I want identical model settings and budgets, so that one implementation does not receive an unintended advantage.
24. As an experimenter, I want scripted model responses, so that I can verify comparable behavior without live-model randomness.
25. As an experimenter, I want bounded, logged provider retries, so that transient failures remain visible and do not create indefinite execution.
26. As an experimenter, I want explicit stopping conditions, so that an unfinished attempt remains a measurable outcome.
27. As an experimenter, I want partial traces and patches preserved, so that budget stops and failures can still be investigated.
28. As an experimenter, I want tool-output truncation clearly marked, so that I know what information the model actually received.
29. As an evaluator, I want canonical acceptance checks outside agent access, so that editing task tests cannot redefine correctness.
30. As an evaluator, I want patches applied to a fresh defective baseline, so that evaluation does not inherit changes to the attempt environment.
31. As an evaluator, I want newly created repository files included in the candidate patch, so that a repair is evaluated completely.
32. As an evaluator, I want functional verdicts distinct from termination reasons, so that agent-declared completion is not mistaken for a successful repair.
33. As an evaluator, I want invalid environments distinguished from failed repairs, so that infrastructure problems do not become misleading quality scores.
34. As a reviewer, I want diagnosis, tool use, patch quality, and failure explanations reviewed separately from executable checks, so that qualitative feedback complements repeatable correctness results.
35. As a reviewer, I want a clearly pending review state, so that a report never invents a Codex judgment.
36. As a reader, I want a clean HTML summary of each attempt, so that its outcome is understandable before opening detailed logs.
37. As a reader, I want expandable long outputs and reasoning sections, so that the report remains legible while preserving detail.
38. As a reader, I want a timeline linked to tool results, code diff, and check evidence, so that I can follow cause and effect through an attempt.
39. As a reader, I want side-by-side implementation comparisons, so that orchestration differences are easy to inspect.
40. As an experimenter, I want model and tool latency, token usage, retries, and cache usage recorded, so that I can explain performance and spending.
41. As an experimenter, I want actual charges distinguished from estimates and unavailable metrics, so that cost reports remain honest.
42. As an experimenter, I want model identifiers, settings, source revisions, dependency versions, and pricing timestamps recorded, so that results have reproducible context.
43. As a project owner, I want API credentials outside task containers and traces, so that realistic repository access does not expose provider credentials.
44. As a project owner, I want disposable task environments with dependencies prepared before execution, so that attempts do not modify my original applications.
45. As an experimenter, I want task-container networking disabled, so that local repository work is separated from model-provider access.
46. As a learner, I want harness changes introduced one at a time on fixed tasks and models, so that I can understand what caused a change in behavior.
47. As a learner, I want the first milestone to use the complete execution and evaluation path, so that harder tasks extend the same architecture.
48. As an experimenter, I want replaceable model integration, so that Qwen and suitable local models can be added after the harness is understood.
49. As an experimenter, I want machine-readable artifacts, so that later multi-task and repeated-run analysis does not depend on scraping HTML.
50. As a portfolio owner, I want measured results and clearly stated limitations, so that I can demonstrate engineering work without overstating agent reliability.

## Implementation Decisions

- Build separate task preparation, model adapter, repository tools, context construction, orchestration, trace recording, evaluation, and report rendering responsibilities. The repository currently contains design documents and a glossary, not executable harness code.
- Use the domain terms agent harness, evaluation system, bug-repair task, task repository, attempt, attempt trace, acceptance checks, functional verdict, and termination reason consistently.
- Implement an explicit Python loop and a LangGraph workflow using explicit model and tool-execution nodes, a state schema, appropriate reducers, conditional routing, and explicit start/end behavior. Explain how each framework component corresponds to the explicit implementation. Begin without a prebuilt agent factory.
- Share task descriptions, prompts, model interface, tools, state meanings, context rules, budgets, and evaluator between orchestrators. Execute multiple tool requests in the same defined order in both implementations. LangGraph graph-step counts must not be treated as equivalent to model-call counts.
- Prefer a single high-level attempt-and-evaluation entry point as the integration seam. Inputs identify an admitted task, orchestrator, model configuration, budgets, and artifact destination. Outputs expose the termination reason, candidate patch, trace, metadata, acceptance results, and functional verdict. This is a proposed interface because no runtime seam exists yet.
- The model adapter returns content, available provider reasoning fields, tool requests, usage, and provider identity. Tool results expose status, output or artifact references, timing, and errors. Keep these contracts small and independent of either orchestrator.
- Use direct DeepSeek API access with the requested model identifier `deepseek-flash`, currently documented as DeepSeek-V4.1-Flash. Enable thinking at low effort with a bounded output budget. Record the requested and observed model identifiers, endpoint, settings, and run date. Do not describe a mutable alias as a pinned snapshot.
- Preserve provider-specific reasoning fields required for follow-up tool requests throughout the model adapter and graph state. Available reasoning content is observable provider output; hidden model reasoning is not assumed accessible.
- Use a small multi-turn tool-call smoke request to verify account access, response handling, latency, and usage before expensive attempts. Provider access and inference reliability have not yet been verified.
- Use ML Tutor as the first task repository. The inspected candidate revision is `6890d9eae6ebd2967553eaf5a0c5753c26322182`. Record the final admitted revision and environment rather than silently following its default branch.
- The first task candidate is lost title evidence during retrieval. Independently check both selected sections and the selected context forwarded to the tutor's injectable chat callable. Keep defect construction and the known repair outside the agent-visible task description.
- Admit the task only after the intact baseline passes, the introduced defect fails, and the known repair passes. Synthetic fixtures and fake tutor responses keep task checks offline. The exact candidate remains unexecuted and must be validated during task preparation.
- Package the repository revision, public task description, defect, known repair, environment definition, and acceptance-check version distinctly. Bind admission evidence to task identity and the content fingerprints of every task-package file. Mount only the task repository and agent-visible inputs into the attempt container. Evaluator-owned task data remains inaccessible to it.
- Run each attempt in a disposable container with full read/write access to the task copy and shell commands starting at its root. Prepare dependencies before execution and disable task-container networking. Keep provider calls in the outer harness; provide no model credentials, evaluator artifacts, host filesystem access, or container-engine socket to the agent container.
- Use file-reading, text-search, patch-editing, and shell tools. Log tool inputs, outputs, errors, and duration. Preserve full tool results as artifacts when only a bounded excerpt is sent back to the model.
- Initial context includes the public task description, repository instructions, short file map, and tool definitions. Discover relevant source through tools. Retain conversation and tool history until the measured context budget is reached; initially stop instead of compacting automatically.
- Stop on agent-declared completion, model-call budget, attempt deadline, context exhaustion, or unrecoverable provider/harness error. Preserve partial artifacts and record the specific termination reason. Enforce deadlines during blocking operations, not solely between steps.
- Use bounded, logged retries for transient provider failures. Return tool failures as structured results to the agent. Include retry activity in elapsed time and request accounting; do not invent billed usage for requests that return no usage information.
- Treat numeric defaults as calibration proposals rather than already accepted benchmark settings: 30 model calls, a 10-minute attempt deadline, a 60-second shell timeout, an 8,192-token response limit, and 16 KiB of model-visible output per tool result. Calibrate the context threshold and spending ceiling at smoke-run setup, then record identical effective limits for both orchestrators.
- Collect complete repository patches, including new files. Apply proposed changes to a fresh defective baseline in an independent evaluator environment with canonical checks and prepared dependencies. Do not carry container state or agent-modified dependencies into evaluation.
- Keep functional verdict and termination reason independent. A collected, evaluable patch that fails canonical acceptance checks is a repair failure. An `invalid_patch` failure means candidate changes could not be safely collected or applied; it does not claim the canonical checks failed. An `invalid_environment` verdict means evaluator-owned checks could not produce valid results. Candidate syntax, import, runtime, or probe-timeout errors are repair failures reported as failed canonical checks. An agent can finish without repairing the bug, or stop at a budget while leaving a working patch.
- Codex supplies a separate qualitative review of diagnosis, tool activity, patch quality, and failure cases using the recorded task, trace, diff, and test evidence. Review may remain pending until performed in this chat; no automatic model judge or scheduled reviewer is implied.
- Produce metadata, an ordered machine-readable trace, candidate patch, canonical check results, and local HTML. Record harness revision and working-tree fingerprint plus installed dependency versions for each attempt. Link report events to reasoning and response payloads, model-visible and full tool outputs, the candidate diff, and canonical check artifacts. Store generated artifacts outside agent control and ignore them in Git by default. Exclude API keys and authorization headers from artifacts.
- The HTML report leads with task, implementation, functional verdict, termination reason, duration, and cost. Use readable typography, restrained colors, expandable long content, and a side-by-side comparison view. Include timeline, exposed reasoning, tool details, unified diff, acceptance evidence, and separate qualitative review. Escape untrusted text and clearly mark truncation and missing information.
- Record cached/uncached input tokens, output and reasoning usage where provided, retries, model/tool latency, and pricing timestamp. Distinguish reported charges, estimates, and unavailable values. Keep token and latency comparisons separate from money comparisons because cache warmth and peak/off-peak rates can differ.
- Deliver six initial learning slices: task validity; tools and traces; explicit loop; independent evaluator and report; LangGraph counterpart; matched live comparison. Each includes an explanation, runnable experiment, and user inspection checkpoint. The milestone uses the same interfaces intended for later experiments.

## Testing Decisions

- Test observable behavior through the highest practical integration seam: the attempt-and-evaluation entry point. Use prepared task bundles and scripted model responses to exercise tools, orchestration, patch collection, evaluation, and report artifacts together. Prefer these checks over tests tied to private helper functions or framework internals.
- Task admission checks are a distinct prerequisite: establish baseline-pass, defect-fail, and known-repair-pass evidence independently before running agents. A faulty task definition must not be counted as an agent failure.
- Prior art in ML Tutor includes retrieval selection checks and tutor tests using fake chat and synthetic sections. Reuse its existing injectable chat boundary and source-to-context behavior; do not introduce live tutor API calls just to test a coding repair.
- For title-only relevance, provide an unrelated section first and a target section whose query terms occur only in its title. Confirm the target is retrieved and passed into tutor context. Reorder unrelated sections to reject accidental positional fixes.
- Preserve body-term retrieval, case normalization, top-k limits, input immutability, full-context bypass, and existing history/mode behavior. Do not broaden this task into unrelated empty-corpus repairs.
- Use scripted model/tool sequences to verify both orchestrators produce equivalent externally observable actions, accumulated context, budget accounting, and termination reasons. Test provider reasoning-field preservation through follow-up requests. This checks parity under controlled input, not identical live generation.
- Include a scripted attempt that edits an agent-visible test without repairing behavior; canonical checks must still fail. Include known correct and incorrect candidate patches and new repository files to validate patch application and scoring.
- Exercise tool failures, bounded output with truncation, command timeout, attempt deadline, context exhaustion, transient provider retry, unrecoverable provider error, and interrupted/partial attempts. Verify trace and patch retention at the integration boundary.
- Verify task-container networking is disabled and evaluator checks, model credentials, host data, and engine socket are absent. Run canonical checks in a fresh environment rather than trusting agent-visible test results.
- Test report rendering against recorded success, failure, and partial-attempt artifacts. Verify readable summaries, evidence links, escaped untrusted content, missing-metric states, pending qualitative review, and accurate distinction between reported and estimated cost. Visually inspect the final HTML and comparison view.
- Separate deterministic checks, Docker build/isolation checks, provider smoke tests, and live benchmark attempts in reporting. None is evidence that the other layer succeeded.
- First-milestone acceptance requires an admitted task, working tools and trace artifacts, independent correct/incorrect patch evaluation, scripted orchestrator parity, and one inspectable live attempt from each implementation under matched configuration. Agent success is not required for measurement validity.
- A single task with one attempt per orchestrator supports demonstration and diagnosis, not reliable aggregate model rankings. Later repeated, multi-task evaluations must report their sample size and limitations.

## Out of Scope

- Trading functionality, real broker access, and use of the algo trading repository.
- A generic hosted product, multi-user service, or broad framework built before the first measured attempt.
- Live ML Tutor answer-quality evaluation as a substitute for coding-agent repair checks.
- Exposing canonical acceptance checks, solution patches, or provider credentials to the coding agent.
- Guaranteed access to hidden model reasoning or treating exposed reasoning as proof of the agent's actual causal process.
- Automatic Codex judging, scheduled evaluation, or recurring external publication.
- Automatic context compaction, checkpoints/resume, and framework-specific advantages in the initial parity baseline. These are subsequent controlled harness experiments.
- Qwen integration, local model serving, Click tasks, broad historical-bug datasets, feature-implementation tasks, and multi-task statistical rankings in the first milestone. They remain planned extensions through the same boundaries.
- A fixed two-week deadline or a previously proposed EUR 30 spending cap; neither was accepted. Numerical execution limits and a live-run spending ceiling require calibration/configuration before paid runs.
- Modifying or publishing repairs to the original ML Tutor application; benchmark changes belong to disposable task copies.

## Further Notes

- This specification synthesizes the conversation and respects the existing ADRs on evaluator-owned acceptance checks, dual orchestration for learning, and separate disposable environments. The high-level testing seam follows the agreed independent evaluation and comparable-trace expectations; no new interview is required for publication.
- Publishing this issue does not mean the harness has been implemented, task behavior reproduced, or benchmarks completed. Preserve the user's incremental learning and inspection checkpoints when executing the work.
- Docker 29.1.3 was observed through approved read-only host execution on Linux x86_64. Ordinary sandbox execution lacked socket permission. Builds, image availability, container isolation, and test execution remain unverified.
- Direct DeepSeek was accepted after comparing current token rates and caching behavior. OpenRouter was not selected. No measured cache-hit rate is available for this workload; direct access also does not guarantee cache hits.
- Documentation checked on 2026-10-10: [DeepSeek models and pricing](https://api-docs.deepseek.com/quick_start/pricing/), [DeepSeek thinking and tool calls](https://api-docs.deepseek.com/guides/thinking_mode/), [DeepSeek context caching](https://api-docs.deepseek.com/guides/kv_cache/), [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api), and [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence). Recheck mutable model availability, aliases, and pricing before live execution.
- Current first-model API identifier is `deepseek-flash`; the previously proposed OpenAI model and Qwen starting model were superseded. Retain Qwen as a later comparison, with local deployment subject to a measured fit-and-speed check on the user's 16 GB GPU.
- Future experiments should vary one harness choice while holding tasks and model fixed, then vary models under a fixed harness. Use the same task preparation, attempt execution, independent evaluation, and reporting path for increasing task difficulty.
