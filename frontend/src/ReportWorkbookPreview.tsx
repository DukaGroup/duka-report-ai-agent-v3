import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, FormEvent } from "react";
import {
  BarChart3,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FileSpreadsheet,
  LoaderCircle,
  RotateCcw,
} from "lucide-react";
import { api } from "./api";
import { SERVICE_UNAVAILABLE } from "./locale";

type PreviewCell = {
  text: string;
  raw: string;
  bold: boolean;
  italic: boolean;
  numeric: boolean;
  color: string | null;
  background: string | null;
  align: "left" | "center" | "right" | null;
  wrap: boolean;
};
type PreviewSheet = { name: string; row_count: number; column_count: number };
type PreviewMerge = {
  start_row: number;
  start_column: number;
  end_row: number;
  end_column: number;
};
type PreviewChart = {
  title: string;
  type: "column" | "bar" | "line" | "area" | "pie";
  categories: string[];
  series: { name: string; values: (number | null)[] }[];
  truncated: boolean;
};
type Preview = {
  sheets: PreviewSheet[];
  sheet_index: number;
  row_start: number;
  column_start: number;
  rows: PreviewCell[][];
  visible_rows: number;
  visible_columns: number;
  has_more_rows: boolean;
  has_more_columns: boolean;
  merged: PreviewMerge[];
  charts: PreviewChart[];
};

const PAGE_ROWS = 50;
const PAGE_COLUMNS = 16;
const chartColors = ["#176844", "#3a8c72", "#6799bf", "#a184c0"];

function columnName(index: number) {
  let name = "";
  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26))
    name = String.fromCharCode(65 + ((n - 1) % 26)) + name;
  return name;
}

function columnIndex(name: string) {
  return [...name.toUpperCase()].reduce(
    (value, letter) => value * 26 + letter.charCodeAt(0) - 64,
    0,
  );
}

function numberLabel(value: number) {
  return new Intl.NumberFormat("sq-AL", { maximumFractionDigits: 2 }).format(value);
}

