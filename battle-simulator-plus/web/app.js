'use strict';
import { ground, loadArt, drawFigure } from './battlefield-art.js';
import { ObserverScheduler, ResponseGate, battleChanged } from './client-state.js';
const $ = (id) => document.getElementById(id);
const roleIcons = { assault: '⌁', ranger: '⌖', medic: '+', heavy: '⬡' };
const colors = { blue: '#a2e6c1', red: '#ef967e', neutral: '#b4b69a' };
let state = null,
  selected = 'b1',
  actionMode = 'move',
  hover = null,
  keyboardCell = null;
let pending = false,
  gameStarted = false,
  sound = false,
  audioContext = null,
  lastEvent = 0;
let animation = {},
  effects = [],
  advice = null,
  victoryShown = false,
  toastTimer = null;
let observerPaused = false,
  frameRequest = null,
  backgroundCanvas = null,
  backgroundKey = '';
const responseGate = new ResponseGate();
const observerScheduler = new ObserverScheduler(() => command('/api/auto'));
let apiKeyEnv = 'BATTLE_API_KEY';
let settingsConfig = null;
let serverClosed = false;
const canvas = $('battlefield'),
  ctx = canvas.getContext('2d');
let viewW = 800,
  viewH = 550;
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

function storeGet(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function storeSet(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* Browser storage is optional. */
  }
}
function unit(id) {
  return state?.units.find((u) => u.id === id);
}
function liveUnitAt(x, y) {
  return state?.units.find((u) => u.hp > 0 && u.x === x && u.y === y);
}
function canAct() {
  return gameStarted && state?.phase === 'player' && state.mode === 'command' && !pending;
}
function legalFor(id = selected) {
  return state?.legal?.[id] || [];
}
function showToast(text, error = false) {
  $('toast').textContent = text;
  $('toast').classList.toggle('error', error);
  $('toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ($('toast').hidden = true), 3800);
}
function beep(kind = 'click') {
  if (!sound) return;
  try {
    audioContext ||= new (window.AudioContext || window.webkitAudioContext)();
    if (audioContext.state === 'suspended') audioContext.resume();
    const osc = audioContext.createOscillator(),
      gain = audioContext.createGain();
    osc.type = kind === 'attack' ? 'triangle' : 'sine';
    const f = kind === 'attack' ? 140 : kind === 'capture' ? 620 : 400;
    osc.frequency.setValueAtTime(f, audioContext.currentTime);
    osc.frequency.exponentialRampToValueAtTime(f * 0.45, audioContext.currentTime + 0.12);
    gain.gain.setValueAtTime(0.045, audioContext.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, audioContext.currentTime + 0.17);
    osc.connect(gain);
    gain.connect(audioContext.destination);
    osc.start();
    osc.stop(audioContext.currentTime + 0.18);
  } catch {
    /* Audio never blocks gameplay. */
  }
}
async function api(path, body) {
  const mutation = body !== undefined;
  if (mutation) responseGate.invalidate();
  try {
    let response;
    try {
      response = await fetch(
        path,
        mutation
          ? {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', 'X-Battle-Client': '1' },
              body: JSON.stringify(body),
            }
          : {},
      );
    } catch {
      $('connection-error').hidden = false;
      throw new Error('Нет связи с сервером игры');
    }
    $('connection-error').hidden = true;
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(data.error || 'Не удалось выполнить запрос');
      error.status = response.status;
      throw error;
    }
    return data;
  } finally {
    if (mutation) responseGate.invalidate();
  }
}
async function command(path, body = {}) {
  if (pending) return false;
  pending = true;
  renderControls();
  try {
    const next = await api(path, {
      ...body,
      expected_revision: state.state_revision,
      expected_session: state.session_id,
    });
    advice = null;
    acceptState(next);
    beep();
    return true;
  } catch (error) {
    showToast(error.message, true);
    if (error.status === 409) {
      try {
        acceptState(await api('/api/state'));
      } catch {
        /* Reconnect banner is already visible. */
      }
    }
    return false;
  } finally {
    pending = false;
    renderControls();
    scheduleObserver();
  }
}
function acceptState(next, reset = false) {
  if (next.unchanged) {
    state.ai = next.ai;
    renderCommander();
    scheduleObserver();
    return;
  }
  const old = state,
    now = performance.now();
  const serverRestarted = old && old.session_id !== next.session_id;
  const newBattle =
    old && old.battle_id !== next.battle_id && next.round === 1 && next.revision === 0;
  const changed = reset || battleChanged(old, next);
  if (reset || serverRestarted || newBattle || next.serial < lastEvent) {
    lastEvent = 0;
    effects = [];
    animation = {};
    victoryShown = false;
  }
  if (old && changed && !reset && !serverRestarted && !newBattle) {
    for (const u of next.units) {
      const before = old.units.find((v) => v.id === u.id);
      if (before && (u.x !== before.x || u.y !== before.y)) {
        const pos = displayedPosition(before, now);
        const moves = next.events.filter(e => e.id > lastEvent && e.kind === 'move' && e.unit === u.id);
        const route = moves.flatMap(e => e.path || []).map(([x, y]) => ({x, y}));
        animation[u.id] = { points: [pos, ...(route.length ? route : [{x: u.x, y: u.y}])], start: now }; 
      }
    }
    for (const e of next.events.filter((e) => e.id > lastEvent)) {
      if (['attack', 'grenade', 'heal', 'capture', 'death'].includes(e.kind)) {
        effects.push({ ...e, born: now + effects.filter((f) => f.born > now).length * 80 });
        if (e.kind === 'attack' || e.kind === 'capture') beep(e.kind);
      }
    }
  }
  state = next;
  lastEvent = Math.max(0, ...next.events.map((e) => e.id));
  if (!unit(selected)?.hp)
    selected = next.units.find((u) => u.team === 'blue' && u.hp > 0)?.id || 'b1';
  if (changed) {
    renderRoster();
    renderLog();
  }
  renderStatus();
  renderControls();
  if (hover) updateTooltip();
  if (gameStarted && state.phase === 'finished' && !victoryShown) showVictory();
  scheduleObserver();
  if (serverRestarted) {
    gameStarted = false;
    observerScheduler.stop();
    renderScenarios();
    openBriefing();
    showToast('Сервер перезапущен. Продолжите сохранённую операцию или начните новую.');
    renderControls();
  }
}
function make(tag, cls, text) {
  const element = document.createElement(tag);
  if (cls) element.className = cls;
  if (text !== undefined) element.textContent = text;
  return element;
}
function renderRoster() {
  $('roster').replaceChildren();
  $('enemy-roster').replaceChildren();
  for (const [i, u] of state.units.filter((u) => u.team === 'blue').entries()) {
    const card = make(
      'button',
      `unit-card${u.id === selected ? ' selected' : ''}${u.hp <= 0 ? ' dead' : ''}${u.ap <= 0 ? ' exhausted' : ''}`,
    );
    card.disabled = u.hp <= 0;
    card.dataset.unit = u.id;
    card.setAttribute('aria-pressed', String(u.id === selected));
    card.setAttribute(
      'aria-label',
      `${u.name}, ${u.title}, здоровье ${u.hp} из ${u.max_hp}, ${u.ap} очка действия`,
    );
    card.append(
      make('span', 'role-icon', roleIcons[u.role]),
      make('span', 'card-hotkey', `0${i + 1}`),
    );
    const data = make('div', 'unit-data');
    data.append(make('strong', '', u.name), make('span', 'role-label', u.title));
    const hp = make('div', 'hp-row'),
      track = make('div', 'hp-track'),
      fill = make('i', 'hp-fill');
    fill.style.width = `${(u.hp / u.max_hp) * 100}%`;
    if (u.hp / u.max_hp < 0.3) fill.style.background = '#ef967e';
    track.append(fill);
    hp.append(track, make('span', 'hp-number', `${u.hp}/${u.max_hp}`));
    data.append(hp);
    const ap = make('div', 'ap-row');
    for (let n = 0; n < 2; n++) {
      const dot = make('i', 'ap-dot');
      if (n >= u.ap) dot.style.background = '#3d5554';
      ap.append(dot);
    }
    ap.append(
      make(
        'small',
        '',
        u.hp <= 0 ? 'ВЫБЫЛ' : u.guard ? 'ПРИКРЫТИЕ' : u.suppressed ? 'ПОДАВЛЕН' : `${u.ap} ОД`,
      ),
    );
    data.append(ap);
    card.append(data);
    card.addEventListener('click', () => selectUnit(u.id));
    $('roster').append(card);
  }
  for (const u of state.units.filter((u) => u.team === 'red')) {
    const mini = make('div', `enemy-mini${u.hp <= 0 ? ' dead' : ''}`);
    mini.title = `${u.name} · ${u.title} · ${u.hp}/${u.max_hp} HP`;
    mini.append(
      make('div', '', roleIcons[u.role]),
      make('small', '', u.hp > 0 ? `${u.hp} HP` : 'ВЫБЫЛ'),
    );
    $('enemy-roster').append(mini);
  }
}
function renderLog() {
  const icons = {
    move: '↗',
    attack: '⌖',
    heal: '+',
    guard: '⬡',
    death: '×',
    capture: '◇',
    turn: '→',
    score: '≡',
    victory: '★',
    grenade: '◈',
    plan: '⌁',
    system: '·',
  };
  const log = $('combat-log');
  log.replaceChildren();
  for (const e of [...state.events].reverse().slice(0, 40)) {
    const item = make('div', `log-item ${e.team || ''}`),
      data = make('div');
    data.append(
      make(
        'small',
        '',
        `РАУНД ${String(e.round).padStart(2, '0')} / ${e.team === 'red' ? 'ПРОТИВНИК' : e.team === 'blue' ? 'ВАШ ОТРЯД' : 'ОПЕРАЦИЯ'}`,
      ),
      make('span', '', e.text),
    );
    item.append(make('span', 'event-mark', icons[e.kind] || '·'), data);
    log.append(item);
  }
  $('log-count').textContent = String(state.events.length).padStart(2, '0');
}
function renderStatus() {
  $('scenario-name').textContent = state.scenario_info.name;
  $('scenario-subtitle').textContent = state.scenario_info.subtitle.toUpperCase();
  $('header-sector').textContent = state.scenario_info.subtitle.split('·')[1].trim().toUpperCase();
  $('operation-id').textContent = String(
    ['foundry', 'crossroads', 'relay'].indexOf(state.scenario) + 1,
  ).padStart(2, '0');
  $('blue-score').textContent = String(state.score.blue).padStart(2, '0');
  $('red-score').textContent = String(state.score.red).padStart(2, '0');
  $('round-number').textContent = String(state.round).padStart(2, '0');
  const alive = state.units.filter((u) => u.team === 'blue' && u.hp > 0).length;
  $('squad-count').textContent = `0${alive} / 04`;
  const phaseText =
    state.phase === 'enemy'
      ? 'Ход противника'
      : state.phase === 'finished'
        ? 'Бой завершён'
        : state.mode === 'observe'
          ? observerPaused
            ? 'Наблюдение: пауза'
            : 'Режим наблюдения'
          : 'Ваш ход';
  $('map-phase').replaceChildren(make('i'), document.createTextNode(phaseText));
  $('map-phase').style.color = state.phase === 'enemy' ? colors.red : colors.blue;
  $('squad-status').textContent =
    state.phase === 'player'
      ? state.mode === 'observe'
        ? 'Автопилот включён'
        : 'Ожидает приказов'
      : phaseText;
  $('objectives').replaceChildren();
  $('point-score').replaceChildren();
  for (const p of state.points) {
    const mini = make('i', '', p.id);
    if (p.owner) {
      mini.style.color = colors[p.owner];
      mini.style.borderColor = colors[p.owner];
    }
    if (p.contested) {
      mini.style.borderStyle = 'dashed';
      mini.title = 'Спорный узел: без очков';
    }
    $('point-score').append(mini);
    const objective = make('div', `objective ${p.owner || ''}${p.contested ? ' contested' : ''}`);
    objective.append(
      make('strong', '', p.id),
      make(
        'small',
        '',
        p.contested
          ? 'СПОРНЫЙ'
          : p.owner === 'blue'
            ? 'ВАШ +5'
            : p.owner === 'red'
              ? 'ВРАГ +5'
              : 'СВОБОДЕН',
      ),
    );
    $('objectives').append(objective);
  }
  renderCommander();
}
function renderCommander() {
  const ai = state.ai;
  $('commander-name').textContent =
    ai.configured === 'builtin'
      ? 'Тактический ИИ'
      : `${ai.configured === 'ollama' ? 'Ollama' : 'API'} / ${ai.model}`;
  $('commander-detail').textContent = ai.fallback
    ? 'Резервный ИИ · ' + ai.message
    : state.phase === 'enemy'
      ? 'Составляет план отряда…'
      : ai.latency
        ? `Последний ход: ${ai.latency} с · ${ai.source === 'builtin' ? 'локально' : 'модель'}`
        : 'Готов к бою · ' + (ai.configured === 'builtin' ? 'локально' : 'модель подключена');
  $('commander-detail').title = ai.message;
  $('commander-detail').parentElement.parentElement.classList.toggle('warning', ai.fallback);
  $('thinking-banner').hidden = state.phase !== 'enemy';
  $('thinking-time').textContent =
    `${ai.busy_seconds.toFixed(1)} с · ${ai.configured === 'builtin' ? 'тактический ИИ' : ai.model}`;
}
function renderControls() {
  if (!state) return;
  requestPaint();
  const u = unit(selected),
    legal = legalFor();
  $('selected-icon').textContent = u ? roleIcons[u.role] : '◇';
  $('selected-name').textContent = u?.name || 'Отряд';
  $('selected-description').textContent = u
    ? `${u.title} · ${u.ap} ОД · дальность ${u.range} · смотрит ${['→','↘','↓','↙','←','↖','↑','↗'][Math.round((u.facing || 0) / 45) % 8]}`
    : 'Операция завершена';
  $('skill-label').textContent = u?.skill || 'Способность';
  for (const button of $('actions').children) {
    const mode = button.dataset.mode;
    button.disabled = !canAct() || !legal.some((a) => a.type === mode);
    button.classList.toggle('active', actionMode === mode);
    button.setAttribute('aria-pressed', String(actionMode === mode));
    button.title =
      mode === 'skill'
        ? `${u?.description || ''}${u?.cooldown ? ' Готова через ' + u.cooldown + ' своих хода.' : ''}`
        : mode === 'guard'
          ? 'Защита −7 урона и ответный огонь. Завершает действия бойца.'
          : mode === 'move'
            ? `До ${u?.move || 0} клеток по свободному пути · 1 ОД`
            : 'Выберите врага с открытой линией огня · 1 ОД';
  }
  $('next-unit-btn').disabled = !canAct() || !state.units.some(v => v.team === 'blue' && v.hp > 0 && v.ap > 0);
  $('advice-btn').disabled = !canAct() || !u?.ap;
  $('end-turn-btn').disabled = pending || state.phase !== 'player' || state.mode === 'observe';
  $('auto-btn').disabled = pending || state.phase !== 'player' || state.mode === 'observe';
  $('undo-btn').disabled = pending || !state.can_undo;
  $('save-btn').disabled = pending || state.phase === 'enemy';
  $('load-btn').disabled = pending || !state.has_save;
  $('fallback-btn').disabled = pending;
  $('pause-btn').hidden = state.mode !== 'observe';
  $('pause-btn').textContent = observerPaused ? '▶ Продолжить' : 'Ⅱ Пауза';
  const hint = $('action-hint');
  hint.classList.toggle('advice', Boolean(advice));
  if (advice) hint.textContent = adviceText(advice);
  else if (state.phase === 'finished')
    hint.textContent = 'Операция завершена. Сохраните журнал или начните новый бой.';
  else if (state.mode === 'observe')
    hint.textContent = observerPaused
      ? 'Наблюдение приостановлено. Текущий ход противника завершится; нажмите «Продолжить» или P для следующего раунда.'
      : 'Автопилот ведёт ваш отряд. P — пауза; для ручного управления начните новую операцию.';
  else if (state.phase === 'enemy')
    hint.textContent = 'Противник выполняет план. После его хода все ваши бойцы получат новые ОД.';
  else if (!u?.ap) hint.textContent = 'У бойца закончились ОД. Выберите другого или завершите ход.';
  else if (actionMode === 'move')
    hint.textContent = `Подсвеченные клетки доступны за 1 ОД. Дальность перемещения: ${u.move}.`;
  else if (actionMode === 'attack')
    hint.textContent =
      'Нажмите на подсвеченного врага. Урон указан при наведении; стены перекрывают огонь.';
  else if (actionMode === 'skill')
    hint.textContent = `${u.description} ${u.cooldown ? 'Перезарядка: ' + u.cooldown + '.' : 'Выберите подсвеченную цель.'}`;
  else hint.textContent = 'Выберите действие, затем клетку на карте.';
}
function adviceText(a) {
  if (a.type === 'move')
    return `Совет: переместиться в ${a.x + 1}:${a.y + 1}. Рекомендуемая клетка выделена белым. Нажмите её для выполнения.`;
  if (a.type === 'guard') return 'Совет: прикрыть сектор. Нажмите «Прикрытие», чтобы выполнить.';
  if (a.type === 'skill' && a.x !== undefined)
    return `Совет: граната в ${a.x + 1}:${a.y + 1}. Нажмите выделенную клетку.`;
  return `Совет: ${a.heal ? 'вылечить' : a.type === 'skill' ? 'применить способность к' : 'атаковать'} ${unit(a.target)?.name || a.target}${a.damage ? ' (−' + a.damage + ' HP)' : ''}. Нажмите выделенную цель.`;
}
function selectUnit(id) {
  if (!unit(id)?.hp) return;
  selected = id;
  actionMode = 'move';
  advice = null;
  keyboardCell = { x: unit(id).x, y: unit(id).y };
  renderRoster();
  renderControls();
  beep();
}
function setMode(mode) {
  if (!canAct() || !legalFor().some((a) => a.type === mode)) {
    if (mode === 'skill' && unit(selected)?.cooldown)
      showToast(`Способность перезаряжается ещё ${unit(selected).cooldown} своих хода`);
    return;
  }
  advice = null;
  if (mode === 'guard') {
    command('/api/action', { unit: selected, action: { type: 'guard' } });
    return;
  }
  actionMode = mode;
  renderControls();
  beep();
}
function actionAt(x, y) {
  const target = liveUnitAt(x, y);
  return legalFor().find(
    (a) =>
      a.type === actionMode &&
      (a.x !== undefined ? a.x === x && a.y === y : a.target && a.target === target?.id),
  );
}
function clickCell(cell) {
  if (!cell || !state) return;
  const target = liveUnitAt(cell.x, cell.y),
    action = actionAt(cell.x, cell.y);
  if (canAct() && action) {
    command('/api/action', { unit: selected, action });
    return;
  }
  if (target?.team === 'blue') {
    selectUnit(target.id);
    return;
  }
  if (!canAct()) {
    if (state.phase === 'enemy') showToast('Сейчас ход противника');
    return;
  }
  showToast(
    actionMode === 'move'
      ? 'Клетка недоступна. Выберите подсвеченную позицию.'
      : 'Нет доступной цели: проверьте дистанцию, ОД и линию огня.',
  );
}
function cellFromEvent(event) {
  const r = canvas.getBoundingClientRect();
  const x = Math.floor(((event.clientX - r.left) / r.width) * 16),
    y = Math.floor(((event.clientY - r.top) / r.height) * 11);
  return x >= 0 && x < 16 && y >= 0 && y < 11 ? { x, y } : null;
}
canvas.addEventListener('pointermove', (e) => {
  hover = cellFromEvent(e);
  updateTooltip();
});
canvas.addEventListener('pointerleave', () => {
  hover = null;
  $('cell-tooltip').hidden = true;
  requestPaint();
});
canvas.addEventListener('focus', requestPaint);
canvas.addEventListener('blur', requestPaint);
canvas.addEventListener('click', (e) => {
  keyboardCell = cellFromEvent(e);
  clickCell(keyboardCell);
});
function updateTooltip() {
  requestPaint();
  if (!hover || !state) return;
  const u = liveUnitAt(hover.x, hover.y),
    a = actionAt(hover.x, hover.y);
  let text = `${hover.x + 1}:${hover.y + 1} · `;
  text += u
    ? `${u.name} · ${u.hp}/${u.max_hp} HP`
    : state.walls.some(([x, y]) => x === hover.x && y === hover.y)
      ? 'Стена · непроходимо'
      : state.cover.some(([x, y]) => x === hover.x && y === hover.y)
        ? 'Укрытие · −5 входящего урона'
        : 'Открытая местность';
  if (a)
    text +=
      a.type === 'move'
        ? ' · движение: 1 ОД'
        : a.heal
          ? ` · лечение +${a.heal} HP`
          : a.damage
            ? ` · урон ${a.damage}${a.targets ? ' по области' : ''} · ${a.cost} ОД`
            : '';
  if (u?.guard) text += ' · прикрытие';
  if (u?.suppressed) text += ' · подавлен';
  $('cell-tooltip').textContent = text;
  $('cell-tooltip').hidden = false;
}
for (const b of $('actions').children) b.addEventListener('click', () => setMode(b.dataset.mode));
$('end-turn-btn').addEventListener('click', () => command('/api/end-turn'));
$('auto-btn').addEventListener('click', () => command('/api/auto'));
$('pause-btn').addEventListener('click', () => {
  observerPaused = !observerPaused;
  renderStatus();
  renderControls();
  scheduleObserver();
});
$('undo-btn').addEventListener('click', () => command('/api/undo'));
$('fallback-btn').addEventListener('click', () => command('/api/fallback'));
$('advice-btn').addEventListener('click', async () => {
  if (!canAct()) return;
  try {
    const response = await api('/api/advice', { unit: selected });
    advice = response.action;
    if (advice) actionMode = advice.type;
    else showToast('У бойца нет доступных действий');
    renderControls();
  } catch (e) {
    showToast(e.message, true);
  }
});
$('save-btn').addEventListener('click', async () => {
  if (await command('/api/save'))
    showToast('Операция сохранена. Действия также сохраняются автоматически.');
});
$('load-btn').addEventListener('click', async () => {
  if (pending) return;
  pending = true;
  try {
    acceptState(await api('/api/load', {}), true);
    gameStarted = true;
    advice = null;
    showToast('Операция загружена');
  } catch (e) {
    showToast(e.message, true);
  } finally {
    pending = false;
    renderControls();
  }
});
$('export-btn').addEventListener('click', async () => {
  try {
    const data = await api('/api/export');
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }),
    );
    const a = make('a');
    a.href = url;
    a.download = `rift-${state.scenario}-round-${state.round}.json`;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showToast('Журнал боя экспортирован');
  } catch (e) {
    showToast(e.message, true);
  }
});
$('sound-btn').addEventListener('click', () => {
  sound = !sound;
  $('sound-btn').classList.toggle('active', sound);
  $('sound-btn').title = sound ? 'Выключить звук' : 'Включить звук';
  $('sound-btn').setAttribute('aria-label', $('sound-btn').title);
  storeSet('rift-sound', String(sound));
  beep();
});
$('dismiss-tutorial').addEventListener('click', () => {
  $('tutorial').hidden = true;
  storeSet('rift-tutorial', 'dismissed');
});
document
  .querySelectorAll('[data-close]')
  .forEach((button) => button.addEventListener('click', () => $(button.dataset.close).close()));
