// Talks to the Python worker. Everything runs in the browser: no server.

export interface Answer {
  question: string;
  text: string;
  source: "planner" | "llm" | "none";
  sql: string[];
  result: { columns: string[]; rows: (string | number | null)[][]; row_count: number; truncated: boolean } | null;
  chart: { type: "none" | "bar" | "line"; x?: string; y?: string };
  ungrounded: string[];
  steps: { kind: string; detail: string; purpose?: string; error?: string; ms?: number; rows?: number }[];
  reason: string;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  model: string;
}

export interface Ready {
  suggestions: string[];
  first_week: string;
  last_week: string;
}

export interface ModelSettings {
  provider: "none" | "anthropic" | "azure";
  api_key: string;
  model: string;
  endpoint: string;
  deployment: string;
}

export const DEFAULT_SETTINGS: ModelSettings = {
  provider: "none",
  api_key: "",
  model: "claude-sonnet-5-5",
  endpoint: "",
  deployment: "",
};

const SETTINGS_KEY = "shelftalk.settings";

export function loadSettings(): ModelSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    return raw ? { ...DEFAULT_SETTINGS, ...JSON.parse(raw) } : { ...DEFAULT_SETTINGS };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export function saveSettings(s: ModelSettings) {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
  } catch {
    /* settings last for this visit only */
  }
}

export class Runtime {
  private worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
  private pending = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>();
  private nextId = 1;
  onProgress: (text: string) => void = () => {};

  constructor() {
    this.worker.onmessage = (event: MessageEvent) => {
      const msg = event.data;
      if (msg.type === "progress") return this.onProgress(msg.text);
      const p = this.pending.get(msg.id);
      if (!p) return;
      this.pending.delete(msg.id);
      if (msg.error) p.reject(new Error(msg.error));
      else p.resolve(msg.result);
    };
  }

  private call<T>(method: string, ...args: unknown[]): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      const id = this.nextId++;
      this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject });
      this.worker.postMessage({ id, method, args });
    });
  }

  ready = () => this.call<Ready>("ready");
  ask = (question: string, settings: ModelSettings) => this.call<Answer>("ask", question, settings);
}
