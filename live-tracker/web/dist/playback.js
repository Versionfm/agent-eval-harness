// Playback controls for recorded events: play/pause, speed, step and scrub. They move the selection
// through events that are already loaded. They fetch nothing and run nothing: no model, tool,
// repository or provider call is made from here. Live following is a separate state (timeline.ts):
// it is on only while the selection sits on the newest recorded event.
// One recorded event per tick at 1x; the speed control divides this interval.
const BASE_INTERVAL_MS = 1000;
export class Playback {
    constructor(controls, onSeek) {
        this.controls = controls;
        this.onSeek = onSeek;
        this.index = -1;
        this.count = 0;
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
        document.addEventListener("keydown", (event) => this.shortcut(event));
    }
    // Keyboard: arrows step, Space plays or pauses, Home and End jump. Fields keep their own keys, and Space
    // stays with a focused button or map node.
    shortcut(event) {
        const target = event.target;
        if (event.altKey || event.ctrlKey || event.metaKey || target.closest("input, select, textarea, [contenteditable]")) {
            return;
        }
        if (event.key === " " && target.closest("button, a, [role=button]")) {
            return;
        }
        const actions = {
            ArrowLeft: () => this.step(-1),
            ArrowRight: () => this.step(1),
            " ": () => this.toggle(),
            Home: () => this.seek(0),
            End: () => this.seek(this.count - 1),
        };
        const action = actions[event.key];
        if (action) {
            event.preventDefault();
            action();
        }
    }
    showPlaying(playing) {
        this.controls.play.dataset.playing = String(playing);
        this.controls.play.querySelector(".label").textContent = playing ? "Pause" : "Play";
    }
    // Called by the timeline after any change to the selection or the recorded events.
    sync(count, index, sequence) {
        this.count = count;
        this.index = index;
        this.controls.scrub.max = String(Math.max(count, 1));
        this.controls.scrub.value = String(index + 1);
        this.controls.position.textContent = count === 0
            ? "no events recorded yet"
            : `#${sequence ?? "?"} · ${index + 1} of ${count}`;
        this.showPlaying(this.timer !== undefined);
        this.controls.play.disabled = count === 0;
    }
    get playing() {
        return this.timer !== undefined;
    }
    // User navigation stops playback first, so the selection never moves under the reader.
    step(delta) {
        this.pause();
        this.seek(this.index + delta);
    }
    seek(index) {
        this.pause();
        this.move(index);
    }
    toggle() {
        if (this.playing) {
            this.pause();
        }
        else {
            this.play();
        }
    }
    play() {
        if (this.count === 0) {
            return;
        }
        if (this.index >= this.count - 1) {
            this.move(0);
        }
        this.schedule();
        this.showPlaying(true);
    }
    pause() {
        if (this.timer !== undefined) {
            window.clearTimeout(this.timer);
            this.timer = undefined;
        }
        this.showPlaying(false);
    }
    schedule() {
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
    move(index) {
        if (this.count === 0) {
            return;
        }
        this.onSeek(Math.min(Math.max(index, 0), this.count - 1));
    }
}
