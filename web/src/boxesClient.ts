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

type Pending = { resolve: (v: unknown) => void; reject: (e: Error) => void };
type RenderRequest = {
  generator: string;
  args: ArgValues;
  resolve: (v: RenderResult | null) => void;
  reject: (e: Error) => void;
};

/**
 * Owns the Pyodide worker. Renders are "latest wins": while one render runs,
 * newer requests replace any queued one, and the replaced request resolves to null.
 *
 * A request that runs longer than `timeoutMs`, or a worker that dies, rejects the pending
 * requests and starts a fresh worker (reloading Python takes a few seconds); requests made
 * meanwhile wait for it. The worker answers in order, so the time limit applies to the oldest
 * pending request, from when the one before it was answered. A worker that fails while loading
 * is not restarted: the first one rejects `ready`, a replacement calls `onRestartFailed`.
 */
export class BoxesClient {
  readonly ready: Promise<ReadyInfo>;
  onStatus: (text: string) => void = () => {};
  /** The worker was replaced (reason given); the new one reports progress through onStatus. */
  onRestart: (reason: string) => void = () => {};
  /** The replacement worker failed to load; every request fails from now on. */
  onRestartFailed: (error: Error) => void = () => {};
  timeoutMs = 30_000;

  private worker!: Worker;
  private started!: Promise<ReadyInfo>;
  private nextId = 1;
  private pending = new Map<number, Pending>();
  private rendering = false;
  private queued: RenderRequest | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;

  constructor(
    private wheelBase: string,
    private pyodideBase: string,
  ) {
    this.ready = this.start();
  }

  private start(): Promise<ReadyInfo> {
    const worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
    this.worker = worker;
    let loaded = false;
    this.started = new Promise((resolve, reject) => {
      worker.onmessage = (ev: MessageEvent<FromWorker>) => {
        const msg = ev.data;
        if (msg.type === "status") this.onStatus(msg.text);
        else if (msg.type === "ready") {
          loaded = true;
          resolve(msg);
        } else if (msg.type === "error" && msg.id === null) reject(new BoxesError(msg.message, msg.detail));
        else this.settle(msg);
      };
      const fail = (message: string) => {
        if (!loaded) {
          worker.terminate();
          reject(new BoxesError(message, message));
        } else this.restart(worker, message);
      };
      worker.onerror = (ev) => {
        ev.preventDefault();
        fail(`The Python worker crashed: ${ev.message || "unknown error"}`);
      };
      worker.onmessageerror = () => fail("The Python worker sent a message that could not be read");
    });
    worker.postMessage({ type: "init", wheelBase: this.wheelBase, pyodideBase: this.pyodideBase } satisfies ToWorker);
    return this.started;
  }

  /** Stops `worker` (if still the current one), fails its requests and starts a new one. */
  private restart(worker: Worker, reason: string) {
    if (worker !== this.worker) return;
    worker.terminate();
    const error = new BoxesError(reason, reason);
    const pending = [...this.pending.values()];
    this.pending.clear();
    this.armTimer();
    this.start().then(
      () => this.onStatus("Python restarted"),
      (e: Error) => this.onRestartFailed(e), // also rejects the requests that wait for it
    );
    this.onRestart(reason);
    for (const p of pending) p.reject(error);
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
    return this.started.then(
      () =>
        new Promise<T>((resolve, reject) => {
          const id = this.nextId++;
          this.pending.set(id, { resolve: (v) => resolve(v as T), reject });
          if (this.pending.size === 1) this.armTimer();
          this.worker.postMessage(build(id));
        }),
    );
  }

  /** Starts the time limit for the oldest pending request (the one the worker is running). */
  private armTimer() {
    clearTimeout(this.timer);
    this.timer = undefined;
    if (!this.pending.size) return;
    const worker = this.worker;
    this.timer = setTimeout(
      () => this.restart(worker, `Stopped after ${this.timeoutMs / 1000} s: the generator took too long. Restarting Python…`),
      this.timeoutMs,
    );
  }

  private settle(msg: Exclude<FromWorker, { type: "status" | "ready" }>) {
    if (msg.id === null) return;
    const p = this.pending.get(msg.id);
    if (!p) return;
    this.pending.delete(msg.id);
    this.armTimer();
    if (msg.type === "error") p.reject(new BoxesError(msg.message, msg.detail));
    else if (msg.type === "schema") p.resolve(msg.schema);
    else if (msg.type === "exported") p.resolve(msg.content);
    else if (msg.type === "printParts") p.resolve({ parts: msg.parts, thickness: msg.thickness });
    else {
      const { svg, parts, assembly, warnings, dims, handles, lines, thickness, ms } = msg;
      p.resolve({ svg, parts, assembly, warnings, dims, handles, lines, thickness, ms } satisfies RenderResult);
    }
  }
}
