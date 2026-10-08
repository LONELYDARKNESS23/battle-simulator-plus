/** Small lifecycle helpers, also exercised by the Node regression suite. */
export class ObserverScheduler {
  constructor(callback, delay = 1500, clock = globalThis) {
    this.callback = callback;
    this.delay = delay;
    this.clock = clock;
    this.timer = null;
  }

  update(active) {
    if (!active) {
      this.stop();
      return;
    }
    if (this.timer !== null) return;
    this.timer = this.clock.setTimeout(() => {
      this.timer = null;
      this.callback();
    }, this.delay);
  }

  stop() {
    if (this.timer !== null) this.clock.clearTimeout(this.timer);
    this.timer = null;
  }
}

export class ResponseGate {
  constructor() {
    this.epoch = 0;
  }
  invalidate() {
    this.epoch += 1;
  }
  ticket() {
    return this.epoch;
  }
  accepts(ticket) {
    return ticket === this.epoch;
  }
}

export function battleChanged(previous, next) {
  return (
    !previous ||
    previous.session_id !== next.session_id ||
    previous.battle_id !== next.battle_id ||
    previous.revision !== next.revision ||
    previous.serial !== next.serial
  );
}
