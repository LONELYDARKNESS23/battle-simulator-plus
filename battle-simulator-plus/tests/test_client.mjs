import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ObserverScheduler, ResponseGate, battleChanged } from '../web/client-state.js';

class Clock {
  now = 0;
  serial = 0;
  tasks = new Map();
  setTimeout(callback, delay) {
    const id = ++this.serial;
    this.tasks.set(id, { at: this.now + delay, callback });
    return id;
  }
  clearTimeout(id) {
    this.tasks.delete(id);
  }
  advance(ms) {
    const end = this.now + ms;
    while (true) {
      const pending = [...this.tasks]
        .filter(([, t]) => t.at <= end)
        .sort((a, b) => a[1].at - b[1].at);
      if (!pending.length) break;
      const [id, task] = pending[0];
      this.now = task.at;
      this.tasks.delete(id);
      task.callback();
    }
    this.now = end;
  }
}

test('background polling does not postpone an observer turn', () => {
  const clock = new Clock();
  let turns = 0;
  const scheduler = new ObserverScheduler(() => turns++, 1500, clock);
  scheduler.update(true);
  clock.advance(700);
  scheduler.update(true);
  clock.advance(700);
  scheduler.update(true);
  assert.equal(turns, 0);
  clock.advance(100);
  assert.equal(turns, 1);
  assert.equal(clock.tasks.size, 0);
});
test('pause or an open dialog cancels the pending turn', () => {
  const clock = new Clock();
  let turns = 0;
  const scheduler = new ObserverScheduler(() => turns++, 1500, clock);
  scheduler.update(true);
  clock.advance(1000);
  scheduler.update(false);
  clock.advance(5000);
  assert.equal(turns, 0);
  scheduler.update(true);
  clock.advance(1500);
  assert.equal(turns, 1);
});
test('scheduler never creates duplicate pending turns', () => {
  const clock = new Clock();
  let turns = 0;
  const scheduler = new ObserverScheduler(() => turns++, 1500, clock);
  for (let i = 0; i < 100; i++) scheduler.update(true);
  assert.equal(clock.tasks.size, 1);
  clock.advance(1500);
  assert.equal(turns, 1);
});
test('poll responses started before a mutation are discarded after it finishes', () => {
  const gate = new ResponseGate();
  const old = gate.ticket();
  gate.invalidate();
  gate.invalidate();
  assert.equal(gate.accepts(old), false);
  assert.equal(gate.accepts(gate.ticket()), true);
});
test('another mutation invalidates a poll started while a form was saving', () => {
  const gate = new ResponseGate();
  gate.invalidate();
  const intermediate = gate.ticket();
  gate.invalidate();
  assert.equal(gate.accepts(intermediate), false);
});
test('load/new match and server restart refresh units even at the same engine revision', () => {
  const previous = { session_id: 'one', battle_id: 2, revision: 0, serial: 1 };
  assert.equal(battleChanged(previous, { ...previous, battle_id: 3 }), true);
  assert.equal(battleChanged(previous, { ...previous, session_id: 'two' }), true);
  assert.equal(battleChanged(previous, { ...previous, serial: 2 }), true);
  assert.equal(battleChanged(previous, { ...previous }), false);
});
