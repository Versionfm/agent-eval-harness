// Small DOM helpers. Evidence only ever reaches the page through textContent.

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K, className = "", text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text !== undefined) {
    node.textContent = text;
  }
  return node;
}

export function display(value: unknown): string {
  if (value === undefined || value === null || value === "") {
    return "not recorded";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

export function count(value: unknown): string {
  return typeof value === "number" ? value.toLocaleString("en-US") : display(value);
}

// A cost summary as recorded: the amount with its status, never a missing amount shown as zero.
export function money(cost: any): string {
  if (typeof cost?.amount !== "number") {
    return display(cost?.status);
  }
  const missing = cost.missing_usage_calls ?? cost.missing_charge_calls;
  return `${cost.amount.toFixed(5)} ${cost.currency ?? ""} ${cost.status}` + (missing ? `, ${missing} calls missing` : "");
}

// One labelled value on a single line, so text reads "key: value" in the page.
// `field` names the value for tests and cross-checks (data-field); it never changes what is shown.
export function kv(parent: Element, key: string, value: unknown, field?: string): void {
  const missing = value === undefined || value === null || value === "";
  const line = el("p", "kv");
  const shown = el("span", missing ? "v missing" : "v", display(value));
  if (field) {
    shown.dataset.field = field;
  }
  line.append(el("span", "k", key), el("span", "sep", ": "), shown);
  parent.append(line);
}

export function block(parent: Element, title: string, value: unknown, className = "", field?: string): void {
  parent.append(el("h4", "", title));
  let text: string;
  if (value === undefined || value === null) {
    text = "not recorded";
  } else if (typeof value === "string") {
    text = value;
  } else {
    text = JSON.stringify(value, null, 2);
  }
  const pre = el("pre", className, text);
  if (field) {
    pre.dataset.field = field;
  }
  parent.append(pre);
}
