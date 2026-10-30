import { HANA_FACE_VIEWBOX, HANA_PORTRAIT } from "./hanaAvatar";

/** Hana's face, cropped from her portrait, for small round avatars. */
export function HanaAvatar() {
  return (
    <svg className="hana-avatar" viewBox={HANA_FACE_VIEWBOX} aria-hidden="true">
      <image href={HANA_PORTRAIT} width="100" height="100" />
    </svg>
  );
}
