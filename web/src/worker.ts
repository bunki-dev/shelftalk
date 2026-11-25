// Runs ShelfTalk's Python (planner, guarded SQLite warehouse, LLM agent) in a Web Worker with Pyodide.

const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v314.0.8/full/";
const BUNDLE_URL = `${import.meta.env.BASE_URL}data/shelftalk.zip?v=${import.meta.env.VITE_BUNDLE_VERSION ?? "dev"}`;
const APP_DIR = "/home/pyodide/app";

interface Pyodide {
  loadPackage(names: string[]): Promise<void>;
  unpackArchive(buffer: ArrayBuffer, format: string, options: { extractDir: string }): void;
  runPython(code: string): unknown;
  runPythonAsync(code: string): Promise<unknown>;
  globals: { set(name: string, value: unknown): void };
}

type Request = { id: number; method: "ready" | "ask"; args: unknown[] };

const ctx = self as unknown as {
  postMessage(message: unknown): void;
  onmessage: ((event: MessageEvent<Request>) => void) | null;
};
const progress = (text: string) => ctx.postMessage({ type: "progress", text });

async function boot(): Promise<{ py: Pyodide; info: unknown }> {
  progress("Loading the Python runtime (first visit only)…");
  const { loadPyodide } = await import(/* @vite-ignore */ `${PYODIDE_URL}pyodide.mjs`);
  const py: Pyodide = await loadPyodide({ indexURL: PYODIDE_URL });
  progress("Loading SQLite and YAML…");
  await py.loadPackage(["sqlite3", "pyyaml"]);
  progress("Stocking the shelves: 220,000 rows of sales…");
  const res = await fetch(BUNDLE_URL);
  if (!res.ok) throw new Error(`Couldn't download the warehouse (${res.status}).`);
  py.unpackArchive(await res.arrayBuffer(), "zip", { extractDir: APP_DIR });
  const info = py.runPython(
    `import sys; sys.path.insert(0, "${APP_DIR}"); import shelftalk.browser as st; st.init("${APP_DIR}/shelftalk.db")`,
  );
  return { py, info: JSON.parse(String(info)) };
}

const booted = boot();

ctx.onmessage = async (event: MessageEvent<Request>) => {
  const { id, method, args } = event.data;
  try {
    const { py, info } = await booted;
    if (method === "ready") {
      ctx.postMessage({ type: "result", id, result: info });
      return;
    }
    py.globals.set("_q", args[0]);
    py.globals.set("_settings", JSON.stringify(args[1] ?? {}));
    const out = await py.runPythonAsync("await st.ask(_q, _settings)");
    ctx.postMessage({ type: "result", id, result: JSON.parse(String(out)) });
  } catch (e) {
    ctx.postMessage({ type: "result", id, error: (e as Error).message ?? String(e) });
  }
};
