// Playback controls for recorded events: play/pause, speed, step and scrub. They move the selection
// through events that are already loaded. They fetch nothing and run nothing: no model, tool,
// repository or provider call is made from here. Live following is a separate state (timeline.ts):
// it is on only while the selection sits on the newest recorded event.

export interface PlaybackControls {
  play: HTMLButtonElement;
  previous: HTMLButtonElement;
  next: HTMLButtonElement;
  speed: HTMLSelectElement;
  scrub: HTMLInputElement;
  position: HTMLElement;
  follow: HTMLButtonElement;
}

// One recorded event per tick at 1x; the speed control divides this interval.
const BASE_INTERVAL_MS = 1000;

export class Playback {
  private index = -1;
  private count = 0;
  private timer: number | undefined;

  constructor(private readonly controls: PlaybackControls, private readonly onSeek: (index: number) => void) {
    controls.play.addEventListener("click", () => this.toggle());
    controls.previous.addEventListener("click", () => this.step(-1));
    controls.next.addEventListener("click", () => this.step(1));
    controls.scrub.addEventListener("input", () => this.seek(Number(controls.scrub.value) - 1));
    controls.follow.addEventListener("click", () => this.seek(this.count - 1));
    controls.speed.addEventListener("change", () => {
      if (this.timer !== undefined) {
        this.pause();
        this.play();
      }
    });
  }

  // Called by the timeline after any change to the selection or the recorded events.
  sync(count: number, index: number, sequence: number | undefined): void {
    this.count = count;
    this.index = index;
    this.controls.scrub.max = String(Math.max(count, 1));
    this.controls.scrub.value = String(index + 1);
    this.controls.position.textContent = count === 0
      ? "no events recorded yet"
      : `#${sequence ?? "?"} (event ${index + 1} of ${count})`;
    this.controls.play.textContent = this.timer === undefined ? "Play" : "Pause";
    this.controls.play.disabled = count === 0;
  }

  get playing(): boolean {
    return this.timer !== undefined;
  }

  // User navigation stops playback first, so the selection never moves under the reader.
  step(delta: number): void {
    this.pause();
    this.seek(this.index + delta);
  }

  seek(index: number): void {
    this.pause();
    this.move(index);
  }

  toggle(): void {
    if (this.playing) {
      this.pause();
    } else {
      this.play();
    }
  }

  play(): void {
    if (this.count === 0) {
      return;
    }
    if (this.index >= this.count - 1) {
      this.move(0);
    }
    this.schedule();
    this.controls.play.textContent = "Pause";
  }

  pause(): void {
    if (this.timer !== undefined) {
      window.clearTimeout(this.timer);
      this.timer = undefined;
    }
    this.controls.play.textContent = "Play";
  }

  private schedule(): void {
    const speed = Number(this.controls.speed.value) || 1;
    this.timer = window.setTimeout(() => {
      if (this.index >= this.count - 1) {
        this.pause();
        return;
      }
      // The handle stays set while the selection moves, so the button still reads Pause.
      this.move(this.index + 1);
      this.schedule();
    }, BASE_INTERVAL_MS / speed);
  }

  private move(index: number): void {
    if (this.count === 0) {
      return;
    }
    this.onSeek(Math.min(Math.max(index, 0), this.count - 1));
  }
}
