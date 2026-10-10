// Execution map state for the selected point: which nodes and edges the recorded events up to that
// sequence have reached. Pure: no DOM. Later events never contribute, so the map cannot show a fact the
// selection had not reached.
import { OPERATION_STARTS, componentsOf } from "./model.js";
// The main flow is centred on x=105; the right column holds the side node (tool execution in the LangGraph
// flow, repository capture in the Python flow). Rows are 72 apart: 40-high boxes with 32-high gaps for labels.
const MAIN = { x: 30, w: 150 };
const SIDE = { x: 208, w: 104 };
const ROW = (row) => row * 72;
const LAYOUTS = {
    "python-loop": {
        width: 320,
        height: 408,
        nodes: [
            { id: "attempt", label: "Attempt lifecycle", name: "Attempt lifecycle", x: MAIN.x, y: ROW(0), w: MAIN.w },
            { id: "model-request", label: "Model request", name: "Model request", x: MAIN.x, y: ROW(1), w: MAIN.w },
            { id: "tool-execution", label: "Tool execution", name: "Tool execution", x: MAIN.x, y: ROW(2), w: MAIN.w },
            { id: "repository-capture", label: "Repo capture", name: "Repository capture", x: SIDE.x, y: ROW(2), w: SIDE.w },
            { id: "candidate", label: "Candidate collection", name: "Candidate collection", x: MAIN.x, y: ROW(3), w: MAIN.w },
            { id: "checks", label: "Independent checks", name: "Independent checks", x: MAIN.x, y: ROW(4), w: MAIN.w },
            { id: "finish", label: "Finish", name: "Finish", x: MAIN.x, y: ROW(5), w: MAIN.w },
        ],
        edges: [
            { id: "start-model", d: "M105,40 V72", lines: ["model request"], lx: 113, ly: 60, anchor: "start" },
            { id: "model-tool", d: "M85,112 V144", lines: ["tool calls"], lx: 79, ly: 131, anchor: "end" },
            { id: "tool-model", d: "M125,144 V112", lines: ["tool results"], lx: 131, ly: 131, anchor: "start" },
            { id: "tool-capture", d: "M180,164 H208", lines: [], lx: 0, ly: 0, anchor: "start" },
            // Stop edge: left of the column, then into candidate collection. Its second line is the recorded reason.
            { id: "model-candidate", d: "M30,92 H16 V236 H30", lines: ["on stop", ""], lx: 208, ly: 204, anchor: "start" },
            { id: "candidate-checks", d: "M105,256 V288", lines: [], lx: 0, ly: 0, anchor: "start" },
            { id: "checks-finish", d: "M105,328 V360", lines: [], lx: 0, ly: 0, anchor: "start" },
        ],
    },
    langgraph: {
        width: 320,
        height: 480,
        nodes: [
            { id: "attempt", label: "START", name: "Attempt lifecycle", x: MAIN.x, y: ROW(0), w: MAIN.w },
            { id: "model-request", label: "Model request", name: "Model request", x: MAIN.x, y: ROW(1), w: MAIN.w },
            { id: "graph-router", label: "LangGraph router", name: "LangGraph router", x: MAIN.x, y: ROW(2), w: MAIN.w },
            { id: "tool-execution", label: "Tool execution", name: "Tool execution", x: SIDE.x, y: ROW(2), w: SIDE.w },
            { id: "graph-end", label: "END", name: "LangGraph END", x: MAIN.x, y: ROW(3), w: MAIN.w },
            { id: "candidate", label: "Candidate collection", name: "Candidate collection", x: MAIN.x, y: ROW(4), w: MAIN.w },
            { id: "checks", label: "Independent checks", name: "Independent checks", x: MAIN.x, y: ROW(5), w: MAIN.w },
            { id: "finish", label: "Finish", name: "Finish", x: MAIN.x, y: ROW(6), w: MAIN.w },
        ],
        edges: [
            { id: "start-model", d: "M105,40 V72", lines: ["model request"], lx: 113, ly: 60, anchor: "start" },
            { id: "model-router", d: "M105,112 V144", lines: ["after model"], lx: 113, ly: 131, anchor: "start" },
            // Router back to the model node after a tool turn, down the left side of the column.
            { id: "router-model", d: "M30,164 H16 V92 H30", lines: ["tool_results"], lx: 99, ly: 131, anchor: "end" },
            { id: "router-tool", d: "M180,156 H208", lines: ["tool_calls"], lx: 196, ly: 138, anchor: "start" },
            { id: "tool-router", d: "M208,172 H180", lines: ["after tool"], lx: 196, ly: 200, anchor: "start" },
            { id: "router-end", d: "M105,184 V216", lines: ["end"], lx: 113, ly: 204, anchor: "start" },
            { id: "end-candidate", d: "M105,256 V288", lines: [], lx: 0, ly: 0, anchor: "start" },
            { id: "candidate-checks", d: "M105,328 V360", lines: [], lx: 0, ly: 0, anchor: "start" },
            { id: "checks-finish", d: "M105,400 V432", lines: [], lx: 0, ly: 0, anchor: "start" },
        ],
    },
};
// The flow comes from the recorded attempt_started. A legacy trace records no attempt_started and no
// transitions: its flow is derived from the event types present, and the caller says so.
export function flowOf(events) {
    const started = events.find((event) => event.type === "attempt_started");
    const recorded = started?.data.orchestrator;
    if (recorded === "python-loop" || recorded === "langgraph") {
        return { flow: recorded, legacy: false };
    }
    if (started !== undefined || events.length === 0) {
        return { flow: "python-loop", legacy: false };
    }
    const graph = events.some((event) => event.type === "route.decision" || event.type === "node.enter");
    return { flow: graph ? "langgraph" : "python-loop", legacy: true };
}
export function computeWorkflow(events, selectedIndex, stopped) {
    const { flow, legacy } = flowOf(events);
    const layout = LAYOUTS[flow];
    const visible = selectedIndex >= 0 ? events.slice(0, selectedIndex + 1) : [];
    const selected = visible[visible.length - 1];
    const active = selected !== undefined ? componentsOf(selected)[0] ?? null : null;
    const counts = new Map();
    for (const event of visible) {
        for (const component of componentsOf(event)) {
            counts.set(component, (counts.get(component) ?? 0) + 1);
        }
    }
    const { waiting, unresolved } = pendingStarts(events, visible, stopped);
    const routes = recordedRoutes(visible);
    const transitions = walkedTransitions(visible);
    const nodes = layout.nodes.map((node) => {
        const count = counts.get(node.id) ?? 0;
        const status = active === node.id ? "active" : count > 0 ? "reached" : "not-reached";
        const isWaiting = waiting.has(node.id);
        const isUnresolved = unresolved.has(node.id);
        const words = [
            ...(isUnresolved ? ["unresolved"] : []),
            ...(isWaiting ? ["waiting"] : []),
            ...(status === "active" ? ["active"] : []),
        ];
        const eventsText = `${count} ${count === 1 ? "event" : "events"}`;
        let countText;
        if (count === 0) {
            countText = "not reached";
        }
        else {
            countText = words.length > 0 ? `${count}` : eventsText;
        }
        return {
            id: node.id,
            label: node.label,
            name: node.name,
            x: node.x,
            y: node.y,
            w: node.w,
            h: 40,
            status,
            waiting: isWaiting,
            unresolved: isUnresolved,
            count,
            subtitle: words.length > 0 ? `${words.join(" · ")} · ${countText}` : countText,
            description: [...words, count > 0 ? eventsText : "not reached"].join(", "),
        };
    });
    const edges = layout.edges.map((edge) => {
        const lines = [...edge.lines];
        let traversed;
        switch (edge.id) {
            case "start-model":
                traversed = (counts.get("model-request") ?? 0) > 0;
                break;
            case "model-tool":
                traversed = transitions.has("model>tool");
                break;
            case "tool-model":
                traversed = transitions.has("tool>model");
                break;
            case "tool-capture":
                traversed = (counts.get("repository-capture") ?? 0) > 0;
                break;
            case "model-candidate": {
                traversed = (counts.get("candidate") ?? 0) > 0;
                const reason = terminationReason(visible);
                lines[1] = reason ?? "reason not yet recorded";
                break;
            }
            case "end-candidate":
                traversed = (counts.get("candidate") ?? 0) > 0;
                break;
            case "candidate-checks":
                traversed = (counts.get("checks") ?? 0) > 0;
                break;
            case "checks-finish":
                traversed = (counts.get("finish") ?? 0) > 0;
                break;
            case "model-router":
                traversed = routes.some((route) => route.after === "model_request");
                break;
            case "router-model":
                traversed = routes.some((route) => route.next === "model_request");
                break;
            case "router-tool":
                traversed = routes.some((route) => route.next === "tool_execution");
                break;
            case "tool-router":
                traversed = routes.some((route) => route.after === "tool_execution");
                break;
            case "router-end": {
                const last = routes.filter((route) => route.next === "end").pop();
                traversed = last !== undefined;
                // The recorded reason of the newest decision to end the graph is shown on the edge.
                lines[0] = last !== undefined ? `end: ${last.reason}` : "end";
                break;
            }
            default:
                traversed = false;
        }
        return { id: edge.id, d: edge.d, traversed, lines, lx: edge.lx, ly: edge.ly, anchor: edge.anchor };
    });
    return { flow, legacy, width: layout.width, height: layout.height, nodes, edges };
}
// Starts recorded up to the selection with no outcome yet at that point. A start whose outcome is
// recorded later is waiting here. One whose outcome never comes is unresolved once the recording has
// stopped, and waiting while the attempt is live.
function pendingStarts(events, visible, stopped) {
    const outcomes = new Map();
    events.forEach((event, index) => {
        if (event.operation_id && !OPERATION_STARTS.has(event.type) && !outcomes.has(event.operation_id)) {
            outcomes.set(event.operation_id, index);
        }
    });
    const waiting = new Set();
    const unresolved = new Set();
    for (const event of visible) {
        const component = componentsOf(event)[0];
        if (!OPERATION_STARTS.has(event.type) || !event.operation_id || component === undefined) {
            continue;
        }
        const outcome = outcomes.get(event.operation_id);
        if (outcome !== undefined && outcome < visible.length) {
            continue;
        }
        if (outcome === undefined && stopped) {
            unresolved.add(component);
        }
        else {
            waiting.add(component);
        }
    }
    return { waiting, unresolved };
}
// Python loop: the main path alternates model and tool turns. Each change of turn is one transition.
// Capture, state and the other side events do not move the path.
function walkedTransitions(visible) {
    const taken = new Set();
    let previous = null;
    for (const event of visible) {
        const component = componentsOf(event)[0];
        if (component !== "model-request" && component !== "tool-execution") {
            continue;
        }
        if (previous !== null && previous !== component) {
            taken.add(previous === "model-request" ? "model>tool" : "tool>model");
        }
        previous = component;
    }
    return taken;
}
// The recorded stop reason, once the termination has been recorded at this point.
function terminationReason(visible) {
    const termination = visible.filter((event) => event.type === "termination").pop();
    return termination === undefined ? undefined : String(termination.data.reason ?? "reason not recorded");
}
// LangGraph: each route decision is recorded with the node it followed and the node it chose.
function recordedRoutes(visible) {
    return visible
        .filter((event) => event.type === "route.decision")
        .map((event) => ({
        after: String(event.data.after_node),
        next: String(event.data.next),
        reason: String(event.data.reason),
    }));
}
