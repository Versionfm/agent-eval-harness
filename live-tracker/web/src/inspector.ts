// Inspector (right pane): selected event or component, selected-point state, retained artifacts.
// Evidence is rendered with textContent. Excerpts are labelled; full output stays one link away.

import { ARTIFACT_PATH, ComponentInfo, OPERATION_STARTS, TrackerEvent, selectedPointState } from "./model.js";
import { block, display, el, kv } from "./dom.js";

const EXCERPT_CHARS = 2000;

interface SourceRecord {
  identity: string;
  file: string;
  line: number;
  end_line: number;
  responsibility: string;
  text: string;
}

export class Inspector {
  private token = 0;
  private readonly artifacts = new Map<string, Promise<string>>();
  private readonly sources = new Map<string, Promise<SourceRecord>>();

  constructor(
    private readonly attemptId: string,
    private readonly panel: HTMLElement,
    private readonly stateSection: HTMLElement,
    private readonly evidence: HTMLElement,
  ) {}

  async showComponent(component: ComponentInfo, eventCount: number): Promise<void> {
    const token = ++this.token;
    const root = el("div");
    root.append(el("h2", "", component.label));
    kv(root, "component", component.id);
    kv(root, "source identity", component.identity);
    kv(root, "events from this component", eventCount);
    await this.attachSource(root, component.identity);
    if (token === this.token) {
      this.panel.replaceChildren(root);
    }
  }

  async showEvent(events: TrackerEvent[], event: TrackerEvent): Promise<void> {
    const token = ++this.token;
    this.renderState(events, event);
    this.renderEvidence(event);
    const root = el("div");
    root.append(el("h2", "", `#${event.sequence} ${event.type}`));
    kv(root, "sequence", event.sequence);
    kv(root, "timestamp", event.timestamp);
    kv(root, "elapsed_seconds", event.elapsed_seconds);
    kv(root, "operation_id", event.operation_id);
    kv(root, "parent_operation_id", event.parent_operation_id);
    if (OPERATION_STARTS.has(event.type)) {
      const outcome = events.find((item) => item.operation_id === event.operation_id && !OPERATION_STARTS.has(item.type));
      kv(root, "outcome", outcome ? `recorded at #${outcome.sequence} (${outcome.type})`
        : "not recorded: waiting, or unresolved once the attempt has finished");
    }
    if (event.legacy) {
      root.append(el("p", "note", "Legacy trace record, shown as recorded. Nothing was added or re-timed."));
    }
    if (event.labels) {
      kv(root, "not recorded for this event", event.labels.unavailable.join(", ") || "none");
      kv(root, "derived (computed now from saved bytes)", event.labels.derived.join(", ") || "none");
      kv(root, "inline in the legacy trace", event.labels.inline.join(", ") || "none");
    }
    try {
      await this.renderBody(root, event);
    } catch (error) {
      kv(root, "detail", `not available (${String(error)})`);
    }
    if (token === this.token) {
      this.panel.replaceChildren(root);
    }
  }

  private renderState(events: TrackerEvent[], event: TrackerEvent): void {
    const root = el("div");
    root.append(el("h2", "", "State at selected point"));
    const source = selectedPointState(events, event.sequence);
    if (!source && event.legacy) {
      root.append(el("p", "note", "unavailable: the legacy trace records no selected-point state snapshots."));
    } else if (!source) {
      root.append(el("p", "note", "No state recorded at or before this selection yet."));
    } else {
      const data = source.data;
      const where = data.after_node !== undefined
        ? `graph step ${display(data.graph_step_count)}, after node ${display(data.after_node)}`
        : `loop step ${display(data.loop_step)}, after ${display(data.after_phase)}`;
      root.append(el("p", "note", `from state event #${source.sequence} (${where}); later events are not used`));
      kv(root, "model calls", `${display(data.model_calls)} / ${display(data.max_model_calls)}`);
      kv(root, "context bytes", `${display(data.context_bytes)} / ${display(data.max_context_bytes)}`);
      kv(root, "tool result messages", data.tool_result_messages);
      kv(root, "tool output limit bytes", data.tool_output_limit_bytes);
      kv(root, "attempt deadline seconds", data.attempt_deadline_seconds);
      kv(root, "elapsed seconds at selection", event.elapsed_seconds);
      kv(root, "usage totals", data.usage_totals);
      kv(root, "estimated cost", data.estimated_cost);
      kv(root, "reported cost", data.reported_cost);
    }
    this.stateSection.replaceChildren(root);
  }

