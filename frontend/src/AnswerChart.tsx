import type { CSSProperties } from "react";

/*
 * A chart drawn automatically above a table of figures in Hana's reply:
 * horizontal bars for categories (companies, products, cities), or columns
 * with a trend line for periods (months, days, years).
 */

type HastNode = {
  type: string;
  tagName?: string;
  value?: string;
  children?: HastNode[];
};

const text = (node: HastNode): string =>
  node.type === "text" ? node.value || "" : (node.children || []).map(text).join("");

function cells(node: HastNode, tag: string): HastNode[][] {
  const rows: HastNode[][] = [];
  const walk = (n: HastNode) => {
    if (n.tagName === "tr") rows.push((n.children || []).filter((c) => c.tagName === tag));
    else (n.children || []).forEach(walk);
  };
  walk(node);
  return rows.filter((r) => r.length);
}

/** "1.234.567,89 ALL", "1,234.5", "45,2%", "−3 200" → number (or null). */
export function parseFigure(raw: string): number | null {
  let value = raw.replace(/[\s ]/g, "").replace(/−/g, "-");
  if (!/\d/.test(value)) return null;
  value = value.replace(/[^\d.,-]/g, "");
  if (!/^-?[\d.,]+$/.test(value)) return null;
  const comma = value.lastIndexOf(",");
  const dot = value.lastIndexOf(".");
  if (comma >= 0 && dot >= 0) {
    const decimal = comma > dot ? "," : ".";
    value = value
      .split(decimal === "," ? "." : ",")
      .join("")
      .replace(decimal, ".");
  } else if (comma >= 0) {
    value = /,\d{1,2}$/.test(value) && value.split(",").length === 2
      ? value.replace(",", ".")
      : value.replace(/,/g, "");
  } else if (dot >= 0) {
    const parts = value.split(".");
    if (parts.length > 2 || /^\d{3}$/.test(parts[1])) value = parts.join("");
  }
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

const TOTAL = /^(totali|gjithsej|total|shuma)\b/i;
const PERIOD =
  /^(\d{1,2}[./-]\d{1,2}([./-]\d{2,4})?|\d{4}(-\d{2})?|jan|shk|mar|pri|maj|qer|kor|gus|sht|tet|nën|nen|dhj|jan|feb|apr|may|jun|jul|aug|sep|oct|nov|dec|t[1-4]|q[1-4])/i;

export type ChartData = {
  label: string;
  series: string;
  unit: string;
  points: { label: string; value: number; display: string }[];
  periods: boolean;
};

export function chartFromTable(node: HastNode): ChartData | null {
  const head = cells(node, "th")[0]?.map(text) || [];
  const body = cells(node, "td").map((row) => row.map(text));
  if (body.length < 2 || head.length < 2) return null;
  // The first column whose values are mostly numbers carries the figures.
  let column = -1;
  for (let c = 1; c < head.length && column < 0; c++) {
    const numeric = body.filter((r) => r[c] && parseFigure(r[c]) !== null).length;
    if (numeric >= Math.max(2, body.length * 0.7)) column = c;
  }
  if (column < 0) return null;
  const points = body
    .filter((r) => r[0] && !TOTAL.test(r[0].trim()))
    .map((r) => ({ label: r[0].trim(), value: parseFigure(r[column] || "") ?? NaN, display: (r[column] || "").trim() }))
    .filter((p) => Number.isFinite(p.value))
    .slice(0, 14);
  if (points.length < 2) return null;
  const unit = (body.find((r) => r[column])?.[column] || "").replace(/[\d.,\s −-]/g, "");
  return {
    label: head[0],
    series: head[column],
    unit,
    points,
    periods: points.filter((p) => PERIOD.test(p.label)).length >= points.length * 0.6,
  };
}

const compact = (value: number) =>
  new Intl.NumberFormat("sq-AL", { notation: "compact", maximumFractionDigits: 1 }).format(value);

export function AnswerChart({ data }: { data: ChartData }) {
  const max = Math.max(...data.points.map((p) => Math.abs(p.value)), 1);
  if (data.periods) {
    // Columns with a trend line for a sequence of periods.
    const width = 640;
    const height = 220;
    const left = 12;
    const bottom = 34;
    const plot = height - bottom - 20;
    const step = (width - left * 2) / data.points.length;
    const y = (v: number) => 20 + plot - (Math.max(0, v) / max) * plot;
    const line = data.points
      .map((p, i) => `${i ? "L" : "M"}${left + step * (i + 0.5)} ${y(p.value)}`)
      .join(" ");
    return (
      <figure className="answer-chart periods" aria-label={`Grafiku: ${data.series}`}>
        <figcaption>
          {data.series}
          {data.unit && <span>{data.unit}</span>}
        </figcaption>
        <svg viewBox={`0 0 ${width} ${height}`} role="img">
          <defs>
            <linearGradient id="answer-col" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="var(--chart-a)" />
              <stop offset="1" stopColor="var(--chart-b)" />
            </linearGradient>
          </defs>
          {data.points.map((p, i) => (
            <g key={i} style={{ "--i": i } as CSSProperties} className="answer-col">
              <rect
                x={left + step * i + step * 0.2}
                y={y(p.value)}
                width={step * 0.6}
                height={20 + plot - y(p.value)}
                rx="6"
                fill="url(#answer-col)"
              >
                <title>{`${p.label}: ${p.display}`}</title>
              </rect>
              <text x={left + step * (i + 0.5)} y={height - 12} textAnchor="middle" className="answer-axis">
                {p.label.slice(0, 10)}
              </text>
              <text x={left + step * (i + 0.5)} y={y(p.value) - 6} textAnchor="middle" className="answer-value">
                {compact(p.value)}
              </text>
            </g>
          ))}
          <path d={line} className="answer-trend" pathLength={1} fill="none" />
        </svg>
      </figure>
    );
  }
  return (
    <figure className="answer-chart bars" aria-label={`Grafiku: ${data.series}`}>
      <figcaption>
        {data.series}
        {data.unit && <span>{data.unit}</span>}
      </figcaption>
      <ol>
        {[...data.points]
          .sort((a, b) => b.value - a.value)
          .map((p, i) => (
            <li key={i} style={{ "--i": i, "--share": Math.abs(p.value) / max } as CSSProperties}>
              <span className="answer-bar-label" title={p.label}>
                {p.label}
              </span>
              <span className="answer-bar-track">
                <span className="answer-bar" />
              </span>
              <span className="answer-bar-value">{p.display}</span>
            </li>
          ))}
      </ol>
    </figure>
  );
}
