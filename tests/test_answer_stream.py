"""Progress notes written between work steps never reach the visible answer."""
from app.answer_stream import AnswerStream


def shown(events, start=""):
    text = start
    for event in events:
        text = event["text"] if event["type"] == "snapshot" else text + event["text"]
    return text


def test_labelled_commentary_is_never_shown_or_saved():
    stream = AnswerStream()
    events = stream.note_phase("a", "commentary")
    events += stream.feed("I'll check the sales tables now.", "a")
    events += stream.complete("a", "I'll check the sales tables now.", "commentary")
    events += stream.work_started()
    events += stream.note_phase("b", "final_answer")
    events += stream.feed("Shitjet: **1.234 ALL**", "b")
    assert shown(events) == "Shitjet: **1.234 ALL**"
    assert "check the sales" not in "".join(e["text"] for e in events)
    assert stream.finish() == "Shitjet: **1.234 ALL**"


def test_unlabelled_short_note_before_a_tool_is_dropped_without_flashing():
    stream = AnswerStream()
    events = stream.feed("Po kontrolloj të dhënat…")
    assert events == []  # held back while it could still be a progress note
    events += stream.work_started()
    events += stream.feed("Totali: 42", "final")
    assert stream.finish() == "Totali: 42"
    assert shown(events + []) in ("", "Totali: 42")


def test_unlabelled_answer_is_shown_when_the_turn_ends():
    stream = AnswerStream()
    assert stream.feed("Përshëndetje!") == []
    stream.finish()
    assert stream.answer() == "Përshëndetje!"
    assert stream.shown == "Përshëndetje!"


def test_long_unlabelled_text_streams_and_is_taken_back_if_work_follows():
    stream = AnswerStream()
    long_note = "x" * (AnswerStream.HOLD + 10)
    events = stream.feed(long_note)
    assert shown(events) == long_note
    events += stream.work_started()
    assert events[-1] == {"type": "snapshot", "text": ""}
    events += stream.feed("Rezultati: 7", 2)
    assert stream.finish() == "Rezultati: 7"


def test_text_continuing_without_work_in_between_is_all_answer():
    stream = AnswerStream()
    stream.complete("a", "Pjesa 1.")
    stream.feed("Pjesa 2.", "b")
    assert stream.finish() == "Pjesa 1.\n\nPjesa 2."
