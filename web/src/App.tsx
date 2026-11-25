import { useEffect, useMemo, useRef, useState } from "react";
import { Chart } from "./components/Chart";
import { Settings } from "./components/Settings";
import { type Answer, loadSettings, type ModelSettings, type Ready, Runtime, saveSettings } from "./runtime";

type Entry = { id: number; question: string; answer?: Answer; error?: string };

const fmtCell = (v: string | number | null) => {
  if (v === null) return "–";
  if (typeof v === "number") {
    if (Number.isInteger(v)) return v.toLocaleString("en-AU");
    if (Math.abs(v) < 1) return `${(v * 100).toFixed(1)}%`;
    return v.toLocaleString("en-AU", { maximumFractionDigits: 2 });
  }
  return v;
};

// "Promo uplift (units per store-week, promo vs non-promo), by category" -> the metric part, brackets intact.
const captionFrom = (reason: string) => reason.match(/^[^,(]*(\([^)]*\))?/)?.[0].trim() || reason;

export default function App() {
  const runtime = useMemo(() => new Runtime(), []);
  const [ready, setReady] = useState<Ready | null>(null);
  const [bootText, setBootText] = useState("Opening the store…");
  const [bootError, setBootError] = useState("");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [settings, setSettings] = useState<ModelSettings>(loadSettings);
  const [showSettings, setShowSettings] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const nextId = useRef(1);

  useEffect(() => {
    runtime.onProgress = setBootText;
    runtime.ready().then(setReady, (e: Error) => setBootError(e.message));
  }, [runtime]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [entries]);

  async function ask(q: string) {
    q = q.trim();
    if (!q || busy || !ready) return;
    const id = nextId.current++;
    setEntries((e) => [...e, { id, question: q }]);
    setQuestion("");
    setBusy(true);
    try {
      const answer = await runtime.ask(q, settings);
      setEntries((e) => e.map((x) => (x.id === id ? { ...x, answer } : x)));
    } catch (err) {
      setEntries((e) => e.map((x) => (x.id === id ? { ...x, error: (err as Error).message } : x)));
    } finally {
      setBusy(false);
    }
  }

  const modelLabel =
    settings.provider === "anthropic" && settings.api_key
      ? "Claude connected"
      : settings.provider === "azure" && settings.api_key
        ? "Azure AI Foundry connected"
        : "No AI model: common questions only";

  return (
    <div className="store">
      <header className="aisle-sign">
        <div className="hanger" aria-hidden />
        <div className="sign-body">
          <div className="aisle-no" aria-hidden>
            <span>Aisle</span>
            <b>7</b>
          </div>
          <div>
            <h1>ShelfTalk</h1>
            <p>Ask Bluegum Market's sales data anything, in plain English.</p>
          </div>
          <button className="model-chip" onClick={() => setShowSettings(true)}>
            <span className={settings.api_key ? "led on" : "led"} aria-hidden />
            {modelLabel}
          </button>
        </div>
      </header>

      <main className="aisle">
        {!ready ? (
          <section className="booting" aria-live="polite">
            {bootError ? (
              <>
                <h2>The warehouse didn't load</h2>
                <p>{bootError} Reload the page to try again.</p>
              </>
            ) : (
              <>
                <div className="scanner" aria-hidden />
                <p>{bootText}</p>
              </>
            )}
          </section>
        ) : (
          <>
            {entries.length === 0 && (
              <section className="intro">
                <p className="lede">
                  A fictional grocery chain: 28 stores, 77 products, two years of weekly sales from{" "}
                  {ready.first_week} to {ready.last_week}. Pick a question or write your own.
                </p>
                <ul className="talkers">
                  {ready.suggestions.map((s) => (
                    <li key={s}>
                      <button onClick={() => ask(s)}>{s}</button>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <ol className="feed">
              {entries.map((e) => (
                <li key={e.id} className="exchange">
                  <p className="q">{e.question}</p>
                  {e.error ? (
                    <div className="ticket ticket-error">
                      <p>{e.error}</p>
                    </div>
                  ) : e.answer ? (
                    <AnswerTicket a={e.answer} onSettings={() => setShowSettings(true)} />
                  ) : (
                    <div className="ticket ticket-pending" aria-live="polite">
                      <div className="scanner small" aria-hidden />
                      Checking the shelves…
                    </div>
                  )}
                </li>
              ))}
            </ol>
            <div ref={endRef} />
          </>
        )}
      </main>

      <form
        className="ask-bar"
        onSubmit={(ev) => {
          ev.preventDefault();
          ask(question);
        }}
      >
        <label htmlFor="q" className="sr-only">
          Your question
        </label>
        <input
          id="q"
          value={question}
          maxLength={500}
          onChange={(ev) => setQuestion(ev.target.value)}
          placeholder={ready ? "Which category had the best promo uplift?" : "Loading…"}
          disabled={!ready}
          autoComplete="off"
        />
        <button type="submit" disabled={!ready || busy || !question.trim()}>
          Ask
        </button>
      </form>

      {showSettings && (
        <Settings
          value={settings}
          onClose={() => setShowSettings(false)}
          onSave={(s) => {
            setSettings(s);
            saveSettings(s);
            setShowSettings(false);
          }}
        />
      )}
    </div>
  );
}

function AnswerTicket({ a, onSettings }: { a: Answer; onSettings: () => void }) {
  const [open, setOpen] = useState(false);
  const r = a.result;
  const chart = a.chart.type !== "none" && r && a.chart.x && a.chart.y ? a.chart : null;
  return (
    <article className={`ticket ticket-${a.source}`}>
      <p className="answer">{a.text}</p>
      {a.source === "none" && (
        <button className="link" onClick={onSettings}>
          Connect a model
        </button>
      )}
      {a.ungrounded.length > 0 && (
        <p className="warn">
          Check these: {a.ungrounded.join(", ")} {a.ungrounded.length === 1 ? "doesn't" : "don't"} match any
          query result.
        </p>
      )}
      {chart && r && (
        <Chart
          type={chart.type as "bar" | "line"}
          columns={r.columns}
          rows={r.rows}
          x={chart.x!}
          y={chart.y!}
          caption={a.source === "planner" ? captionFrom(a.reason) : undefined}
        />
      )}
      {a.source !== "none" && (
        <footer className="ticket-foot">
          <span className="barcode" aria-hidden />
          <span>
            {a.source === "planner" ? "Semantic planner" : a.model} · {Math.round(a.latency_ms).toLocaleString()} ms
            {a.input_tokens ? ` · ${(a.input_tokens + a.output_tokens).toLocaleString()} tokens` : ""}
          </span>
          <button className="link" onClick={() => setOpen(!open)} aria-expanded={open}>
            {open ? "Hide working" : "Show working"}
          </button>
        </footer>
      )}
      {open && (
        <div className="working">
          {a.steps.map((s, i) => (
            <div key={i} className="step">
              {s.kind === "plan" ? (
                <p>
                  <b>Plan</b> {s.detail}
                </p>
              ) : (
                <>
                  {s.purpose && <p className="purpose">{s.purpose}</p>}
                  <pre>{s.detail}</pre>
                  <p className="meta">
                    {s.error ? `Refused: ${s.error}` : `${s.rows ?? 0} rows in ${s.ms ?? 0} ms`}
                  </p>
                </>
              )}
            </div>
          ))}
          {r && r.rows.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {r.columns.map((c) => (
                      <th key={c}>{c.replaceAll("_", " ")}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {r.rows.slice(0, 25).map((row, i) => (
                    <tr key={i}>
                      {row.map((v, j) => (
                        <td key={j} className={typeof v === "number" ? "num" : ""}>
                          {fmtCell(v)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {r.rows.length > 25 && <p className="meta">First 25 of {r.rows.length} rows.</p>}
            </div>
          )}
        </div>
      )}
    </article>
  );
}
