import {
  Children,
  isValidElement,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import Markdown, { type Components } from "react-markdown";
import { AnswerChart, chartFromTable } from "./AnswerChart";
import remarkGfm from "remark-gfm";

type HastNode = {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
};

/*
 * While Hana is still writing, every word is wrapped in its own span. Words
 * that are already on screen keep their element, so only the new ones play a
 * short fade-in: the reply flows in instead of jumping in chunks.
 */
function wrapWords() {
  const visit = (node: HastNode) => {
    if (!node.children) return;
    if (node.tagName === "code" || node.tagName === "pre") return;
    node.children = node.children.flatMap((child) => {
      if (child.type !== "text" || !child.value) {
        visit(child);
        return [child];
      }
      return child.value
        .split(/(\s+)/)
        .filter(Boolean)
        .map((part) =>
          /^\s+$/.test(part)
            ? { type: "text", value: part }
            : {
                type: "element",
                tagName: "span",
                properties: { className: ["stream-word"] },
                children: [{ type: "text", value: part }],
              },
        );
    });
  };
  return (tree: HastNode) => visit(tree);
}

function plainText(node: ReactNode): string {
  return Children.toArray(node)
    .map((child) =>
      typeof child === "string" || typeof child === "number"
        ? String(child)
        : isValidElement<{ children?: ReactNode }>(child)
          ? plainText(child.props.children)
          : "",
    )
    .join("");
}

// A figure such as "1.234.567 €", "45,2%" or "ALL 12 000"; never a date.
const FIGURE =
  /^[-+−]?\s?(?:€|\$|ALL|L)?\s?\d[\d.,\s ]*(?:\s?(?:%|€|\$|ALL|lekë|Lekë|EUR|USD|mijë|mln|milionë?))?$/;
const DATE = /^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$/;
export const isFigure = (text: string) =>
  text.length <= 24 && FIGURE.test(text.trim()) && !DATE.test(text.trim());

const DIGITS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9];

/** Each digit rolls up to its value, like an odometer. Format stays exact. */
function RollingFigure({ text }: { text: string }) {
  const [rolled, setRolled] = useState(false);
  useEffect(() => {
    // Wait until the zeros have been drawn once, so the roll always plays.
    let second = 0;
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => setRolled(true));
    });
    return () => {
      cancelAnimationFrame(first);
      cancelAnimationFrame(second);
    };
  }, []);
  let digit = 0;
  return (
    <strong className={`rolling-figure${rolled ? " rolled" : ""}`} aria-label={text}>
      {[...text].map((character, index) =>
        /\d/.test(character) ? (
          <span
            key={index}
            className="roll-digit"
            aria-hidden="true"
            style={
              {
                "--digit": Number(character),
                "--order": digit++,
              } as CSSProperties
            }
          >
            <span>
              {DIGITS.map((value) => (
                <span key={value}>{value}</span>
              ))}
            </span>
          </span>
        ) : (
          <span key={index} aria-hidden="true">
            {character}
          </span>
        ),
      )}
    </strong>
  );
}

const baseComponents: Components = {
  table: ({ node: _node, ...props }) => (
    <div
      className="markdown-table-scroll"
      role="region"
      aria-label="Tabelë e përgjigjes"
      tabIndex={0}
    >
      <table {...props} />
    </div>
  ),
  td: ({ node: _node, ...props }) => (
    <td
      {...props}
      className={props.style?.textAlign === "right" ? "numeric" : undefined}
    />
  ),
};

const figureComponents: Components = {
  ...baseComponents,
  strong: ({ node: _node, children, ...props }) => {
    const text = plainText(children);
    return isFigure(text) ? (
      <RollingFigure text={text} />
    ) : (
      <strong {...props}>{children}</strong>
    );
  },
};

const REPORT_LINK = /\/api\/reports\/([^/?#]+)\/export\b/;

export function MarkdownContent({
  children,
  streaming = false,
  celebrate = false,
  reportStatus,
}: {
  children: string;
  // Hana is still writing this reply.
  streaming?: boolean;
  // The reply just finished while the user watched: key figures roll up.
  celebrate?: boolean;
  // A report's current status, so its download link only works once ready.
  reportStatus?: (id: string) => string | undefined;
}) {
  // Read through a ref so the rendering components stay the same between
  // renders (new component types would rebuild and re-animate the reply).
  const status = useRef(reportStatus);
  status.current = reportStatus;
  const checksReports = !!reportStatus;
  const components = useMemo<Components>(() => {
    const figures = celebrate ? figureComponents : baseComponents;
    // Once the reply is complete, a table of figures gets a chart above it.
    const base: Components = streaming
      ? figures
      : {
          ...figures,
          table: ({ node, ...props }) => {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const chart = node ? chartFromTable(node as any) : null;
            const Table = baseComponents.table as (p: typeof props) => ReactNode;
            return (
              <>
                {chart && <AnswerChart data={chart} />}
                {Table(props)}
              </>
            );
          },
        };
    if (!checksReports) return base;
    return {
      ...base,
      a: ({ node: _node, href, children: label, ...props }) => {
        const report = href?.match(REPORT_LINK)?.[1];
        const state = report ? status.current?.(report) : undefined;
        if (report && state && state !== "completed")
          return (
            <span className="report-link-pending">
              {state === "failed"
                ? "Raporti nuk u krijua."
                : "Excel-i po përgatitet…"}
            </span>
          );
        return (
          <a href={href} {...props}>
            {label}
          </a>
        );
      },
    };
  }, [celebrate, checksReports, streaming]);
  return (
    <div className={`markdown${streaming ? " streaming" : ""}`}>
      <Markdown
        remarkPlugins={[remarkGfm]}
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        rehypePlugins={streaming ? [wrapWords as any] : []}
        components={components}
      >
        {children}
      </Markdown>
    </div>
  );
}
