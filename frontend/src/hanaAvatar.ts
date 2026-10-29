// Hana's portrait. Every place that shows the assistant uses these files,
// including the talking animation, so they always match.
// Portrait supplied by the user: futuristic_ai_assistant_avatar_sleek--1--1p8dx.webp.
// Version the URLs so existing browser caches receive the replacement portrait.
const AVATAR_VERSION = "fe69cfcd1e39";
export const HANA_AVATAR = `/brand/hana-avatar.webp?v=${AVATAR_VERSION}`;
// A small copy for chat avatars and other tiny spots.
export const HANA_AVATAR_SMALL = `/brand/hana-avatar-256.webp?v=${AVATAR_VERSION}`;