  private renderEvidence(event: TrackerEvent): void {
    const root = el("div");
    root.append(el("h2", "", "Retained artifacts"));
    if (event.artifacts.length === 0) {
      root.append(el("p", "note", "No artifacts were recorded for this event."));
    }
    const list = el("ul");
    for (const artifact of event.artifacts) {
      const item = el("li");
      if (!ARTIFACT_PATH.test(artifact.path)) {
        item.append(el("span", "missing", `${artifact.role}: invalid artifact path, not linked`));
        list.append(item);
        continue;
      }
      const link = el("a", "", `${artifact.role} (${artifact.bytes} bytes)`);
      link.dataset.artifact = artifact.role;
      link.href = this.artifactUrl(artifact.path);
      item.append(link, document.createTextNode(" sha256 "), el("code", "", artifact.sha256));
      list.append(item);
    }
    root.append(list);
    this.evidence.replaceChildren(root);
  }

  private async renderBody(root: HTMLElement, event: TrackerEvent): Promise<void> {
    const data = event.data;
    switch (event.type) {
      case "phase.enter":
      case "node.enter":
      case "node.outcome":
      case "route.decision":
        return this.renderSourced(root, event);
      case "model.start":
        kv(root, "model_call", data.model_call);
        kv(root, "message_count", data.message_count);
        root.append(el("p", "note", "The full request messages are in the retained artifact (request.json)."));
        return;
      case "model.outcome":
        return this.renderModelOutcome(root, event);
      case "tool.start":
        kv(root, "tool_name", data.tool_name);
        kv(root, "tool_call_id", data.tool_call_id);
        block(root, "arguments", data.arguments, "", "tool-arguments");
        return;
      case "tool.outcome":
        return this.renderToolOutcome(root, event);
      default:
        block(root, "data", data);
    }
  }

  // Phase, graph node and router events name the registered source function that produced them.
  private async renderSourced(root: HTMLElement, event: TrackerEvent): Promise<void> {
    const data = event.data;
    for (const key of ["phase", "node", "after_node", "next", "reason", "loop_step", "graph_step_count",
      "termination_reason", "max_graph_steps"]) {
      if (data[key] !== undefined) {
        kv(root, key, data[key]);
      }
    }
    kv(root, "source", data.source);
    const link = el("a", "", "registered source record (JSON)");
    link.dataset.source = data.source;
    link.href = `/api/sources?identity=${encodeURI(String(data.source))}`;
    link.target = "_blank";
    link.rel = "noopener";
    const linkLine = el("p");
    linkLine.append(link);
    root.append(linkLine);
    await this.attachSource(root, data.source);
  }

