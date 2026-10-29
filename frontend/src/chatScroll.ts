type Viewport = Pick<
  HTMLElement,
  "scrollHeight" | "scrollTop" | "clientHeight"
>;

// Within this distance the reader is at the end of the conversation.
const END_DISTANCE = 8;
// The "latest message" button only appears once there is real unread
// content below, not when the reader is already looking at the last message.
const JUMP_DISTANCE = 120;

function distanceFromEnd(scroll: Viewport) {
  return Math.max(0, scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight);
}

function atEnd(scroll: Viewport) {
  return distanceFromEnd(scroll) <= END_DISTANCE;
}

export class ChatScrollFollower {
  following = true;
  private previousTop = 0;
  pause() {
    this.following = false;
  }
  observe(scroll: Viewport) {
    // Moving up pauses following, so streaming text never pulls the reader
    // away. Reaching the end again (by scrolling down) resumes it, which also
    // hides the "latest message" button automatically.
    if (scroll.scrollTop < this.previousTop - 1) this.following = false;
    else if (atEnd(scroll)) this.following = true;
    this.previousTop = scroll.scrollTop;
    return this.following;
  }
  update(scroll: HTMLElement, switched = false) {
    // Nothing to scroll means the whole conversation is already visible.
    if (switched || scroll.scrollHeight <= scroll.clientHeight + END_DISTANCE)
      this.following = true;
    if (this.following)
      scroll.scrollTo({ top: scroll.scrollHeight, behavior: "instant" });
    this.previousTop = scroll.scrollTop;
  }
  showsJump(scroll?: Viewport | null) {
    if (!scroll || this.following) return false;
    return distanceFromEnd(scroll) > JUMP_DISTANCE;
  }
  resume(scroll?: HTMLElement | null) {
    this.following = true;
    if (scroll) this.update(scroll);
  }
}
