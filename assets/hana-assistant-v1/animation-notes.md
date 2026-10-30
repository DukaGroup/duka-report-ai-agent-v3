# Hana layered 2D animation

The application now uses the original generated character from `assets/hana-assistant-v1/hana-waist-up.png`. The production artwork is served locally from `/home/pume-laptop/Documents/duka-group/duka-report-ai-agent-v3/frontend/public/brand/hana-original-v1.png`.

The new matched closed-eye frame is `/home/pume-laptop/Documents/duka-group/duka-report-ai-agent-v3/frontend/public/brand/hana-original-v1-blink.png`, generated with the built-in imagegen tool. Only the eye regions are blended over the unchanged original artwork.

Final blink prompt:

Use case: identity-preserve. Edit target: the referenced original Hana artwork. Change ONLY both eyelids to a relaxed, natural closed blink. Keep the same square canvas, same full waist-up framing and margins, same face location and size, exact identity, hair, expression, lips, armor, hands, lighting, and transparent alpha. Do not reframe or zoom. All non-eye details should stay exactly aligned with the reference because only the eye regions will be composited over the original. Real skin texture and natural eyelid folds, no painted or cartoon eye shapes.

Implementation: `frontend/src/HanaPuppet.tsx` renders source-texture cutouts in a shoulder → elbow → wrist hierarchy; source pivots and clip paths live in `hanaRig.ts`. The source PNG remains intact. `hanaMotion.ts` supplies small authored poses, a brief wave, thinking and listening poses, open-palm explanation, acknowledgment and error gestures. Frame-independent easing blends state changes without overshoot. Browsers perform the animation locally from the existing assistant activity states. No extra model calls or new animation dependencies are introduced.

This is a front-facing 2D rig. Finger articulation and depth rotation are not implemented. The existing moonrise (700 ms), transformation to Hana's face (500 ms), greeting (1700 ms), and logout timings remain unchanged. Reduced-motion preferences render the neutral body pose. Hidden/offscreen figures skip painting. The login page contains no assistant image or avatar caption.

The original artwork and previous assistant assets are preserved. No server deployment or live AI request is part of this update.

