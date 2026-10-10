// Small DOM helpers. Evidence only ever reaches the page through textContent.
export function el(tag, className = "", text) {
    const node = document.createElement(tag);
    if (className) {
        node.className = className;
    }
    if (text !== undefined) {
        node.textContent = text;
    }
    return node;
}
export function display(value) {
    if (value === undefined || value === null || value === "") {
        return "not recorded";
    }
    if (typeof value === "object") {
        return JSON.stringify(value);
    }
    return String(value);
}
// One labelled value on a single line, so text reads "key: value" in the page.
// `field` names the value for tests and cross-checks (data-field); it never changes what is shown.
export function kv(parent, key, value, field) {
    const missing = value === undefined || value === null || value === "";
    const line = el("p", "kv");
    const shown = el("span", missing ? "v missing" : "v", display(value));
    if (field) {
        shown.dataset.field = field;
    }
    line.append(el("span", "k", key), document.createTextNode(": "), shown);
    parent.append(line);
}
export function block(parent, title, value, className = "", field) {
    parent.append(el("h4", "", title));
    let text;
    if (value === undefined || value === null) {
        text = "not recorded";
    }
    else if (typeof value === "string") {
        text = value;
    }
    else {
        text = JSON.stringify(value, null, 2);
    }
    const pre = el("pre", className, text);
    if (field) {
        pre.dataset.field = field;
    }
    parent.append(pre);
}
