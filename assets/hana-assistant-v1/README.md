# Hana — original waist-up character artwork

`hana-waist-up.png` is the selected final cutout. `source-render.png` preserves the initial render for reference. Both are lossless RGBA PNG files with transparent backgrounds. See `manifest.json` for exact dimensions and checksums.

Created with the built-in image generation tool from an original descriptive prompt, followed by framing and cutout refinements. No marketplace character model or third-party robot picture was used as an image input. The full prompt set is preserved in `prompts.md`.

The character has a realistic adult female face, dark hair, blue eyes, silver/pearl-white mechanical armor with cyan details, visible shoulder/elbow/wrist joints, and separated open hands with five fingers each. The image is framed from the head to the waist with margins around the silhouette. The final PNG was inspected on both light and dark backgrounds.

## Future animation

The artwork is now incorporated through a layered 2D rig in `frontend/src/HanaPuppet.tsx`, with pivots in `hanaRig.ts` and authored gestures in `hanaMotion.ts`. It moves the head, upper arms, forearms and hands through connected pivots. It has no 3D mesh or independently animated fingers. See `animation-notes.md` for details and the matching eyelid-frame prompt.

The app uses a copy of this original artwork; the master PNGs in this folder remain unchanged. The login page has no assistant image.
