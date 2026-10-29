"""Keep the model's in-between progress notes out of the visible answer.

While working, a model often writes short notes between steps ("I'll check
the sales data now…") before calling a tool. Those notes are part of its
work, not the reply, and must never appear in the chat or the saved answer.

Text is grouped into segments (one per model message). A segment is part of
the answer when the provider labels it an answer, or when no tool, search or
reasoning step follows it. Segments with no label are briefly held back: if
work starts next they are discarded; if more text follows directly or the
turn ends, they are shown. Long unlabeled text is shown early (and taken back
if work follows after all), so real answers still stream.
"""

ANSWER_PHASES = ("final_answer", "partial_answer")
NOTE_PHASES = ("commentary",)


class AnswerStream:
    # Unlabeled text longer than this is almost certainly the answer itself.
    HOLD = 320

    def __init__(self):
        self.segments: list[dict] = []
        self.shown = ""

    def _segment(self, sid=None, phase=None):
        last = self.segments[-1] if self.segments else None
        if last and not last["closed"] and (sid is None or last["id"] in (None, sid)):
            if sid is not None:
                last["id"] = sid
        else:
            # Text that directly follows another message (no work in between)
            # confirms that the earlier message was part of the answer.
            if last:
                last["confirmed"] = True
                last["closed"] = True
            last = {"id": sid, "phase": None, "text": "", "closed": False, "confirmed": False}
            self.segments.append(last)
        if phase:
            last["phase"] = phase
        return last

    def note_phase(self, sid, phase):
        """A provider announced a message and (maybe) its phase."""
        if phase:
            self._segment(sid, phase)
        return self._sync()

    def feed(self, text, sid=None, phase=None):
        self._segment(sid, phase)["text"] += text
        return self._sync()

    def complete(self, sid, text, phase=None):
        """The provider's authoritative full text for a finished message."""
        segment = self._segment(sid, phase)
        segment["text"] = text
        segment["closed"] = True
        return self._sync()

    def work_started(self):
        """A tool call, search or reasoning step began: earlier notes were work."""
        self.segments = [s for s in self.segments if s["phase"] in ANSWER_PHASES]
        for segment in self.segments:
            segment["closed"] = True
        return self._sync()

    def release(self):
        """The turn ended: everything still held back is the answer. Returns
        the stream events that show it."""
        for segment in self.segments:
            segment["confirmed"] = True
            segment["closed"] = True
        return self._sync()

    def finish(self):
        self.release()
        return self.answer()

    def answer(self):
        return "\n\n".join(
            s["text"] for s in self.segments if s["phase"] not in NOTE_PHASES and s["text"]
        )

    def _visible(self):
        parts = []
        for s in self.segments:
            if s["phase"] in NOTE_PHASES or not s["text"]:
                continue
            if s["phase"] in ANSWER_PHASES or s["confirmed"] or len(s["text"]) > self.HOLD:
                parts.append(s["text"])
        return "\n\n".join(parts)

    def _sync(self):
        desired = self._visible()
        if desired == self.shown:
            return []
        if desired.startswith(self.shown):
            events = [{"type": "delta", "text": desired[len(self.shown):]}]
        else:
            # Something already shown turned out to be a progress note.
            events = [{"type": "snapshot", "text": desired}]
        self.shown = desired
        return events