$('help-btn').addEventListener('click', () => $('help-dialog').showModal());
function openBriefing() {
  observerScheduler.stop();
  $('cancel-briefing').hidden = !gameStarted;
  $('resume-btn').hidden = !state?.has_save;
  $('briefing-dialog').showModal();
}
$('new-btn').addEventListener('click', openBriefing);
$('victory-new').addEventListener('click', () => {
  $('victory-dialog').close();
  openBriefing();
});
$('cancel-briefing').addEventListener('click', () => {
  $('briefing-dialog').close();
  scheduleObserver();
});
$('briefing-dialog').addEventListener('cancel', (e) => {
  if (!gameStarted) e.preventDefault();
});
function renderScenarios() {
  $('scenario-options').replaceChildren();
  for (const [i, s] of state.scenarios.entries()) {
    const b = make(
      'button',
      `scenario-option${s.id === $('scenario-select').value ? ' active' : ''}`,
    );
    b.type = 'button';
    b.setAttribute('aria-pressed', String(s.id === $('scenario-select').value));
    b.append(make('small', '', `СЕКТОР 0${i + 1}`), document.createTextNode(s.name));
    b.addEventListener('click', () => {
      $('scenario-select').value = s.id;
      renderScenarios();
    });
    $('scenario-options').append(b);
  }
  $('brief-description').textContent =
    state.scenarios.find((s) => s.id === $('scenario-select').value)?.brief || '';
}
$('start-btn').addEventListener('click', async () => {
  if (pending) return;
  pending = true;
  $('start-btn').disabled = true;
  try {
    const next = await api('/api/new', {
      scenario: $('scenario-select').value,
      difficulty: $('difficulty-select').value,
      mode: $('mode-select').value,
    });
    gameStarted = true;
    observerPaused = false;
    victoryShown = false;
    advice = null;
    selected = 'b1';
    actionMode = 'move';
    acceptState(next, true);
    $('briefing-dialog').close();
    renderControls();
    beep('capture');
  } catch (e) {
    showToast(e.message, true);
  } finally {
    pending = false;
    $('start-btn').disabled = false;
    renderControls();
    scheduleObserver();
  }
});
$('resume-btn').addEventListener('click', async () => {
  if (pending) return;
  pending = true;
  try {
    const next = await api('/api/load', { slot: 'auto' });
    gameStarted = true;
    victoryShown = false;
    acceptState(next, true);
    $('briefing-dialog').close();
    if (next.phase === 'finished') showVictory();
  } catch (e) {
    showToast(e.message, true);
  } finally {
    pending = false;
    renderControls();
    scheduleObserver();
  }
});
function scheduleObserver() {
  if (serverClosed) { observerScheduler.stop(); return; }
  observerScheduler.update(
    gameStarted &&
      state?.mode === 'observe' &&
      state.phase === 'player' &&
      !pending &&
      !observerPaused &&
      !document.hidden &&
      !document.querySelector('dialog[open]'),
  );
}
document.querySelectorAll('dialog').forEach((d) => d.addEventListener('close', scheduleObserver));
function showVictory() {
  if (victoryShown) return;
  const win = state.winner;
  $('victory-title').textContent =
    win === 'blue' ? 'Операция успешна' : win === 'red' ? 'Операция проиграна' : 'Равные силы';
  $('victory-symbol').textContent = win === 'blue' ? '◇' : win === 'red' ? '×' : '≡';
  $('victory-symbol').style.color = win === 'red' ? colors.red : colors.blue;
  $('victory-reason').textContent = state.reason;
  $('victory-stats').replaceChildren();
  for (const [value, label] of [
    [`${state.score.blue}:${state.score.red}`, 'ИТОГОВЫЙ СЧЁТ'],
    [state.round, 'РАУНДОВ'],
    [state.units.filter((u) => u.team === 'blue' && u.hp > 0).length, 'БОЙЦОВ В СТРОЮ'],
  ]) {
    const div = make('div');
    div.append(make('b', '', value), make('small', '', label));
    $('victory-stats').append(div);
  }
  if (!document.querySelector('dialog[open]')) {
    victoryShown = true;
    $('victory-dialog').showModal();
  }
}
function providerFields() {
  const p = $('provider').value;
  $('network-fields').hidden = p === 'builtin';
  $('key-fields').hidden = p !== 'openai';
  $('models-btn').hidden = p !== 'ollama';
  $('thinking-field').hidden = p !== 'ollama';
  for (const input of [$('base-url'), $('model-name'), $('timeout')])
    input.required = p !== 'builtin';
  $('network-fields')
    .querySelectorAll('input')
    .forEach((input) => (input.disabled = p === 'builtin'));
}
$('provider').addEventListener('change', () => {
  const p = $('provider').value;
  if (p === 'ollama') $('base-url').value = 'http://127.0.0.1:11434';
  else if (p === 'openai' && $('base-url').value.endsWith(':11434'))
    $('base-url').value = 'http://127.0.0.1:1234/v1';
  providerFields();
});
$('settings-btn').addEventListener('click', async () => {
  try {
    const c = await api('/api/config');
    settingsConfig = c;
    apiKeyEnv = c.api_key_env;
    $('provider').value = c.provider;
    $('base-url').value = c.base_url;
    $('model-name').value = c.model;
    $('timeout').value = c.timeout;
    $('structured').checked = c.structured;
    $('thinking').checked = c.thinking;
    $('api-key').value = '';
    $('clear-key').checked = false;
    $('api-key').placeholder = c.has_key
      ? 'Ключ уже задан · оставьте пустым, чтобы сохранить'
      : 'Ключ хранится только до закрытия сервера';
    $('settings-result').textContent = c.warning || '';
    providerFields();
    $('settings-dialog').showModal();
  } catch (e) {
    showToast(e.message, true);
  }
});
function configBody() {
  if ($('provider').value === 'builtin')
    return { ...settingsConfig, provider: 'builtin', api_key: '', clear_key: false };
  return {
    provider: $('provider').value,
    base_url: $('base-url').value,
    model: $('model-name').value,
    api_key_env: apiKeyEnv,
    timeout: Number($('timeout').value),
    structured: $('structured').checked,
    thinking: $('thinking').checked,
    api_key: $('api-key').value,
    clear_key: $('clear-key').checked,
  };
}
function settingsResult(text, error = false) {
  $('settings-result').textContent = text;
  $('settings-result').classList.toggle('error', error);
}
$('settings-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    await api('/api/config', configBody());
    $('api-key').value = '';
    $('clear-key').checked = false;
    settingsResult('Настройки сохранены. Новый командир вступит в бой со следующего хода.');
    acceptState(await api('/api/state'));
  } catch (e) {
    settingsResult(e.message, true);
  }
});
$('models-btn').addEventListener('click', async () => {
  $('models-btn').disabled = true;
  settingsResult('Ищем установленные модели…');
  try {
    const data = await api('/api/models', configBody());
    $('models-list').replaceChildren();
    for (const name of data.models) {
      const option = make('option');
      option.value = name;
      $('models-list').append(option);
    }
    settingsResult(`Найдено моделей: ${data.models.length}. Выберите модель в поле выше.`);
    if (!data.models.includes($('model-name').value) && data.models.length)
      $('model-name').value = data.models[0];
  } catch (e) {
    settingsResult(e.message, true);
  } finally {
    $('models-btn').disabled = false;
  }
});
$('test-btn').addEventListener('click', async () => {
  if (!$('settings-form').reportValidity()) return;
  $('test-btn').disabled = true;
  settingsResult('Проверяем реальный боевой план. Первый запрос может загружать модель…');
  try {
    const data = await api('/api/test-model', configBody());
    settingsResult(
      `План принят: ${data.orders.length} бойца, ${data.latency} с. Подключение работает. Нажмите «Сохранить настройки» для применения.`,
    );
  } catch (e) {
    settingsResult(e.message, true);
  } finally {
    $('test-btn').disabled = false;
  }
});
document.addEventListener('keydown', (e) => {
  if (
    document.querySelector('dialog[open]') ||
    ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName) ||
    !gameStarted
  )
    return;
  const key = e.key.toLowerCase();
  if (['1', '2', '3', '4'].includes(key)) {
    e.preventDefault();
    selectUnit(`b${key}`);
  } else if ({ m: 'move', f: 'attack', q: 'skill', g: 'guard' }[key]) {
    e.preventDefault();
    setMode({ m: 'move', f: 'attack', q: 'skill', g: 'guard' }[key]);
  } else if (e.code === 'Space') {
    e.preventDefault();
    if (canAct()) command('/api/end-turn');
  } else if (key === 'p' && state.mode === 'observe') {
    e.preventDefault();
    $('pause-btn').click();
  } else if (key === 'escape') {
    advice = null;
    actionMode = 'move';
    renderControls();
  } else if (
    document.activeElement === canvas &&
    ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)
  ) {
    e.preventDefault();
    keyboardCell ||= { x: unit(selected)?.x || 0, y: unit(selected)?.y || 0 };
    const [dx, dy] = {
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
    }[e.key];
    keyboardCell = {
      x: Math.min(15, Math.max(0, keyboardCell.x + dx)),
      y: Math.min(10, Math.max(0, keyboardCell.y + dy)),
    };
    hover = keyboardCell;
    updateTooltip();
  } else if (document.activeElement === canvas && e.key === 'Enter') {
    e.preventDefault();
    clickCell(keyboardCell);
  }
});

