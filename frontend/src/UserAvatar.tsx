/** First and last initials: "Pellumb Maraj" → "PM", "Pellumb" → "P". */
export function userInitials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  const first = parts[0][0];
  const last = parts.length > 1 ? parts[parts.length - 1][0] : "";
  return (first + last).toUpperCase();
}

// The same person always gets the same colour; different people rarely share one.
function hueFor(seed: string) {
  let hash = 0;
  for (const char of seed) hash = (hash * 31 + char.codePointAt(0)!) | 0;
  return Math.abs(hash) % 360;
}

export function UserAvatar({
  name,
  seed,
  className = "",
}: {
  name: string;
  seed?: string;
  className?: string;
}) {
  const hue = hueFor(seed || name);
  return (
    <span
      className={`user-avatar ${className}`}
      aria-hidden="true"
      style={{
        background: `linear-gradient(135deg, hsl(${hue} 70% 52%), hsl(${(hue + 40) % 360} 72% 40%))`,
      }}
    >
      {userInitials(name)}
    </span>
  );
}
