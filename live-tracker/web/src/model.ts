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

// The nodes of the execution map. Each identity is a registered source function (live_tracker/sources.py):
// candidate collection, independent checks and finish are all recorded by attempt_and_evaluate.
export const COMPONENTS: ComponentInfo[] = [
  { id: "attempt", identity: "agent_eval_harness.attempt:attempt_and_evaluate", label: "Attempt lifecycle" },
  { id: "model-request", identity: "agent_eval_harness.loop:_request_model_turn", label: "Model request" },
  { id: "tool-execution", identity: "agent_eval_harness.tools:execute_tool_turn", label: "Tool execution" },
  { id: "repository-capture", identity: "agent_eval_harness.tools:execute_tool_turn", label: "Repository capture" },
  { id: "graph-router", identity: "agent_eval_harness.langgraph_attempt:route_after_node", label: "LangGraph router" },
  { id: "graph-end", identity: "agent_eval_harness.langgraph_attempt:route_after_node", label: "LangGraph END" },
  { id: "candidate", identity: "agent_eval_harness.attempt:attempt_and_evaluate", label: "Candidate collection" },
  { id: "checks", identity: "agent_eval_harness.attempt:attempt_and_evaluate", label: "Independent checks" },
  { id: "finish", identity: "agent_eval_harness.attempt:attempt_and_evaluate", label: "Finish" },
];

const PHASE_COMPONENT: Record<string, string> = {
  "agent_eval_harness.loop:_request_model_turn": "model-request",
  "agent_eval_harness.tools:execute_tool_turn": "tool-execution",
};

// Graph nodes run the same model and tool functions as the Python phases.
const NODE_COMPONENT: Record<string, string> = {
  model_request: "model-request",
  tool_execution: "tool-execution",
};

// Starts whose outcome may be missing; a missing outcome is shown as waiting or unresolved.
export const OPERATION_STARTS = new Set(["node.enter", "model.start", "tool.start"]);

// Tools whose outcome is followed by a repository capture (tool.capture, linked by parent_operation_id).
export const MUTATING_TOOLS = new Set(["apply_patch", "run_shell"]);

// The map nodes an event belongs to, the event's own node first. An end decision is both the router's and
// END's. Termination and the other events without a node are not on the map.
export function componentsOf(event: TrackerEvent): string[] {
  switch (event.type) {
    case "phase.enter":
      return one(PHASE_COMPONENT[event.data.source]);
    case "node.enter":
    case "node.outcome":
      return one(NODE_COMPONENT[event.data.node]);
    case "route.decision":
      return event.data.next === "end" ? ["graph-router", "graph-end"] : ["graph-router"];
    case "state":
      return one(NODE_COMPONENT[event.data.after_node ?? event.data.after_phase]);
    case "attempt_started":
    case "initial_context":
      return ["attempt"];
    case "patch_collection":
      return ["candidate"];
    case "evaluation":
      return ["checks"];
    case "attempt_finished":
      return ["finish"];
    case "tool.capture":
      return ["repository-capture"];
  }
  if (event.type.startsWith("model.")) {
    return ["model-request"];
  }
  if (event.type.startsWith("tool.")) {
    return ["tool-execution"];
  }
  return [];
}

function one(component: string | undefined): string[] {
  return component === undefined ? [] : [component];
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

// The timeline filter and colour group of an event type.
export function categoryOf(type: string): "model" | "tool" | "flow" | "state" | "lifecycle" {
  if (type.startsWith("model.")) {
    return "model";
  }
  if (type.startsWith("tool.")) {
    return "tool";
  }
  if (type === "phase.enter" || type === "route.decision" || type.startsWith("node.")) {
    return "flow";
  }
  return type === "state" ? "state" : "lifecycle";
}
