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
export function kv(parent, key, value) {
    const missing = value === undefined || value === null || value === "";
    const line = el("p", "kv");
    line.append(el("span", "k", key), document.createTextNode(": "), el("span", missing ? "v missing" : "v", display(value)));
    parent.append(line);
}
export function block(parent, title, value, className = "") {
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
    parent.append(el("pre", className, text));
}
