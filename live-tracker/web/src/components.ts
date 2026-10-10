// Execution map: the recorded flow drawn as SVG, each node showing its state at the selected point. On desktop it
// is a full-width band read left to right; below 900px it is a vertical column. Each geometry is drawn at its
// natural size, so text is never scaled down; the map scrolls horizontally inside its own container if needed.
// The SVG is built once per flow and geometry, and repainted in place, so keyboard focus survives a selection.
// Evidence never reaches the DOM here: labels are fixed names and counts.

import { TrackerEvent } from "./model.js";
import { el } from "./dom.js";
import { Flow, WorkflowState, computeWorkflow } from "./workflow.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const WIDE = "(min-width: 900px)";

function svgEl<K extends keyof SVGElementTagNameMap>(
  tag: K, attributes: Record<string, string | number> = {}, text?: string,
): SVGElementTagNameMap[K] {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attributes)) {
    node.setAttribute(name, String(value));
  }
  if (text !== undefined) {
    node.textContent = text;
  }
  return node;
}

function arrowhead(id: string, className: string): SVGMarkerElement {
  const marker = svgEl("marker", {
    id, class: className, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto",
  });
  marker.append(svgEl("path", { d: "M0,0 L10,5 L0,10 z" }));
  return marker;
}

interface Shown {
  events: TrackerEvent[];
  selectedIndex: number;
  stopped: boolean;
  pressed: string | null;
}

export class WorkflowMap {
  private key: string | null = null;
  private svg: SVGSVGElement | null = null;
  private shown: Shown | null = null;
  private readonly nodeElements = new Map<string, SVGGElement>();
  private readonly edgeElements = new Map<string, SVGPathElement>();
  private readonly labelElements = new Map<string, SVGTextElement>();
  private readonly caption = el("p", "note wf-caption");
  private readonly wide = window.matchMedia(WIDE);

  constructor(private readonly nav: HTMLElement, private readonly onSelect: (component: string) => void) {
    nav.append(this.caption);
    this.wide.addEventListener("change", () => this.render());
  }

  // `pressed` is the component chosen from the map, shown apart from the selected event's own node.
  update(events: TrackerEvent[], selectedIndex: number, stopped: boolean, pressed: string | null): void {
    this.shown = { events, selectedIndex, stopped, pressed };
    this.render();
  }

  private render(): void {
    if (this.shown === null) {
      return;
    }
    const { events, selectedIndex, stopped, pressed } = this.shown;
    const state = computeWorkflow(events, selectedIndex, stopped, this.wide.matches);
    const key = `${state.flow}/${this.wide.matches ? "wide" : "tall"}`;
    if (key !== this.key || this.svg === null) {
      this.build(state, key);
    }
    this.paint(state, pressed, events.length === 0);
  }

  private build(state: WorkflowState, key: string): void {
    this.key = key;
    this.nodeElements.clear();
    this.edgeElements.clear();
    this.labelElements.clear();
    const svg = svgEl("svg", {
      class: "wf-map", width: state.width, height: state.height, viewBox: `0 0 ${state.width} ${state.height}`,
      role: "group", "aria-label": "Execution map of the recorded flow",
    });
    const defs = svgEl("defs");
    defs.append(arrowhead("wf-arrow-on", "wf-arrow-on"), arrowhead("wf-arrow-off", "wf-arrow-off"));
    svg.append(defs);

    for (const edge of state.edges) {
      const path = svgEl("path", { class: "wf-edge", "data-edge": edge.id, d: edge.d });
      svg.append(path);
      this.edgeElements.set(edge.id, path);
    }
    for (const edge of state.edges) {
      if (edge.lines.length > 0) {
        const label = svgEl("text", {
          class: "wf-edge-label", "data-edge-label": edge.id, x: edge.lx, y: edge.ly, "text-anchor": edge.anchor,
        });
        svg.append(label);
        this.labelElements.set(edge.id, label);
      }
    }
    for (const node of state.nodes) {
      const group = svgEl("g", {
        class: "wf-node", "data-component": node.id, role: "button", tabindex: 0,
      });
      group.append(
        svgEl("rect", { class: "wf-ring", x: node.x - 4, y: node.y - 4, width: node.w + 8, height: node.h + 8, rx: 9 }),
        svgEl("rect", { class: "wf-box", x: node.x, y: node.y, width: node.w, height: node.h, rx: 6 }),
        svgEl("text", { class: "wf-title", x: node.x + 10, y: node.y + 22 }, node.label),
        svgEl("text", { class: "wf-status", x: node.x + 10, y: node.y + 40 }),
      );
      group.addEventListener("click", () => this.onSelect(node.id));
      group.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          this.onSelect(node.id);
        }
      });
      svg.append(group);
      this.nodeElements.set(node.id, group);
    }

    this.svg?.remove();
    this.svg = svg;
    this.nav.insertBefore(svg, this.caption);
  }

  private paint(state: WorkflowState, pressed: string | null, empty: boolean): void {
    this.nav.dataset.flow = state.flow;
    for (const node of state.nodes) {
      const group = this.nodeElements.get(node.id)!;
      group.dataset.status = node.status;
      group.dataset.waiting = String(node.waiting);
      group.dataset.unresolved = String(node.unresolved);
      group.dataset.count = String(node.count);
      group.dataset.pressed = String(pressed === node.id);
      group.setAttribute("aria-label", `${node.name}: ${node.description}`);
      group.setAttribute("aria-pressed", String(pressed === node.id));
      group.querySelector(".wf-status")!.textContent = node.subtitle;
    }
    for (const edge of state.edges) {
      const path = this.edgeElements.get(edge.id)!;
      path.dataset.traversed = String(edge.traversed);
      path.setAttribute("marker-end", `url(#${edge.traversed ? "wf-arrow-on" : "wf-arrow-off"})`);
      const label = this.labelElements.get(edge.id);
      if (label) {
        label.replaceChildren(...edge.lines.map((line, index) =>
          svgEl("tspan", { x: edge.lx, dy: index === 0 ? 0 : 13 }, line)));
      }
    }
    this.caption.textContent = caption(state, empty);
  }
}

function caption(state: WorkflowState, empty: boolean): string {
  if (empty) {
    return "Waiting for the attempt to start. Nodes and edges fill in as recorded events arrive.";
  }
  if (state.legacy) {
    return `Flow ${state.flow}: derived from event types; legacy trace did not record transitions. `
      + "Dashed edges and dimmed nodes were not reached at the selected point.";
  }
  const capture = state.flow === "python-loop" ? " Repository capture follows only mutating tools." : "";
  return `Flow ${state.flow}, as recorded by attempt_started. Solid edges were taken by the selected point; `
    + `dashed edges were not.${capture}`;
}
