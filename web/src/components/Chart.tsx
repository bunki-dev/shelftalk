// Hand-drawn SVG charts: horizontal bars for rankings, a line for weekly trends.

type Cell = string | number | null;

const short = (v: number) => {
  const a = Math.abs(v);
  if (a >= 1e6) return `${(v / 1e6).toFixed(a >= 1e7 ? 1 : 2)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(a >= 1e4 ? 0 : 1)}k`;
  if (a > 0 && a < 1) return `${(v * 100).toFixed(1)}%`;
  return v.toLocaleString("en-AU", { maximumFractionDigits: 1 });
};

export function Chart({
  type,
  columns,
  rows,
  x,
  y,
  caption,
}: {
  caption?: string;
  type: "bar" | "line";
  columns: string[];
  rows: Cell[][];
  x: string;
  y: string;
}) {
  const xi = columns.indexOf(x);
  const yi = columns.indexOf(y);
  if (xi < 0 || yi < 0) return null;
  const pts = rows
    .map((r) => ({ label: String(r[xi] ?? ""), value: Number(r[yi]) }))
    .filter((p) => Number.isFinite(p.value));
  if (pts.length < 2) return null;
  const label = caption || y.replaceAll("_", " ");
  // Uplift is already in percentage points (114.8 means +114.8%).
  const pct = /uplift|_pct\b|percent/i.test(`${label} ${y}`);
  const fmt = (v: number) => (pct && Math.abs(v) >= 1 ? `${v.toFixed(1)}%` : short(v));
  return type === "bar" ? (
    <Bars pts={pts.slice(0, 15)} y={label} fmt={fmt} />
  ) : (
    <Line pts={pts} y={label} fmt={fmt} />
  );
}

function Bars({ pts, y, fmt }: { pts: { label: string; value: number }[]; y: string; fmt: (v: number) => string }) {
  const max = Math.max(...pts.map((p) => Math.abs(p.value)), 1e-9);
  const rowH = 30;
  const labelW = 150;
  const W = 560;
  const barW = W - labelW - 70;
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${pts.length * rowH + 6}`} role="img" aria-label={`Bar chart of ${y}`}>
        {pts.map((p, i) => {
          const w = Math.max(2, (Math.abs(p.value) / max) * barW);
          const top = i * rowH + 3;
          return (
            <g key={p.label + i}>
              <text x={labelW - 10} y={top + 18} textAnchor="end" className="chart-label">
                {p.label.length > 20 ? `${p.label.slice(0, 19)}…` : p.label}
              </text>
              <rect x={labelW} y={top + 4} width={w} height={rowH - 10} className={i === 0 ? "bar bar-top" : "bar"} />
              <text x={labelW + w + 6} y={top + 18} className="chart-value">
                {fmt(p.value)}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption>{y}</figcaption>
    </figure>
  );
}

function Line({ pts, y, fmt }: { pts: { label: string; value: number }[]; y: string; fmt: (v: number) => string }) {
  const W = 560;
  const H = 220;
  const pad = { l: 52, r: 16, t: 14, b: 34 };
  const vals = pts.map((p) => p.value);
  let lo = Math.min(...vals);
  let hi = Math.max(...vals);
  if (hi === lo) [lo, hi] = [lo * 0.9, hi * 1.1 || 1];
  const span = hi - lo;
  lo -= span * 0.08;
  hi += span * 0.08;
  const px = (i: number) => pad.l + (i / (pts.length - 1)) * (W - pad.l - pad.r);
  const py = (v: number) => pad.t + (1 - (v - lo) / (hi - lo)) * (H - pad.t - pad.b);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${px(i).toFixed(1)},${py(p.value).toFixed(1)}`).join("");
  const ticks = [lo + (hi - lo) * 0.1, (lo + hi) / 2, hi - (hi - lo) * 0.1];
  const every = Math.ceil(pts.length / 6);
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Line chart of ${y}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={py(t)} y2={py(t)} className="grid" />
            <text x={pad.l - 8} y={py(t) + 4} textAnchor="end" className="chart-value">
              {fmt(t)}
            </text>
          </g>
        ))}
        <path d={d} className="line" />
        {pts.map((p, i) => (
          <g key={p.label + i}>
            <circle cx={px(i)} cy={py(p.value)} r={i === pts.length - 1 ? 5 : 3} className="dot">
              <title>{`${p.label}: ${fmt(p.value)}`}</title>
            </circle>
            {(i % every === 0 && pts.length - 1 - i > every / 2) || i === pts.length - 1 ? (
              <text
                x={px(i)}
                y={H - 10}
                textAnchor={i === 0 ? "start" : i === pts.length - 1 ? "end" : "middle"}
                className="chart-label"
              >
                {p.label.length > 10 ? p.label.slice(5) : p.label}
              </text>
            ) : null}
          </g>
        ))}
      </svg>
      <figcaption>{y}</figcaption>
    </figure>
  );
}