// Local raster art, cached terrain and resolution-independent tactical overlays.
let directions = storeGet('rift-directions') !== 'false';
$('directions-btn').setAttribute('aria-pressed', String(directions));
$('directions-btn').addEventListener('click', () => {
  directions = !directions;
  storeSet('rift-directions', String(directions));
  $('directions-btn').setAttribute('aria-pressed', String(directions));
  requestPaint();
});
$('focus-btn').addEventListener('click', () => {
  const active = document.body.classList.toggle('map-focus');
  $('focus-btn').setAttribute('aria-pressed', String(active));
  $('focus-btn').textContent = active ? '↙ Обычный вид' : '⛶ Крупная карта';
});
$('next-unit-btn').addEventListener('click', () => {
  const ready = state.units.filter(u => u.team === 'blue' && u.hp > 0 && u.ap > 0);
  if (ready.length) selectUnit(ready[(ready.findIndex(u => u.id === selected) + 1) % ready.length].id);
});
loadArt(() => { backgroundKey = ''; requestPaint(); });
function resizeCanvas() {
  const r = canvas.getBoundingClientRect(),
    dpr = Math.min(window.devicePixelRatio || 1, 2);
  viewW = r.width;
  viewH = r.height;
  canvas.width = Math.round(viewW * dpr);
  canvas.height = Math.round(viewH * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  requestPaint();
}
new ResizeObserver(resizeCanvas).observe(canvas);
function displayedPosition(u, now) {
  const a = animation[u.id];
  if (!a || reducedMotion) return { x: u.x, y: u.y };
  const segments = a.points.length - 1;
  const progress = Math.min(segments, (now - a.start) / 140);
  if (progress >= segments) {
    delete animation[u.id];
    return { x: u.x, y: u.y };
  }
  const index = Math.floor(progress), t = progress - index;
  const from = a.points[index], to = a.points[index + 1];
  return { x: from.x + (to.x - from.x) * t, y: from.y + (to.y - from.y) * t,
    facing: Math.atan2(to.y - from.y, to.x - from.x) * 180 / Math.PI };

}
function rounded(x, y, w, h, r, fill, stroke) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
  if (fill) {
    ctx.fillStyle = fill;
    ctx.fill();
  }
  if (stroke) {
    ctx.strokeStyle = stroke;
    ctx.stroke();
  }
}
function line(x1, y1, x2, y2, color, width = 1) {
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
}
function circle(x, y, r, fill, stroke) {
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  if (fill) {
    ctx.fillStyle = fill;
    ctx.fill();
  }
  if (stroke) {
    ctx.strokeStyle = stroke;
    ctx.stroke();
  }
}
function text(str, x, y, size, color, align = 'center') {
  ctx.font = `${size}px Consolas, monospace`;
  ctx.fillStyle = color;
  ctx.textAlign = align;
  ctx.textBaseline = 'middle';
  ctx.fillText(String(str), x, y);
}
function cellHighlight(x, y, color, alpha = 0.15) {
  const s = viewW / 16;
  ctx.globalAlpha = alpha;
  ctx.fillStyle = color;
  ctx.fillRect(x * s + 2, y * s + 2, s - 4, s - 4);
  ctx.globalAlpha = 1;
  const l = s * 0.16;
  for (const [dx, dy, sx, sy] of [
    [3, 3, 1, 1],
    [s - 3, 3, -1, 1],
    [3, s - 3, 1, -1],
    [s - 3, s - 3, -1, -1],
  ]) {
    line(x * s + dx, y * s + dy, x * s + dx + l * sx, y * s + dy, color, 1);
    line(x * s + dx, y * s + dy, x * s + dx, y * s + dy + l * sy, color, 1);
  }
}
function drawWall(x, y) {
  const s = viewW / 16,
    px = x * s,
    py = y * s;
  rounded(px + 6, py + 10, s - 10, s - 10, 2, '#0d1617');
  rounded(px + 4, py + 3, s - 10, s - 10, 2, '#4b5650', '#697566');
  ctx.fillStyle = '#363f3b';
  ctx.fillRect(px + 4, py + s - 13, s - 10, 6);
  if (ground.complete && ground.naturalWidth) {
    ctx.save(); ctx.globalAlpha = .22;
    ctx.drawImage(ground, (x * 73) % 600, (y * 53) % 600, 150, 150, px + 5, py + 4, s - 12, s - 20);
    ctx.restore();
  }
  for (const dx of [8, s - 13]) for (const dy of [8, s - 19]) {
    circle(px + dx, py + dy, Math.max(1, s * .025), '#b6b9a0', '#303d37');
  }
  line(px + 7, py + 8, px + s - 10, py + 8, '#7e8771', 1);
  line(px + s / 2, py + 10, px + s / 2, py + s - 16, '#35453c', 2);
  for (let i = 0; i < 3; i++)
    line(px + 8 + i * 4, py + s - 11, px + 11 + i * 4, py + s - 8, '#a9a177', 1);
}
function drawCover(x, y) {
  const s = viewW / 16,
    px = x * s,
    py = y * s;
  rounded(px + s * 0.17, py + s * 0.34, s * 0.67, s * 0.48, 2, '#0d1717');
  rounded(px + s * 0.13, py + s * 0.24, s * 0.64, s * 0.45, 2, '#70745a', '#a3a580');
  line(px + s * 0.13, py + s * 0.59, px + s * 0.77, py + s * 0.59, '#464f3f', 3);
  line(px + s * 0.25, py + s * 0.27, px + s * 0.25, py + s * 0.57, '#494f3f', 2);
  line(px + s * 0.65, py + s * 0.27, px + s * 0.65, py + s * 0.57, '#494f3f', 2);
  for (let i = 0; i < 5; i++) line(px + s * .32, py + s * (.29 + i * .045), px + s * .57, py + s * (.29 + i * .045), '#9a9e7840');
  text('▰', px + s * 0.46, py + s * 0.42, s * 0.19, '#bfc7a0');
}
function drawPoint(p, now) {
  const s = viewW / 16,
    x = (p.x + 0.5) * s,
    y = (p.y + 0.5) * s,
    c = p.contested ? '#dbcb8c' : colors[p.owner || 'neutral'];
  ctx.save();
  ctx.setLineDash([3, 5]);
  ctx.lineWidth = 1;
  circle(x, y, s * 1.3, null, c + '35');
  ctx.setLineDash([]);
  circle(x, y, s * 0.38, '#172724', c);
  circle(x, y, s * 0.27, null, c + '66');
  line(x, y - s * 0.2, x, y + s * 0.12, c, 2);
  line(x - s * 0.12, y + s * 0.2, x + s * 0.12, y + s * 0.2, c, 2);
  ctx.beginPath();
  ctx.arc(x, y - s * 0.08, s * 0.14, Math.PI * 1.15, Math.PI * 1.85);
  ctx.strokeStyle = c;
  ctx.stroke();
  rounded(x - s * 0.23, y - s * 0.69, s * 0.46, s * 0.26, 3, '#152723', c);
  text(p.id, x, y - s * 0.56, s * 0.18, c);
  if (p.contested) text('!', x + s * 0.29, y - s * 0.28, s * 0.24, '#e8d8a2');
  ctx.restore();
}
function drawSoldier(u, now) {
  const s = viewW / 16,
    p = displayedPosition(u, now),
    x = (p.x + 0.5) * s,
    y = (p.y + 0.5) * s,
    c = colors[u.team];
  if (u.hp <= 0) {
    ctx.globalAlpha = 0.25;
    line(x - 5, y - 5, x + 5, y + 5, c, 2);
    line(x + 5, y - 5, x - 5, y + 5, c, 2);
    ctx.globalAlpha = 1;
    return;
  }
  const isSelected = u.id === selected;
  circle(x + 1, y + 5, s * 0.27, '#071310aa');
  if (isSelected) {
    circle(x, y, s * 0.41, null, c);
    ctx.save();
    ctx.setLineDash([2, 3]);
    circle(x, y, s * 0.46, null, c + '55');
    ctx.restore();
  }
  if (u.guard) {
    circle(x, y, s * 0.35, c + '16', c + '77');
    text('⬡', x + s * 0.28, y - s * 0.25, s * 0.21, c);
  }
  drawFigure(ctx, { ...u, facing: p.facing ?? u.facing }, x, y, s, isSelected, directions);
  const labelY = y + s * 0.34;
  ctx.lineWidth = 1;
  rounded(x - s * 0.29, labelY, s * 0.58, s * 0.065, 1, '#11251d');
  ctx.fillStyle = c;
  ctx.fillRect(x - s * 0.29, labelY, (s * 0.58 * u.hp) / u.max_hp, s * 0.065);
  if (isSelected || (hover?.x === u.x && hover?.y === u.y)) {
    const nameY = Math.max(2, y - s * .88);
    rounded(x - s * 0.65, nameY, s * 1.3, s * 0.25, 3, '#0d1c1cf0', c + '55');
    text(u.name, x, nameY + s * .12, s * 0.16, '#e1e9d8');
  }
  text(
    u.role === 'medic' ? '+' : u.role === 'heavy' ? 'H' : u.role === 'ranger' ? 'R' : 'A',
    x - s * 0.26,
    y - s * 0.23,
    s * 0.14,
    c,
  );
  if (u.team === 'blue')
    for (let i = 0; i < 2; i++)
      circle(x - s * 0.075 + i * s * 0.15, y + s * 0.5, s * 0.025, i < u.ap ? c : '#4d6055');
  if (u.suppressed) text('↓', x + s * 0.25, y - s * 0.23, s * 0.25, '#e5c790');
}
function pathTo(target) {
  const u = unit(selected);
  if (!u) return [];
  const blocked = new Set(
    [
      ...state.walls,
      ...state.units.filter((v) => v.hp > 0 && v.id !== u.id).map((v) => [v.x, v.y]),
    ].map((p) => p.join(',')),
  );
  const paths = new Map([[`${u.x},${u.y}`, []]]),
    queue = [[u.x, u.y]];
  for (let i = 0; i < queue.length; i++) {
    const p = queue[i],
      path = paths.get(p.join(','));
    if (path.length >= u.move) continue;
    for (const [dx, dy] of [
      [1, 0],
      [0, 1],
      [-1, 0],
      [0, -1],
    ]) {
      const q = [p[0] + dx, p[1] + dy],
        key = q.join(',');
      if (q[0] < 0 || q[0] >= 16 || q[1] < 0 || q[1] >= 11 || blocked.has(key) || paths.has(key))
        continue;
      const next = [...path, q];
      paths.set(key, next);
      queue.push(q);
      if (q[0] === target.x && q[1] === target.y) return next;
    }
  }
  return [];
}
function drawEffects(now) {
  const s = viewW / 16;
  effects = effects.filter((e) => now - e.born < 1000);
  for (const e of effects) {
    const t = (now - e.born) / 1000;
    if (t < 0 || reducedMotion) continue;
    const p = e.end || [
      state.points.find((p) => p.id === e.point)?.x,
      state.points.find((p) => p.id === e.point)?.y,
    ];
    if (p[0] === undefined) continue;
    const x = (p[0] + 0.5) * s,
      y = (p[1] + 0.5) * s,
      c = e.kind === 'heal' ? '#a2e6c1' : e.kind === 'capture' ? '#e5d8a0' : '#f3b38d';
    ctx.globalAlpha = 1 - t;
    if (e.start && e.kind === 'attack' && t < 0.25) {
      line((e.start[0] + 0.5) * s, (e.start[1] + 0.5) * s, x, y, c, 2);
      circle(x, y, s * 0.2 * t * 4, null, c);
    } else circle(x, y, s * (0.15 + t * 0.65), null, c);
    if (e.amount)
      text(
        `${e.kind === 'heal' ? '+' : '−'}${e.amount}`,
        x,
        y - s * (0.45 + t * 0.5),
        Math.max(10, s * 0.26),
        c,
      );
    ctx.globalAlpha = 1;
  }
}
function drawBackground() {
  const key = `${state.scenario}:${canvas.width}:${canvas.height}`;
  if (backgroundKey !== key) {
    backgroundCanvas = document.createElement('canvas');
    backgroundCanvas.width = canvas.width;
    backgroundCanvas.height = canvas.height;
    const bg = backgroundCanvas.getContext('2d'),
      s = viewW / 16,
      dpr = canvas.width / viewW;
    bg.setTransform(dpr, 0, 0, dpr, 0, 0);
    const stroke = (x1, y1, x2, y2, color, width = 1) => {
      bg.strokeStyle = color;
      bg.lineWidth = width;
      bg.beginPath();
      bg.moveTo(x1, y1);
      bg.lineTo(x2, y2);
      bg.stroke();
    };
    for (let x = 0; x < 16; x++)
      for (let y = 0; y < 11; y++) {
        const n = (x * 71 + y * 37) % 9,
          road = x === 7 || x === 8 || y === 5;
        bg.fillStyle = road
          ? `rgb(${33 + n},${44 + n},${39 + n})`
          : `rgb(${35 + n},${48 + n},${40 + n})`;
        bg.fillRect(x * s, y * s, s, s);
        bg.strokeStyle = '#6a826011';
        bg.lineWidth = 0.7;
        bg.strokeRect(x * s, y * s, s, s);
        if (!road) {
          stroke(
            x * s + s * 0.13,
            y * s + s * 0.23,
            x * s + s * 0.25,
            y * s + s * 0.19,
            '#97a67f10',
          );
          stroke(
            x * s + s * 0.7,
            y * s + s * 0.76,
            x * s + s * 0.82,
            y * s + s * 0.78,
            '#182b2455',
          );
        }
      }
    if (ground.complete && ground.naturalWidth) {
      bg.save();
      bg.globalAlpha = .44;
      bg.drawImage(ground, 0, 0, viewW, viewH);
      bg.restore();
      bg.fillStyle = '#10201935';
      bg.fillRect(0, 0, viewW, viewH);
    }
    for (let x = 0; x <= 16; x++) stroke(x * s, 0, x * s, viewH, '#bed2c21c');
    for (let y = 0; y <= 11; y++) stroke(0, y * s, viewW, y * s, '#bed2c21c');
    bg.fillStyle = '#a2e6c107';
    bg.fillRect(0, s, 2 * s, 9 * s);
    bg.fillStyle = '#ef967e09';
    bg.fillRect(14 * s, s, 2 * s, 9 * s);
    for (let x = 2; x < 14; x++)
      stroke(x * s + s * 0.45, s * 5.5, x * s + s * 0.75, s * 5.5, '#b6b39220', 1.5);
    bg.font = `${s * 0.13}px Consolas, monospace`;
    bg.fillStyle = '#8ca27a66';
    bg.textBaseline = 'middle';
    bg.textAlign = 'left';
    for (let y = 0; y < 11; y++)
      bg.fillText(String(y + 1).padStart(2, '0'), s * 0.13, y * s + s * 0.14);
    bg.textAlign = 'center';
    for (let x = 0; x < 16; x++)
      bg.fillText(String(x + 1).padStart(2, '0'), x * s + s * 0.84, s * 0.14);
    backgroundKey = key;
  }
  ctx.drawImage(backgroundCanvas, 0, 0, viewW, viewH);
}
function draw(now) {
  frameRequest = null;
  if (document.hidden) return;
  if (state && viewW > 0) {
    const s = viewW / 16;
    ctx.clearRect(0, 0, viewW, viewH);
    drawBackground();
    for (const p of state.points) drawPoint(p, now);
    if (canAct()) {
      const legal = legalFor().filter((a) => a.type === actionMode),
        c =
          actionMode === 'move'
            ? colors.blue
            : actionMode === 'skill' && unit(selected)?.role === 'medic'
              ? colors.blue
              : '#efa37c';
      for (const a of legal) {
        if (a.x !== undefined) cellHighlight(a.x, a.y, c, actionMode === 'move' ? 0.08 : 0.08);
        else if (a.target) {
          const u = unit(a.target);
          if (u) cellHighlight(u.x, u.y, c, 0.15);
        }
      }
      const cursor = hover || keyboardCell,
        a = cursor && actionAt(cursor.x, cursor.y);
      if (a && actionMode === 'move') {
        const u = unit(selected),
          path = pathTo(cursor);
        ctx.save();
        ctx.setLineDash([3, 4]);
        ctx.beginPath();
        ctx.moveTo((u.x + 0.5) * s, (u.y + 0.5) * s);
        for (const p of path) ctx.lineTo((p[0] + 0.5) * s, (p[1] + 0.5) * s);
        ctx.strokeStyle = '#b2e8c0';
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.restore();
      }
      if (a && actionMode === 'skill' && unit(selected)?.role === 'assault')
        for (const [dx, dy] of [
          [0, 0],
          [1, 0],
          [0, 1],
          [-1, 0],
          [0, -1],
        ])
          if (cursor.x + dx >= 0 && cursor.x + dx < 16 && cursor.y + dy >= 0 && cursor.y + dy < 11)
            cellHighlight(cursor.x + dx, cursor.y + dy, '#f3b28e', 0.23);
      if (advice) {
        const p = advice.x !== undefined ? advice : unit(advice.target);
        if (p) cellHighlight(p.x, p.y, '#edf4d9', 0.25);
      }
    }
    for (const [x, y] of state.cover) drawCover(x, y);
    for (const [x, y] of state.walls) drawWall(x, y);
    for (const u of state.units) drawSoldier(u, now);
    if (hover) cellHighlight(hover.x, hover.y, '#d9e0ba', 0.06);
    if (document.activeElement === canvas && keyboardCell)
      cellHighlight(keyboardCell.x, keyboardCell.y, '#f3ebc6', 0.18);
    drawEffects(now);
  }
  if (!reducedMotion && (Object.keys(animation).length || effects.length))
    frameRequest = requestAnimationFrame(draw);
}
function requestPaint() {
  if (frameRequest === null && !document.hidden) frameRequest = requestAnimationFrame(draw);
}
requestPaint();
async function poll() {
  try {
    if (!pending) {
      const first = !state,
        ticket = responseGate.ticket();
      const query = state ? `?since=${state.state_revision}&session=${state.session_id}` : '';
      const next = await api('/api/state' + query);
      if (!responseGate.accepts(ticket) || pending) return;
      acceptState(next);
      if (first) {
        renderScenarios();
        openBriefing();
      }
    }
  } catch {
    /* The visible reconnect banner handles interrupted servers. */
  }
}
$('retry-btn').addEventListener('click', poll);
let polling = false;
async function pollLoop() {
  if (serverClosed) return;
  if (!polling && !document.hidden) {
    polling = true;
    try {
      await poll();
    } finally {
      polling = false;
    }
  }
  setTimeout(pollLoop, state?.phase === 'enemy' ? 700 : 1800);
}
setTimeout(pollLoop, 1800);
document.addEventListener('visibilitychange', () => {
  if (serverClosed) return;
  if (document.hidden && frameRequest !== null) {
    cancelAnimationFrame(frameRequest);
    frameRequest = null;
  }
  scheduleObserver();
  if (!document.hidden) {
    requestPaint();
    poll();
  }
});
async function init() {
  sound = storeGet('rift-sound') === 'true';
  $('sound-btn').classList.toggle('active', sound);
  $('tutorial').hidden = storeGet('rift-tutorial') === 'dismissed';
  $('sound-btn').title = sound ? 'Выключить звук' : 'Включить звук';
  $('sound-btn').setAttribute('aria-label', $('sound-btn').title);
  try {
    acceptState(await api('/api/state'), true);
    renderScenarios();
    openBriefing();
    resizeCanvas();
  } catch (e) {
    showToast(e.message, true);
  }
}
init();

$('quit-btn').addEventListener('click', () => $('quit-dialog').showModal());
$('closed-dialog').addEventListener('cancel', event => event.preventDefault());
$('confirm-quit-btn').addEventListener('click', async () => {
  if (pending || !state) return;
  pending = true;
  $('confirm-quit-btn').disabled = true;
  try {
    await api('/api/shutdown', { expected_session: state.session_id });
    serverClosed = true;
    observerScheduler.stop();
    $('quit-dialog').close();
    $('connection-error').hidden = true;
    $('closed-dialog').showModal();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    pending = false;
    $('confirm-quit-btn').disabled = false;
  }
});
