// @vitest-environment happy-dom
import { describe, expect, test } from "vitest";
import { parseSvg } from "../../src/svg";

const wrap = (body: string, attrs = "") =>
  `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="10mm" ${attrs}>${body}</svg>`;

describe("parseSvg", () => {
  test("keeps the drawing", () => {
    const svg = parseSvg(
      wrap('<title>Box</title><g id="p-0" transform="translate(1 2)"><path d="M0 0L1 1" style="stroke:#f00"/><text font-size="2">A</text></g>'),
    );
    expect(svg.getAttribute("width")).toBe("10mm");
    expect(svg.querySelector("#p-0")?.getAttribute("transform")).toBe("translate(1 2)");
    expect(svg.querySelector("path")?.getAttribute("style")).toBe("stroke:#f00");
    expect(svg.querySelector("text")?.textContent).toBe("A");
  });

  test("drops scripts, foreign content and unknown elements", () => {
    const svg = parseSvg(
      wrap(
        '<script>alert(1)</script><foreignObject><div xmlns="http://www.w3.org/1999/xhtml">x</div></foreignObject>' +
          '<g><image href="https://example.com/a.png"/><animate attributeName="href" to="javascript:alert(1)"/>' +
          '<path d="M0 0"/></g><metadata><x/></metadata>',
      ),
    );
    expect([...svg.querySelectorAll("*")].map((e) => e.localName)).toEqual(["g", "path"]);
  });

  test("drops event handlers, external links and url() references", () => {
    const svg = parseSvg(
      wrap(
        '<g onclick="alert(1)" ONMOUSEOVER="x"><path id="a" d="M0 0" style="fill:url(https://e.com/x)"/>' +
          '<path d="M0 0" style="fill:url(#grad)"/></g>' +
          '<a href="javascript:alert(1)"/><text xlink:href="https://e.com">t</text>',
        'onload="alert(1)"',
      ),
    );
    expect(svg.hasAttribute("onload")).toBe(false);
    const g = svg.querySelector("g")!;
    expect(g.attributes.length).toBe(0);
    const [ext, local] = svg.querySelectorAll("path");
    expect(ext.hasAttribute("style")).toBe(false);
    expect(local.getAttribute("style")).toBe("fill:url(#grad)");
    expect(svg.querySelector("text")?.hasAttribute("xlink:href")).toBe(false);
  });

  test("rejects documents that are not SVG", () => {
    expect(() => parseSvg("<svg")).toThrow(/invalid SVG/);
    expect(() => parseSvg('<html xmlns="http://www.w3.org/1999/xhtml"/>')).toThrow(/invalid SVG/);
  });
});
