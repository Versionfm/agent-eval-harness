// Component map (left pane): one button per registered component, with its event count.

import { COMPONENTS, TrackerEvent, componentOf } from "./model.js";
import { el } from "./dom.js";

export function buildComponentMap(nav: HTMLElement, onSelect: (id: string) => void): void {
  for (const component of COMPONENTS) {
    const button = el("button");
    button.type = "button";
    button.dataset.component = component.id;
    button.append(document.createTextNode(component.label), " ", el("span", "count"));
    button.querySelector(".count")!.setAttribute("data-count", component.id);
    button.addEventListener("click", () => onSelect(component.id));
    nav.append(button);
  }
}

export function updateComponentCounts(nav: HTMLElement, events: TrackerEvent[]): void {
  for (const component of COMPONENTS) {
    const count = events.filter((event) => componentOf(event) === component.id).length;
    const badge = nav.querySelector(`[data-count="${component.id}"]`);
    if (badge) {
      badge.textContent = String(count);
    }
  }
}
