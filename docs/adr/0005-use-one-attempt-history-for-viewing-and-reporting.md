# Use one attempt history for viewing and reporting

The viewer, recorded playback and final report consume one versioned append-only history of observable attempt events and its associated artifacts. We accept designing compatibility and completeness explicitly instead of maintaining a separate UI history, so a displayed action can be traced to the same evidence used in evaluation and review. Events are stored in JSONL with linked artifact files; a local SSE connection delivers recorded events to the viewer.

Mandatory evidence recording belongs to the attempt boundary: inability to save it stops further agent work at a safe boundary and marks the evidence incomplete. The browser remains a replaceable observer, so its disconnection does not stop the attempt. This intentionally treats evidence loss differently from a failed repair or a failed viewing connection.

Within an attempt, event sequence determines recorded order and operation identities connect starts to outcomes. Readers preserve interrupted evidence and expose its verified prefix, gaps or corruption; they do not fabricate completion or earlier state from final summaries.

Save and sync operation starts before execution and outcomes before advertising them as recorded, writing linked artifacts atomically before their references. We accept this recording overhead for inspectable interrupted attempts; bounded browser buffering and disk catch-up keep slow observers outside execution ownership.
