export function ThinkingStatus({ description }: { description: string }) {
  return (
    <div
      className="thinking"
      role="status"
      aria-label={description}
      aria-atomic="true"
    >
      <span className="thinking-dots" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <span className="thinking-label">{description}</span>
    </div>
  );
}
