// Event shapes and pure selection rules for the workbench. No DOM here.

export interface Artifact {
  role: string;
  path: string;
  bytes: number;
  sha256: string;
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
}

export interface ComponentInfo {
  id: string;
  identity: string;
  label: string;
}

// Only server-validated artifact paths are ever fetched.
export const ARTIFACT_PATH = /^artifacts\/[0-9a-f]{64}$/;

export const COMPONENTS: ComponentInfo[] = [
  { id: "attempt", identity: "agent_eval_harness.attempt:attempt_and_evaluate", label: "Attempt lifecycle" },
  { id: "python-loop", identity: "agent_eval_harness.loop:run_python_loop", label: "Python loop" },
  { id: "model-request", identity: "agent_eval_harness.loop:_request_model_turn", label: "Model request" },
  { id: "tool-execution", identity: "agent_eval_harness.tools:execute_tool_turn", label: "Tool execution" },
];

const COMPONENT_BY_SOURCE: Record<string, string> = Object.fromEntries(
  COMPONENTS.map((component) => [component.identity, component.id]),
);

// The component whose registered source function produced the event, or null.
export function componentOf(event: TrackerEvent): string | null {
  if (event.type === "phase.enter") {
    return COMPONENT_BY_SOURCE[event.data.source] ?? null;
  }
  if (event.type === "state") {
    return "python-loop";
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
