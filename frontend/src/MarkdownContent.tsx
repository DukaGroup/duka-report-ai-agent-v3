import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const components: Components = {
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

export function MarkdownContent({ children }: { children: string }) {
  return (
    <div className="markdown">
      <Markdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </Markdown>
    </div>
  );
}
