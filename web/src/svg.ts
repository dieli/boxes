// The generator's SVG goes into the page as live DOM, so only plain drawing survives: an
// allowlist of SVG elements, no event handlers, no links or url() references to anything but
// fragments of the same document. Our own generators never emit more than that.

const SVG_NS = "http://www.w3.org/2000/svg";
const ELEMENTS = new Set([
  "svg", "g", "path", "text", "tspan", "title", "desc", "defs",
  "line", "polyline", "polygon", "rect", "circle", "ellipse",
]);
const LINK_ATTRS = new Set(["href", "xlink:href"]);
// url(...) pointing anywhere but "#id".
const EXTERNAL_URL = /url\s*\(\s*['"]?\s*(?!#)/i;

/** Removes everything outside the allowlist from `root` (in place) and returns it. */
export function sanitizeSvg(root: Element): Element {
  const walk = (el: Element) => {
    for (const child of [...el.children]) {
      if (child.namespaceURI !== SVG_NS || !ELEMENTS.has(child.localName)) child.remove();
      else walk(child);
    }
    for (const attr of [...el.attributes]) {
      const name = attr.name.toLowerCase();
      const value = attr.value.trim();
      if (
        name.startsWith("on") ||
        (LINK_ATTRS.has(name) && !value.startsWith("#")) ||
        EXTERNAL_URL.test(value) ||
        /^\s*javascript:/i.test(value)
      ) {
        el.removeAttribute(attr.name);
      }
    }
  };
  walk(root);
  return root;
}

/** Parses and sanitizes an SVG document; throws if it is not valid SVG. */
export function parseSvg(text: string): Element {
  const doc = new DOMParser().parseFromString(text, "image/svg+xml");
  const root = doc.documentElement;
  if (doc.querySelector("parsererror") || root.namespaceURI !== SVG_NS || root.localName !== "svg") {
    throw new Error("The generator produced an invalid SVG");
  }
  return sanitizeSvg(root);
}
