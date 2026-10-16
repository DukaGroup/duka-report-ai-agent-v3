export function Brand({ light = false }: { light?: boolean }) {
  return (
    <span className={`brand-lockup${light ? " brand-lockup-light" : ""}`}>
      <img
        className="brand-logo"
        src={`/brand/duka-group-logo${light ? "-light" : ""}.webp`}
        width="768"
        height="173"
        alt="Duka Group"
      />
      <img
        className="brand-compact"
        src="/brand/duka-group-icon-192.webp"
        width="192"
        height="192"
        alt="Duka Group"
      />
      <span className="brand-sub">HAPËSIRA E RAPORTEVE</span>
    </span>
  );
}
