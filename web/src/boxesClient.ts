import type {
  ArgValues,
  AssemblyStatus,
  Dimension,
  GridLine,
  Handle,
  FromWorker,
  GeneratorGroup,
  GeneratorInfo,
  GeneratorSchema,
  RecordedPart,
  ToWorker,
} from "./protocol";

export interface ReadyInfo {
  groups: GeneratorGroup[];
  generators: GeneratorInfo[];
  loadMs: number;
}

export interface RenderResult {
  svg: string;
  parts: RecordedPart[];
  assembly: AssemblyStatus;
  /** Problems with the 3D view that do not stop it (e.g. a bad ramp value). */
  warnings: string[];
  dims: Dimension[];
  handles: Handle[];
  lines: GridLine[];
  thickness: number;
  /** Time spent inside Python. */
  ms: number;
}

export interface PartFile {
  part: number;
  reference: boolean;
  content: string;
}

export interface PrintParts {
  parts: RecordedPart[];
  thickness: number;
}

export class BoxesError extends Error {
  constructor(
    message: string,
    readonly detail: string,
  ) {
    super(message);
  }
}

type Pending = { resolve: (v: any) => void; reject: (e: Error) => void };
type RenderRequest = { generator: string; args: ArgValues } & Pending;

/**
 * Owns the Pyodide worker. Renders are "latest wins": while one render runs,
 * newer requests replace any queued one, and the replaced request resolves to null.
 */
export class BoxesClient {
  readonly ready: Promise<ReadyInfo>;
  onStatus: (text: string) => void = () => {};

  private worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
  private nextId = 1;
  private pending = new Map<number, Pending>();
  private rendering = false;
  private queued: RenderRequest | null = null;

  constructor(wheelBase: string) {
    this.ready = new Promise((resolve, reject) => {
      this.worker.onmessage = (ev: MessageEvent<FromWorker>) => {
        const msg = ev.data;
        if (msg.type === "status") this.onStatus(msg.text);
        else if (msg.type === "ready") resolve(msg);
        else if (msg.type === "error" && msg.id === null) reject(new BoxesError(msg.message, msg.detail));
        else this.settle(msg);
      };
    });
    this.post({ type: "init", wheelBase });
  }

  schema(generator: string): Promise<GeneratorSchema> {
    return this.request((id) => ({ type: "schema", id, generator }));
  }

  exportFormat(generator: string, args: ArgValues, format: string): Promise<string> {
    return this.request((id) => ({ type: "export", id, generator, args, format }));
  }

  /** One file per part, `part` being the index of its `<g id="p-N">` in the full SVG. */
  async exportParts(generator: string, args: ArgValues, format: string): Promise<PartFile[]> {
    return JSON.parse(await this.exportFormat(generator, args, `${format}-parts`));
  }

  /** The parts without burn compensation, shrunk for `clearance` mm of play per joint (for STL). */
  printParts(generator: string, args: ArgValues, clearance: number): Promise<PrintParts> {
    return this.request((id) => ({ type: "printParts", id, generator, args, clearance }));
  }

  render(generator: string, args: ArgValues): Promise<RenderResult | null> {
    return new Promise((resolve, reject) => {
      this.queued?.resolve(null);
      this.queued = { generator, args, resolve, reject };
      this.pump();
    });
  }

  private pump() {
    if (this.rendering || !this.queued) return;
    const { generator, args, resolve, reject } = this.queued;
    this.queued = null;
    this.rendering = true;
    this.request<RenderResult>((id) => ({ type: "render", id, generator, args }))
      .then(resolve, reject)
      .finally(() => {
        this.rendering = false;
        this.pump();
      });
  }

  private request<T>(build: (id: number) => ToWorker): Promise<T> {
    const id = this.nextId++;
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.post(build(id));
    });
  }

  private settle(msg: Exclude<FromWorker, { type: "status" | "ready" }>) {
    if (msg.id === null) return;
    const p = this.pending.get(msg.id);
    if (!p) return;
    this.pending.delete(msg.id);
    if (msg.type === "error") p.reject(new BoxesError(msg.message, msg.detail));
    else if (msg.type === "schema") p.resolve(msg.schema);
    else if (msg.type === "exported") p.resolve(msg.content);
    else if (msg.type === "printParts") p.resolve({ parts: msg.parts, thickness: msg.thickness });
    else {
      const { svg, parts, assembly, dims, handles, lines, thickness, ms } = msg;
      p.resolve({ svg, parts, assembly, dims, handles, lines, thickness, ms });
    }
  }

  private post(msg: ToWorker) {
    this.worker.postMessage(msg);
  }
}