  private async renderModelOutcome(root: HTMLElement, event: TrackerEvent): Promise<void> {
    const data = event.data;
    kv(root, "status", data.status);
    kv(root, "model_call", data.model_call);
    kv(root, "duration_seconds", data.duration_seconds);
    kv(root, "error_category", data.error_category);
    kv(root, "error", data.error);
    kv(root, "retrying", data.retrying);
    const artifact = event.artifacts.find((item) => item.role === "response.json");
    let response: any;
    if (artifact) {
      response = JSON.parse(await this.loadArtifact(artifact.path));
    } else if (data.response !== undefined) {
      // A legacy trace carries the response inline; the labels above say so.
      response = data.response;
    } else {
      kv(root, "provider response", "not recorded (no provider response for this outcome)");
      return;
    }
    root.append(el("h3", "", "Model response"));
    kv(root, "observed_model", response.observed_model);
    block(root, "content", response.content, "", "response-content");
    block(root, "provider-exposed reasoning (reasoning_content, as the provider returned it)",
      response.reasoning_fields?.reasoning_content, "", "reasoning");
    root.append(el("p", "note",
      "This is the reasoning field the provider exposed, not a full record of the model's internal reasoning."));
    const calls: any[] | undefined = response.tool_calls;
    if (calls === undefined) {
      kv(root, "tool calls", undefined);
    } else if (calls.length === 0) {
      kv(root, "tool calls", "none");
    }
    for (const call of calls ?? []) {
      const item = el("div", "call");
      kv(item, "name", call.name);
      kv(item, "call_id", call.call_id);
      block(item, "arguments", call.arguments);
      root.append(item);
    }
    const usage = response.usage ?? {};
    kv(root, "prompt_tokens", usage.prompt_tokens, "prompt-tokens");
    kv(root, "completion_tokens", usage.completion_tokens, "completion-tokens");
    kv(root, "provider_finish_reason", usage.provider_finish_reason);
    if (usage.billing !== undefined) {
      block(root, "billing (as recorded)", usage.billing);
    }
  }

  private async renderToolOutcome(root: HTMLElement, event: TrackerEvent): Promise<void> {
    const data = event.data;
    const result = data.result ?? {};
    const visible = data.model_visible_result ?? {};
    kv(root, "tool_name", data.tool_name);
    kv(root, "tool_call_id", data.tool_call_id);
    kv(root, "status", data.status);
    kv(root, "duration_seconds", data.duration_seconds);
    kv(root, "exit_code", result.exit_code);
    kv(root, "error_category", result.error_category ?? visible.error_category);
    kv(root, "error", result.error);
    root.append(el("h3", "", "Model-visible result (what the model received)"));
    kv(root, "truncated", visible.truncated === undefined ? undefined : visible.truncated ? "yes" : "no");
    block(root, "model-visible output", visible.output, "visible");
    root.append(el("h3", "", "Full retained output"));
    const artifact = event.artifacts.find((item) => item.role === "output.txt");
    if (!artifact) {
      kv(root, "full output", undefined);
      return;
    }
    const full = await this.loadArtifact(artifact.path);
    if (full.length > EXCERPT_CHARS) {
      root.append(el("p", "note",
        `presentation excerpt: the first ${EXCERPT_CHARS} of ${full.length} characters. The complete output is in the retained artifact (output.txt).`));
      block(root, "presentation excerpt", full.slice(0, EXCERPT_CHARS), "excerpt", "full-output");
    } else {
      block(root, `full output (${full.length} characters)`, full, "", "full-output");
    }
  }

  private async attachSource(root: Element, identity: string): Promise<void> {
    try {
      const source = await this.loadSource(identity);
      kv(root, "responsibility", source.responsibility);
      kv(root, "file", `${source.file} lines ${source.line}-${source.end_line}`);
      block(root, "registered source function", source.text, "source");
    } catch (error) {
      kv(root, "source", `not available (${String(error)})`);
    }
  }

  private artifactUrl(path: string): string {
    return `/api/attempts/${encodeURIComponent(this.attemptId)}/artifacts/${path}`;
  }

  private loadArtifact(path: string): Promise<string> {
    if (!ARTIFACT_PATH.test(path)) {
      return Promise.reject(new Error("invalid artifact path"));
    }
    let pending = this.artifacts.get(path);
    if (!pending) {
      pending = fetch(this.artifactUrl(path)).then(async (response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return response.text();
      });
      this.artifacts.set(path, pending);
    }
    return pending;
  }

  private loadSource(identity: string): Promise<SourceRecord> {
    let pending = this.sources.get(identity);
    if (!pending) {
      pending = fetch(`/api/sources?identity=${encodeURI(identity)}`).then(async (response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return (await response.json()) as SourceRecord;
      });
      this.sources.set(identity, pending);
    }
    return pending;
  }
}
