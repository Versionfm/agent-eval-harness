// Connection to one attempt's SSE stream: sequence ledger (dedupe, gaps, conflicts), connection state
// and lag against the latest sequence the server has reported. Evidence never touches the DOM here;
// timeline.ts renders it with textContent.

export interface TrackerEvent {
  schema: string;
  schema_version: number;
  attempt_id: string;
  sequence: number;
  type: string;
  operation_id?: string;
  data: Record<string, any>;
  artifacts: { role: string; path: string; bytes: number; sha256: string }[];
}

export type Accepted =
  | { kind: "new"; gap?: [number, number] }
  | { kind: "duplicate" }
  | { kind: "conflict"; message: string };

export type State = "connecting" | "live" | "reconnecting" | "refused" | "conflict" | "recording-error" | "finished";

export interface Progress {
  state: State;
  detail: string;
  displayed: number;
  latest: number;
}

export interface FeedHandlers {
  onAccepted(event: TrackerEvent, accepted: Accepted): void;
  onProgress(progress: Progress): void;
}

const SCHEMA = "agent-eval-harness/attempt-events";

// What was displayed, by sequence. The same bytes again are a duplicate; different content for a
// sequence, another attempt or an unknown schema is a conflict and stops the feed.
export class Ledger {
  private readonly canonical: (string | undefined)[] = [];
  private highest = 0;

  constructor(private readonly attemptId: string) {}

  get displayed(): number {
    return this.highest;
  }

  accept(event: TrackerEvent): Accepted {
    if (event.schema !== SCHEMA || event.schema_version !== 1) {
      return { kind: "conflict", message: `event ${event.sequence} has an unsupported schema` };
    }
    if (event.attempt_id !== this.attemptId) {
      return { kind: "conflict", message: `event ${event.sequence} belongs to another attempt` };
    }
    const text = JSON.stringify(event);
    if (event.sequence <= this.highest) {
      if (this.canonical[event.sequence - 1] === text) {
        return { kind: "duplicate" };
      }
      return { kind: "conflict", message: `sequence ${event.sequence} conflicts with what was displayed` };
    }
    const gap: [number, number] | undefined =
      event.sequence > this.highest + 1 ? [this.highest + 1, event.sequence - 1] : undefined;
    this.canonical[event.sequence - 1] = text;
    this.highest = event.sequence;
    return { kind: "new", gap };
  }
}

// ponytail: lag polls /api/attempts while the stream is down; a dedicated head endpoint is the upgrade.
const LAG_POLL_MILLISECONDS = 1000

export function follow(attemptId: string, handlers: FeedHandlers): void {
  const ledger = new Ledger(attemptId);
  const base = `/api/attempts/${encodeURIComponent(attemptId)}`;
  let latest = 0;
  let timer: number | undefined;

  const report = (state: State, detail = "") =>
    handlers.onProgress({ state, detail, displayed: ledger.displayed, latest: Math.max(latest, ledger.displayed) });

  // While the stream is down, learn how far the recording has got, if the viewer is reachable.
  const pollLatest = async () => {
    let detail = "viewer reachable; resuming the stream";
    try {
      const attempts = (await (await fetch("/api/attempts")).json()) as { attempt_id: string; event_count?: number }[];
      const mine = attempts.find((item) => item.attempt_id === attemptId);
      if (mine?.event_count !== undefined) {
        latest = Math.max(latest, mine.event_count);
      }
    } catch {
      detail = "viewer unreachable; lag is against the last reported sequence";
    }
    report("reconnecting", detail);
  };
  const stopPolling = () => {
    window.clearInterval(timer);
    timer = undefined;
  };

  const source = new EventSource(`${base}/stream?after=0`);
  source.onopen = () => {
    stopPolling();
    report("live");
  };
  source.addEventListener("attempt-event", (message) => {
    const event = JSON.parse((message as MessageEvent).data) as TrackerEvent;
    const accepted = ledger.accept(event);
    if (accepted.kind === "conflict") {
      source.close();
      handlers.onAccepted(event, accepted);
      report("conflict", accepted.message);
      return;
    }
    latest = Math.max(latest, event.sequence);
    handlers.onAccepted(event, accepted);
    if (accepted.kind === "new" && event.type === "attempt_finished") {
      source.close();
      report("finished");
      return;
    }
    report("live");
  });
  source.addEventListener("head", (message) => {
    latest = Math.max(latest, (JSON.parse((message as MessageEvent).data) as { latest_sequence: number }).latest_sequence);
    report("live");
  });
  source.addEventListener("recording-error", (message) => {
    source.close();
    report("recording-error", (JSON.parse((message as MessageEvent).data) as { error: string }).error);
  });
  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED) {
      // Refused before streaming (incompatible cursor or unknown attempt): show the explicit error.
      fetch(`${base}/events?after=${ledger.displayed}`)
        .then((response) => response.json())
        .then((body: { error?: string }) => report("refused", body.error ?? "stream refused"))
        .catch(() => report("refused", "stream refused and the viewer did not answer"));
      return;
    }
    // The browser retries with Last-Event-ID, so the stream resumes from the displayed sequence.
    report("reconnecting", `stream interrupted; resuming after #${ledger.displayed}`);
    if (timer === undefined) {
      void pollLatest();
      timer = window.setInterval(() => void pollLatest(), LAG_POLL_MILLISECONDS);
    }
  };
}