function WorkbookChart({ chart }: { chart: PreviewChart }) {
  const categories = chart.categories;
  const series = chart.series.slice(0, 4);
  const points = series.flatMap((item) => item.values).filter((value): value is number => value !== null);
  if (!points.length) return null;
  const count = Math.max(categories.length, ...series.map((item) => item.values.length));
  const low = Math.min(0, ...points);
  const high = Math.max(0, ...points);
  const span = high - low || 1;
  const plot = { left: 55, right: 700, top: 20, bottom: 230 };
  const y = (value: number) => plot.bottom - ((value - low) / span) * (plot.bottom - plot.top);
  const zero = y(0);
  const labelIndexes = [...new Set([0, Math.floor((count - 1) / 2), count - 1])];

  if (chart.type === "bar") {
    const height = Math.max(270, count * 27 + 42);
    const left = 170;
    const scale = (value: number) => left + ((value - low) / span) * 520;
    const origin = scale(0);
    return <article className="workbook-chart-card">
      <h5>{chart.title}</h5>
      <div className="workbook-chart-scroll">
        <svg viewBox={`0 0 730 ${height}`} role="img" aria-label={`Grafiku ${chart.title}`}>
          {categories.map((category, index) => <text key={index} x={left - 9} y={31 + index * 27} textAnchor="end" className="workbook-chart-axis">{category.slice(0, 22)}</text>)}
          {series.flatMap((item, seriesIndex) => item.values.map((value, index) => {
            if (value === null) return null;
            const barHeight = 17 / series.length;
            return <rect key={`${seriesIndex}-${index}`} x={Math.min(origin, scale(value))} y={18 + index * 27 + seriesIndex * barHeight} width={Math.max(1, Math.abs(scale(value) - origin))} height={barHeight} fill={chartColors[seriesIndex]} className="chart-bar-h" style={{ "--i": index } as CSSProperties}>
              <title>{`${categories[index] || index + 1} · ${item.name}: ${numberLabel(value)}`}</title>
            </rect>;
          }))}
        </svg>
      </div>
      <div className="workbook-chart-legend">{series.map((item, index) => <span key={`${item.name}-${index}`}><i style={{ backgroundColor: chartColors[index] }} />{item.name}</span>)}</div>
      {chart.truncated && <p>Grafiku tregon 1 000 pikat e para; të gjitha vlerat mund t’i shihni në fletë.</p>}
    </article>;
  }

  if (chart.type === "pie") {
    const values = series[0].values.map((value) => Math.max(0, value || 0));
    const total = values.reduce((sum, value) => sum + value, 0);
    let angle = -Math.PI / 2;
    const slices = values.map((value, index) => {
      const start = angle;
      angle += total ? (value / total) * Math.PI * 2 : 0;
      const end = angle;
      const x1 = 365 + 105 * Math.cos(start);
      const y1 = 130 + 105 * Math.sin(start);
      const x2 = 365 + 105 * Math.cos(end);
      const y2 = 130 + 105 * Math.sin(end);
      if (!value) return null;
      if (value === total) return <circle key={index} cx="365" cy="130" r="105" fill={chartColors[index % chartColors.length]} className="chart-slice"><title>{`${categories[index] || index + 1}: ${numberLabel(value)}`}</title></circle>;
      return <path key={index} d={`M 365 130 L ${x1} ${y1} A 105 105 0 ${end - start > Math.PI ? 1 : 0} 1 ${x2} ${y2} Z`} fill={chartColors[index % chartColors.length]} className="chart-slice" style={{ "--i": index } as CSSProperties}>
        <title>{`${categories[index] || index + 1}: ${numberLabel(value)}`}</title>
      </path>;
    });
    return <article className="workbook-chart-card">
      <h5>{chart.title}</h5>
      <div className="workbook-chart-scroll"><svg viewBox="0 0 730 270" role="img" aria-label={`Grafiku ${chart.title}`}>{slices}</svg></div>
      <div className="workbook-chart-legend">{categories.slice(0, 12).map((category, index) => <span key={`${category}-${index}`}><i style={{ backgroundColor: chartColors[index % chartColors.length] }} />{category}</span>)}{categories.length > 12 && <span>+{categories.length - 12} të tjera në fletë</span>}</div>
    </article>;
  }

  return (
    <article className="workbook-chart-card">
      <h5>{chart.title}</h5>
      <div className="workbook-chart-scroll">
        <svg viewBox="0 0 730 270" role="img" aria-label={`Grafiku ${chart.title}`}>
          {[0, 0.5, 1].map((fraction) => {
            const value = low + span * fraction;
            const position = y(value);
            return (
              <g key={fraction}>
                <line x1={plot.left} x2={plot.right} y1={position} y2={position} className="workbook-chart-gridline" />
                <text x={plot.left - 8} y={position + 4} textAnchor="end" className="workbook-chart-axis">{numberLabel(value)}</text>
              </g>
            );
          })}
          {chart.type === "column" &&
            series.flatMap((item, seriesIndex) =>
              item.values.map((value, index) => {
                if (value === null) return null;
                const groupWidth = (plot.right - plot.left) / count;
                const width = Math.max(0.5, (groupWidth * 0.76) / series.length);
                const x = plot.left + index * groupWidth + groupWidth * 0.12 + seriesIndex * width;
                const top = Math.min(y(value), zero);
                return (
                  <rect
                    key={`${seriesIndex}-${index}`}
                    x={x}
                    y={top}
                    width={width}
                    height={Math.max(1, Math.abs(y(value) - zero))}
                    fill={chartColors[seriesIndex]}
                    className="chart-bar-v"
                    style={{ "--i": index } as CSSProperties}
                  >
                    <title>{`${categories[index] || index + 1} · ${item.name}: ${numberLabel(value)}`}</title>
                  </rect>
                );
              }),
            )}
          {(chart.type === "line" || chart.type === "area") &&
            series.map((item, seriesIndex) => {
              const coordinates = item.values.flatMap((value, index) =>
                value === null ? [] : [[plot.left + ((index + 0.5) / count) * (plot.right - plot.left), y(value)]],
              );
              const line = coordinates.map(([x, yValue], index) => `${index === 0 ? "M" : "L"} ${x} ${yValue}`).join(" ");
              const area = coordinates.length ? `${line} L ${coordinates[coordinates.length - 1][0]} ${zero} L ${coordinates[0][0]} ${zero} Z` : "";
              return <g key={seriesIndex}>
                {chart.type === "area" && <path d={area} fill={chartColors[seriesIndex]} fillOpacity="0.15" className="chart-area" />}
                <path d={line} fill="none" stroke={chartColors[seriesIndex]} strokeWidth="2.5" className="chart-line" pathLength={1} />
                {coordinates.length <= 60 && coordinates.map(([x, yValue], index) => <circle key={index} cx={x} cy={yValue} r="3" fill={chartColors[seriesIndex]} className="chart-point" style={{ "--i": index } as CSSProperties} />)}
              </g>;
            })}
          {labelIndexes.map((index) => (
            <text
              key={index}
              x={plot.left + ((index + 0.5) / count) * (plot.right - plot.left)}
              y={255}
              textAnchor={index === 0 ? "start" : index === count - 1 ? "end" : "middle"}
              className="workbook-chart-axis"
            >
              {(categories[index] || String(index + 1)).slice(0, 24)}
            </text>
          ))}
        </svg>
      </div>
      <div className="workbook-chart-legend">
        {series.map((item, index) => (
          <span key={`${item.name}-${index}`}><i style={{ backgroundColor: chartColors[index] }} />{item.name}</span>
        ))}
      </div>
      {chart.truncated && <p>Grafiku tregon 1 000 pikat e para; të gjitha vlerat mund t’i shihni në fletë.</p>}
    </article>
  );
}

