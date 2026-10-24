import type { ArgSchema, ArgValues, GeneratorSchema } from "./protocol";

/** Builds the parameter form from a generator's argparse schema. */
export class ParamForm {
  private inputs = new Map<string, { arg: ArgSchema; el: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement }>();

  constructor(
    private root: HTMLElement,
    private onChange: () => void,
  ) {}

  build(schema: GeneratorSchema, initial: ArgValues = {}) {
    this.inputs.clear();
    this.root.replaceChildren();
    for (const group of schema.groups) {
      const details = document.createElement("details");
      details.open = !group.collapsed;
      const summary = document.createElement("summary");
      summary.textContent = group.title;
      details.append(summary);
      for (const arg of group.args) details.append(this.row(arg, initial[arg.name]));
      this.root.append(details);
    }
  }

  /** All current values, as strings boxes understands. */
  values(): ArgValues {
    const out: ArgValues = {};
    for (const [name, { arg, el }] of this.inputs) {
      out[name] = arg.kind === "bool" ? ((el as HTMLInputElement).checked ? "1" : "0") : el.value;
    }
    return out;
  }

  /** Only the values that differ from the defaults (for the URL). */
  changedValues(): ArgValues {
    const all = this.values();
    const out: ArgValues = {};
    for (const [name, { arg }] of this.inputs) {
      if (all[name] !== defaultString(arg)) out[name] = all[name];
    }
    return out;
  }

  get(name: string): string | undefined {
    return this.values()[name];
  }

  /** Sets one parameter (e.g. from a dimension in the 3D view) and re-renders, unless !notify. */
  set(name: string, value: string, notify = true) {
    const input = this.inputs.get(name);
    if (!input) return;
    setValue(input.arg, input.el, value);
    if (notify) this.onChange();
  }

  /** Changed values without the given parameters (e.g. ones derived from others). */
  changedValuesExcept(...names: string[]): ArgValues {
    const out = this.changedValues();
    for (const name of names) delete out[name];
    return out;
  }

  reset() {
    for (const { arg, el } of this.inputs.values()) setValue(arg, el, defaultString(arg));
    this.onChange();
  }

  private row(arg: ArgSchema, initial: string | undefined): HTMLElement {
    const row = document.createElement("div");
    row.className = `param param-${arg.kind}`;
    const id = `arg-${arg.name}`;

    const label = document.createElement("label");
    label.htmlFor = id;
    label.textContent = arg.label;

    let el: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
    if (arg.kind === "bool") {
      el = document.createElement("input");
      el.type = "checkbox";
    } else if (arg.kind === "select") {
      el = document.createElement("select");
      for (const [value, text] of arg.options) el.add(new Option(text, value));
    } else if (arg.kind === "textarea") {
      el = document.createElement("textarea");
      el.rows = Math.max(3, arg.default.split("\n").length + 1);
    } else {
      el = document.createElement("input");
      el.type = "text";
      el.spellcheck = false;
    }
    el.id = id;
    el.name = arg.name;
    setValue(arg, el, initial ?? defaultString(arg));
    el.addEventListener(arg.kind === "bool" || arg.kind === "select" ? "change" : "input", this.onChange);
    this.inputs.set(arg.name, { arg, el });

    row.append(label, el);
    if (arg.help) {
      const help = document.createElement("small");
      help.textContent = stripMarkdown(arg.help);
      row.append(help);
    }
    return row;
  }
}

function defaultString(arg: ArgSchema): string {
  return arg.kind === "bool" ? (arg.default ? "1" : "0") : arg.default;
}

function setValue(arg: ArgSchema, el: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement, value: string) {
  if (arg.kind === "bool") (el as HTMLInputElement).checked = !["", "0", "false", "off", "none"].includes(value.toLowerCase());
  else el.value = value;
  if (el instanceof HTMLTextAreaElement) el.rows = Math.max(3, value.split("\n").length + 1);
}

function stripMarkdown(s: string): string {
  return s.replace(/\*\*(.+?)\*\*/g, "$1").replace(/`(.+?)`/g, "$1").replace(/\[(.+?)\]\(.+?\)/g, "$1");
}
