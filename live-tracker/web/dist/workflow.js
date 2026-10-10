// Execution map state for the selected point: which nodes and edges the recorded events up to that
// sequence have reached. Pure: no DOM. Later events never contribute, so the map cannot show a fact the
// selection had not reached.
import { OPERATION_STARTS, componentsOf } from "./model.js";
// Two geometries per flow, drawn at their natural pixel size (no scaling): `wide` is the full-width band on
// desktop, read left to right; `tall` is the phone column. Titles are 13px and sub-labels 11px in both.
// Node order and edge order are the same in both, so the DOM and the tests read the same flow.
const WIDE_PYTHON = {
    width: 1208,
    height: 268,
    nodes: [
        { id: "attempt", label: "Attempt lifecycle", name: "Attempt lifecycle", x: 0, y: 100, w: 150, h: 56 },
        { id: "model-request", label: "Model request", name: "Model request", x: 206, y: 100, w: 150, h: 56 },
        { id: "tool-execution", label: "Tool execution", name: "Tool execution", x: 440, y: 100, w: 150, h: 56 },
        { id: "repository-capture", label: "Repo capture", name: "Repository capture", x: 440, y: 204, w: 150, h: 56 },
        { id: "candidate", label: "Candidate collection", name: "Candidate collection", x: 646, y: 100, w: 150, h: 56 },
        { id: "checks", label: "Independent checks", name: "Independent checks", x: 852, y: 100, w: 150, h: 56 },
        { id: "finish", label: "Finish", name: "Finish", x: 1058, y: 100, w: 150, h: 56 },
    ],
    edges: [
        { id: "start-model", d: "M150,128 H206", lines: ["model request"], lx: 178, ly: 88, anchor: "middle" },
        // Forward turn straight across the gap; the loop-back curves below the row, away from the capture node.
        { id: "model-tool", d: "M356,128 H440", lines: ["tool calls"], lx: 398, ly: 118, anchor: "middle" },
        { id: "tool-model", d: "M470,156 C452,186 356,186 338,156", lines: ["tool results"], lx: 404, ly: 194, anchor: "middle" },
        { id: "tool-capture", d: "M515,156 V204", lines: [], lx: 0, ly: 0, anchor: "start" },
        // The stop edge arcs above the tool node into candidate collection. Its lines are the stop and the reason.
        { id: "model-candidate", d: "M281,100 C281,40 721,40 721,100", lines: ["on stop", ""], lx: 501, ly: 30, anchor: "middle" },
        { id: "candidate-checks", d: "M796,128 H852", lines: [], lx: 0, ly: 0, anchor: "start" },
        { id: "checks-finish", d: "M1002,128 H1058", lines: [], lx: 0, ly: 0, anchor: "start" },
    ],
};
const WIDE_LANGGRAPH = {
    width: 1242,
    height: 276,
    nodes: [
        { id: "attempt", label: "START", name: "Attempt lifecycle", x: 0, y: 100, w: 150, h: 56 },
        { id: "model-request", label: "Model request", name: "Model request", x: 182, y: 100, w: 150, h: 56 },
        { id: "graph-router", label: "LangGraph router", name: "LangGraph router", x: 364, y: 100, w: 150, h: 56 },
        { id: "tool-execution", label: "Tool execution", name: "Tool execution", x: 364, y: 212, w: 150, h: 56 },
        { id: "graph-end", label: "END", name: "LangGraph END", x: 546, y: 100, w: 150, h: 56 },
        { id: "candidate", label: "Candidate collection", name: "Candidate collection", x: 728, y: 100, w: 150, h: 56 },
        { id: "checks", label: "Independent checks", name: "Independent checks", x: 910, y: 100, w: 150, h: 56 },
        { id: "finish", label: "Finish", name: "Finish", x: 1092, y: 100, w: 150, h: 56 },
    ],
    edges: [
        { id: "start-model", d: "M150,128 H182", lines: ["model request"], lx: 166, ly: 88, anchor: "middle" },
        { id: "model-router", d: "M332,128 H364", lines: ["after model"], lx: 348, ly: 88, anchor: "middle" },
        // The router loops with the tool node below it: down for tool_calls, back up for after tool, and the
        // tool_results edge returns to the model node below the row.
        { id: "router-model", d: "M380,156 C360,186 280,186 262,156", lines: ["tool_results"], lx: 330, ly: 194, anchor: "end" },
        { id: "router-tool", d: "M400,156 V212", lines: ["tool_calls"], lx: 394, ly: 190, anchor: "end" },
        { id: "tool-router", d: "M480,212 V156", lines: ["after tool"], lx: 486, ly: 190, anchor: "start" },
        { id: "router-end", d: "M514,128 H546", lines: ["end"], lx: 530, ly: 88, anchor: "middle" },
        { id: "end-candidate", d: "M696,128 H728", lines: [], lx: 0, ly: 0, anchor: "start" },
        { id: "candidate-checks", d: "M878,128 H910", lines: [], lx: 0, ly: 0, anchor: "start" },
        { id: "checks-finish", d: "M1060,128 H1092", lines: [], lx: 0, ly: 0, anchor: "start" },
    ],
};
const TALL_PYTHON = {
    width: 340,
    height: 484,
    nodes: [
        { id: "attempt", label: "Attempt lifecycle", name: "Attempt lifecycle", x: 28, y: 0, w: 180, h: 56 },
        { id: "model-request", label: "Model request", name: "Model request", x: 28, y: 84, w: 180, h: 56 },
        { id: "tool-execution", label: "Tool execution", name: "Tool execution", x: 28, y: 168, w: 180, h: 56 },
        { id: "repository-capture", label: "Repo capture", name: "Repository capture", x: 236, y: 168, w: 98, h: 56 },
        { id: "candidate", label: "Candidate collection", name: "Candidate collection", x: 28, y: 252, w: 180, h: 56 },
        { id: "checks", label: "Independent checks", name: "Independent checks", x: 28, y: 336, w: 180, h: 56 },
        { id: "finish", label: "Finish", name: "Finish", x: 28, y: 420, w: 180, h: 56 },
    ],
    edges: [
        { id: "start-model", d: "M118,56 V84", lines: ["model request"], lx: 126, ly: 74, anchor: "start" },
        { id: "model-tool", d: "M98,140 V168", lines: ["tool calls"], lx: 92, ly: 158, anchor: "end" },
        { id: "tool-model", d: "M138,168 V140", lines: ["tool results"], lx: 144, ly: 158, anchor: "start" },
        { id: "tool-capture", d: "M208,196 H236", lines: [], lx: 0, ly: 0, anchor: "start" },
        // Stop edge: left of the column, then into candidate collection. Its second line is the recorded reason.
        { id: "model-candidate", d: "M28,112 H12 V280 H28", lines: ["on stop", ""], lx: 244, ly: 262, anchor: "start" },
        { id: "candidate-checks", d: "M118,308 V336", lines: [], lx: 0, ly: 0, anchor: "start" },
        { id: "checks-finish", d: "M118,392 V420", lines: [], lx: 0, ly: 0, anchor: "start" },
    ],
};
const TALL_LANGGRAPH = {
    width: 340,
    height: 568,
    nodes: [
        { id: "attempt", label: "START", name: "Attempt lifecycle", x: 28, y: 0, w: 180, h: 56 },
        { id: "model-request", label: "Model request", name: "Model request", x: 28, y: 84, w: 180, h: 56 },
        { id: "graph-router", label: "LangGraph router", name: "LangGraph router", x: 28, y: 168, w: 180, h: 56 },
        { id: "tool-execution", label: "Tool execution", name: "Tool execution", x: 236, y: 168, w: 98, h: 56 },
        { id: "graph-end", label: "END", name: "LangGraph END", x: 28, y: 252, w: 180, h: 56 },
        { id: "candidate", label: "Candidate collection", name: "Candidate collection", x: 28, y: 336, w: 180, h: 56 },
        { id: "checks", label: "Independent checks", name: "Independent checks", x: 28, y: 420, w: 180, h: 56 },
        { id: "finish", label: "Finish", name: "Finish", x: 28, y: 504, w: 180, h: 56 },
    ],
    edges: [
        { id: "start-model", d: "M118,56 V84", lines: ["model request"], lx: 126, ly: 74, anchor: "start" },
        { id: "model-router", d: "M118,140 V168", lines: ["after model"], lx: 126, ly: 158, anchor: "start" },
        // Router back to the model node after a tool turn, down the left side of the column.
        { id: "router-model", d: "M28,196 H12 V112 H28", lines: ["tool_results"], lx: 110, ly: 158, anchor: "end" },
        { id: "router-tool", d: "M208,180 H236", lines: ["tool_calls"], lx: 236, ly: 160, anchor: "start" },
        { id: "tool-router", d: "M236,212 H208", lines: ["after tool"], lx: 236, ly: 240, anchor: "start" },
        { id: "router-end", d: "M118,224 V252", lines: ["end"], lx: 126, ly: 242, anchor: "start" },
        { id: "end-candidate", d: "M118,308 V336", lines: [], lx: 0, ly: 0, anchor: "start" },
        { id: "candidate-checks", d: "M118,392 V420", lines: [], lx: 0, ly: 0, anchor: "start" },
        { id: "checks-finish", d: "M118,476 V504", lines: [], lx: 0, ly: 0, anchor: "start" },
    ],
};
const LAYOUTS = {
    "python-loop": { wide: WIDE_PYTHON, tall: TALL_PYTHON },
    langgraph: { wide: WIDE_LANGGRAPH, tall: TALL_LANGGRAPH },
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
export function computeWorkflow(events, selectedIndex, stopped, wide) {
    const { flow, legacy } = flowOf(events);
    const layout = LAYOUTS[flow][wide ? "wide" : "tall"];
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
            h: node.h,
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
                lines[1] = reason ?? "not yet recorded";
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