export function ReportWorkbookPreview({ reportId, technical = false }: { reportId: string; technical?: boolean }) {
  const [sheetIndex, setSheetIndex] = useState(0);
  const [rowStart, setRowStart] = useState(1);
  const [columnStart, setColumnStart] = useState(1);
  const [selection, setSelection] = useState({ row: 1, column: 1 });
  const [addressInput, setAddressInput] = useState("A1");
  const [addressError, setAddressError] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [chartsOpen, setChartsOpen] = useState(true);
  const gridScroll = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    void api<Preview>(
      `/reports/${reportId}/preview?sheet=${sheetIndex}&row=${rowStart}&column=${columnStart}`,
      { signal: controller.signal },
    )
      .then((result) => {
        if (!controller.signal.aborted) setPreview(result);
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted)
          setError((cause as Error).message || "Pamja paraprake nuk u hap.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [reportId, sheetIndex, rowStart, columnStart, retry]);

  const visible =
    preview?.sheet_index === sheetIndex &&
    preview.row_start === rowStart &&
    preview.column_start === columnStart
      ? preview
      : null;
  const sheet = preview?.sheets[sheetIndex];
  const selectedCell = visible?.rows[selection.row - rowStart]?.[selection.column - columnStart];
  const mergeMap = useMemo(() => {
    const roots = new Map<string, { rows: number; columns: number }>();
    const covered = new Set<string>();
    if (!visible) return { roots, covered };
    for (const merge of visible.merged) {
      const top = Math.max(merge.start_row, visible.row_start);
      const left = Math.max(merge.start_column, visible.column_start);
      const bottom = Math.min(merge.end_row, visible.row_start + visible.visible_rows - 1);
      const right = Math.min(merge.end_column, visible.column_start + visible.visible_columns - 1);
      roots.set(`${top}:${left}`, { rows: bottom - top + 1, columns: right - left + 1 });
      for (let row = top; row <= bottom; row++)
        for (let column = left; column <= right; column++)
          if (row !== top || column !== left) covered.add(`${row}:${column}`);
    }
    return { roots, covered };
  }, [visible]);

  function select(row: number, column: number) {
    setSelection({ row, column });
    setAddressInput(`${columnName(column - 1)}${row}`);
    setAddressError("");
  }

  function page(nextRow: number, nextColumn: number) {
    setRowStart(nextRow);
    setColumnStart(nextColumn);
    select(nextRow, nextColumn);
    gridScroll.current?.scrollTo({ top: 0, left: 0 });
  }

  function changeSheet(index: number) {
    setSheetIndex(index);
    setRowStart(1);
    setColumnStart(1);
    select(1, 1);
    gridScroll.current?.scrollTo({ top: 0, left: 0 });
  }

  function jump(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const match = /^\s*([A-Za-z]{1,3})([1-9]\d*)\s*$/.exec(addressInput);
    if (!match || !sheet) {
      setAddressError("Shkruani një qelizë si A1 ose Q120.");
      return;
    }
    const column = columnIndex(match[1]);
    const row = Number(match[2]);
    if (row > sheet.row_count || column > sheet.column_count) {
      setAddressError("Kjo qelizë është jashtë fletës.");
      return;
    }
    const nextRow = Math.floor((row - 1) / PAGE_ROWS) * PAGE_ROWS + 1;
    const nextColumn = Math.floor((column - 1) / PAGE_COLUMNS) * PAGE_COLUMNS + 1;
    setRowStart(nextRow);
    setColumnStart(nextColumn);
    select(row, column);
    gridScroll.current?.scrollTo({ top: 0, left: 0 });
  }

  return (
    <section className="workbook-preview" aria-label="Pamja paraprake e Excel-it">
      <div className="workbook-preview-intro">
        <span className="workbook-preview-icon" aria-hidden="true"><FileSpreadsheet size={23} /></span>
        <div>
          <span className="eyebrow">LIBRI I PUNËS</span>
          <h3>Pamja e Excel-it</h3>
          <p>Shfletoni çdo fletë, rresht, kolonë dhe grafik para shkarkimit.</p>
        </div>
        {!!preview?.sheets.length && <span className="workbook-sheet-count">{preview.sheets.length} fletë</span>}
      </div>

      {!!preview?.sheets.length && (
        <div className="workbook-formula-bar">
          <form onSubmit={jump} className="workbook-name-box">
            <label htmlFor="workbook-address">Qeliza</label>
            <input id="workbook-address" aria-label="Shko te qeliza" value={addressInput} onChange={(event) => setAddressInput(event.target.value)} spellCheck={false} />
          </form>
          <span className="workbook-fx" aria-hidden="true">fx</span>
          <textarea aria-label="Përmbajtja e plotë e qelizës" readOnly value={selectedCell?.raw || ""} rows={1} />
        </div>
      )}
      {addressError && <p className="workbook-address-error" role="alert">{addressError}</p>}
      {error && (
        <div className="workbook-preview-error" role="alert">
          <span>{technical ? error : SERVICE_UNAVAILABLE}</span>
          <button type="button" className="button outline small" onClick={() => setRetry((n) => n + 1)}>
            <RotateCcw size={15} /> Provo përsëri
          </button>
        </div>
      )}
      {loading && <div className="workbook-preview-loading" role="status"><LoaderCircle size={20} className="spin" /> Po hapet fleta…</div>}
      {!loading && !error && sheet && visible && (
        <>
          {/* Charts come first, above the sheet's cells. */}
          {visible.charts.length > 0 && (
            <section className="workbook-charts" aria-label="Grafikët e fletës">
              <button className="workbook-charts-toggle" type="button" aria-expanded={chartsOpen} onClick={() => setChartsOpen((value) => !value)}>
                <BarChart3 size={17} /> Grafikët e fletës ({visible.charts.length}) <ChevronDown size={16} className={chartsOpen ? "open" : ""} />
              </button>
              {chartsOpen && <div className="workbook-charts-list">{visible.charts.map((chart, index) => <WorkbookChart chart={chart} key={`${index}:${chart.title}`} />)}</div>}
            </section>
          )}
          <div className="workbook-preview-meta">
            <strong>{sheet.name}</strong>
            <span>{numberLabel(sheet.row_count)} rreshta · {numberLabel(sheet.column_count)} kolona</span>
          </div>
          <div className="workbook-navigation">
            <div className="workbook-page-control" aria-label="Lëvizja në rreshta">
              <button type="button" aria-label="Rreshtat e mëparshëm" disabled={rowStart <= 1} onClick={() => page(Math.max(1, rowStart - PAGE_ROWS), columnStart)}><ChevronLeft size={17} /></button>
              <span>Rreshtat {numberLabel(rowStart)}–{numberLabel(rowStart + visible.visible_rows - 1)} / {numberLabel(sheet.row_count)}</span>
              <button type="button" aria-label="Rreshtat e ardhshëm" disabled={!visible.has_more_rows} onClick={() => page(rowStart + PAGE_ROWS, columnStart)}><ChevronRight size={17} /></button>
            </div>
            <div className="workbook-page-control" aria-label="Lëvizja në kolona">
              <button type="button" aria-label="Kolonat e mëparshme" disabled={columnStart <= 1} onClick={() => page(rowStart, Math.max(1, columnStart - PAGE_COLUMNS))}><ChevronLeft size={17} /></button>
              <span>Kolonat {columnName(columnStart - 1)}–{columnName(columnStart + visible.visible_columns - 2)} / {columnName(Math.max(0, sheet.column_count - 1))}</span>
              <button type="button" aria-label="Kolonat e ardhshme" disabled={!visible.has_more_columns} onClick={() => page(rowStart, columnStart + PAGE_COLUMNS)}><ChevronRight size={17} /></button>
            </div>
          </div>
          {visible.rows.length ? (
            <div ref={gridScroll} key={sheet.name} className="workbook-grid-scroll" role="region" aria-label={`Përmbajtja e fletës ${sheet.name}`} tabIndex={0}>
              <table className="workbook-grid">
                <thead><tr>
                  <th className="workbook-corner" scope="col" aria-label="Numri i rreshtit" />
                  {Array.from({ length: visible.visible_columns }, (_, index) => {
                    const column = visible.column_start + index;
                    return <th scope="col" key={column} className={selection.column === column ? "selected" : ""}>{columnName(column - 1)}</th>;
                  })}
                </tr></thead>
                <tbody>
                  {visible.rows.map((row, rowIndex) => {
                    const absoluteRow = visible.row_start + rowIndex;
                    return <tr key={absoluteRow} style={{ "--i": Math.min(rowIndex, 24) } as CSSProperties}>
                      <th scope="row" className={selection.row === absoluteRow ? "selected" : ""}>{absoluteRow}</th>
                      {row.map((cell, cellIndex) => {
                        const absoluteColumn = visible.column_start + cellIndex;
                        const key = `${absoluteRow}:${absoluteColumn}`;
                        if (mergeMap.covered.has(key)) return null;
                        const merged = mergeMap.roots.get(key);
                        const active = selection.row === absoluteRow && selection.column === absoluteColumn;
                        const style: CSSProperties = {
                          color: cell.color || undefined,
                          backgroundColor: cell.background || undefined,
                          textAlign: cell.align || undefined,
                        };
                        return <td
                          key={key}
                          colSpan={merged?.columns}
                          rowSpan={merged?.rows}
                          style={style}
                          className={`${cell.bold ? "emphasized " : ""}${cell.italic ? "italic " : ""}${cell.numeric ? "numeric " : ""}${cell.wrap ? "wrapped " : ""}${active ? "active" : ""}`}
                          aria-selected={active}
                          onClick={() => select(absoluteRow, absoluteColumn)}
                        >{cell.text || "\u00a0"}</td>;
                      })}
                    </tr>;
                  })}
                </tbody>
              </table>
            </div>
          ) : <p className="workbook-preview-empty">Kjo fletë nuk ka qeliza të mbushura.</p>}

          <div className="workbook-sheet-tabs" role="group" aria-label="Fletët e Excel-it">
            {visible.sheets.map((item, index) => (
              <button key={`${index}:${item.name}`} type="button" className={index === sheetIndex ? "active" : ""} aria-pressed={index === sheetIndex} onClick={() => changeSheet(index)}>{item.name}</button>
            ))}
          </div>
          <p className="workbook-preview-note">Të gjitha fletët, rreshtat dhe kolonat mund të shfletohen këtu. Shkruani një adresë si Q120 për të shkuar drejtpërdrejt te një qelizë.</p>
        </>
      )}
    </section>
  );
}
