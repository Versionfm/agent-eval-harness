// Event shapes and pure selection rules for the workbench. No DOM here.

export interface Artifact {
  role: string;
  path: string;
  bytes: number;
  sha256: string;
}

// What a legacy record lacks (unavailable), computed now from saved bytes (derived), or carried inline in the trace.
export interface EventLabels {
  unavailable: string[];
  derived: string[];
  inline: string[];
}

export interface TrackerEvent {
  sequence: number;
  type: string;
  timestamp?: string;
  elapsed_seconds?: number;
  operation_id?: string;
  parent_operation_id?: string;
  data: Record<string, any>;
  artifacts: Artifact[];
  legacy?: boolean;
  labels?: EventLabels;
}

export interface ComponentInfo {
  id: string;
  identity: string;
  label: string;
}

// Only server-validated artifact paths are ever fetched: content-addressed ones, and the preserved
// legacy tool outputs by their recorded relative path.
export const ARTIFACT_PATH = /^(artifacts\/[0-9a-f]{64}|tool-results\/event-\d{4}\.txt)$/;

// Graph node components point at the shared functions their nodes run. Graph events select them by
// node name, and Python phases by source, so the shared identities never collide.
export const COMPONENTS: ComponentInfo[] = [
  { id: "attempt", identity: "agent_eval_harness.attempt:attempt_and_evaluate", label: "Attempt lifecycle" },
  { id: "python-loop", identity: "agent_eval_harness.loop:run_python_loop", label: "Python loop" },
  { id: "model-request", identity: "agent_eval_harness.loop:_request_model_turn", label: "Model request" },
  { id: "tool-execution", identity: "agent_eval_harness.tools:execute_tool_turn", label: "Tool execution" },
  { id: "graph-model-node", identity: "agent_eval_harness.loop:_request_model_turn", label: "LangGraph model_request node" },
  { id: "graph-tool-node", identity: "agent_eval_harness.tools:execute_tool_turn", label: "LangGraph tool_execution node" },
  { id: "graph-router", identity: "agent_eval_harness.langgraph_attempt:route_after_node", label: "LangGraph router" },
];

const PHASE_COMPONENT: Record<string, string> = {
  "agent_eval_harness.loop:_request_model_turn": "model-request",
  "agent_eval_harness.tools:execute_tool_turn": "tool-execution",
};

const GRAPH_NODE_COMPONENT: Record<string, string> = {
  model_request: "graph-model-node",
  tool_execution: "graph-tool-node",
};

// Starts whose outcome may be missing; a missing outcome is shown as waiting or unresolved.
export const OPERATION_STARTS = new Set(["node.enter", "model.start", "tool.start"]);

// The component whose registered source function produced the event, or null.
export function componentOf(event: TrackerEvent): string | null {
  if (event.type === "phase.enter") {
    return PHASE_COMPONENT[event.data.source] ?? null;
  }
  if (event.type === "node.enter" || event.type === "node.outcome") {
    return GRAPH_NODE_COMPONENT[event.data.node] ?? null;
  }
  if (event.type === "route.decision") {
    return "graph-router";
  }
  if (event.type === "state") {
    return event.data.after_node !== undefined
      ? GRAPH_NODE_COMPONENT[event.data.after_node] ?? null
      : "python-loop";
  }
  if (event.type.startsWith("model.")) {
    return "model-request";
  }
  if (event.type.startsWith("tool.")) {
    return "tool-execution";
  }
  if (event.type === "attempt_started" || event.type === "initial_context" || event.type === "attempt_finished") {
    return "attempt";
  }
  return null;
}

// Selected-point state: the newest state event at or before the selected sequence.
// Later events never contribute, so the view cannot show facts the selection had not reached.
export function selectedPointState(events: TrackerEvent[], sequence: number): TrackerEvent | null {
  let found: TrackerEvent | null = null;
  for (const event of events) {
    if (event.sequence > sequence) {
      break;
    }
    if (event.type === "state") {
      found = event;
    }
  }
  return found;
}
