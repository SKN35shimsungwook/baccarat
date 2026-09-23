// 주사위 홀짝 (식보) 화면 (Streamlit Custom Component v2). common.js 뒤에 이어 붙는다.
// - 파이썬(dice/game.py)이 굴리고 정산한다. 결과는 베팅이 확정된 뒤에 서버에서 계산된다.
// - JS → 파이썬: setTriggerValue("roll", {bets})
// - 굴리기를 누르면 3D 주사위가 접시 안을 굴러다니고, 결과가 오면 그 눈이 위로 오도록 멈춘 뒤 결과·수익 표시
//   (진행은 setTimeout으로 하고 끝 상태를 먼저 적어 두므로 창이 가려져도 결과는 제대로 남는다)

const STATE = new WeakMap();
// 베팅판: [키, 이름, 설명, 모양, 단축키]
const ROWS = [
  ["main", [["odd", "홀", "합계 홀수 · 트리플 제외", "odd", "KeyS"], ["even", "짝", "합계 짝수 · 트리플 제외", "even", "KeyD"]]],
  ["side", [
    ["small", "소", "합계 4~10", "small", "KeyA"], ["double", "더블", "같은 눈 2개 이상", "double", "KeyQ"],
    ["triple", "트리플", "세 개 모두 같은 눈", "triple", "KeyW"], ["big", "대", "합계 11~17", "big", "KeyF"],
  ]],
];
const SPOT_KEYS = Object.fromEntries(ROWS.flatMap(([, spots]) => spots.map((sp) => [sp[4], sp[0]])));
// 주사위 눈 위치 (%, 3×3 격자)
const PIPS = {
  1: [[50, 50]], 2: [[27, 27], [73, 73]], 3: [[25, 25], [50, 50], [75, 75]],
  4: [[27, 27], [73, 27], [27, 73], [73, 73]], 5: [[26, 26], [74, 26], [50, 50], [26, 74], [74, 74]],
  6: [[27, 24], [73, 24], [27, 50], [73, 50], [27, 76], [73, 76]],
};
// 정육면체의 면 배치 (마주 보는 면의 합 = 7)와, 그 면이 위(화면 쪽)로 오게 하는 회전 [rotateX, rotateY]
const FACE_PLACE = {
  1: "translateZ(var(--h))", 6: "rotateY(180deg) translateZ(var(--h))",
  3: "rotateY(90deg) translateZ(var(--h))", 4: "rotateY(-90deg) translateZ(var(--h))",
  2: "rotateX(90deg) translateZ(var(--h))", 5: "rotateX(-90deg) translateZ(var(--h))",
};
const FACE_ROT = { 1: [0, 0], 6: [0, 180], 3: [0, -90], 4: [0, 90], 2: [-90, 0], 5: [90, 0] };
// 멈춘 자리 (접시 안 %, 기울기)
const DIE_POS = [[6, 10, -14], [54, 16, 11], [30, 54, -4]];
const SPIN_MS = 650;      // 굴러가는 한 구간
const MIN_ROLL_MS = 1100; // 결과가 빨리 와도 이만큼은 굴린다
const SETTLE_MS = 900;    // 멈추는 연출

const isTriple = (d) => d[0] === d[1] && d[1] === d[2];
const total = (d) => d[0] + d[1] + d[2];
const WIN = {
  odd: (d) => total(d) % 2 === 1 && !isTriple(d),
  even: (d) => total(d) % 2 === 0 && !isTriple(d),
  small: (d) => total(d) >= 4 && total(d) <= 10 && !isTriple(d),
  big: (d) => total(d) >= 11 && total(d) <= 17 && !isTriple(d),
  double: (d) => new Set(d).size < 3,
  triple: isTriple,
};
const rand = (a, b) => a + Math.random() * (b - a);

// 양방 베팅 금지 (dice/game.py 의 hedge_error 와 같은 규칙)
const OPPOSITE = [["odd", "even"], ["small", "big"]];
const SPOT_NAME = Object.fromEntries(ROWS.flatMap(([, spots]) => spots.map(([k, n]) => [k, n])));
const ALL_ROLLS = [];
for (let a = 1; a <= 6; a++) for (let b = 1; b <= 6; b++) for (let c = 1; c <= 6; c++) ALL_ROLLS.push([a, b, c]);
function hedgeError(keys) {
  const set = new Set(keys);
  for (const [a, b] of OPPOSITE) if (set.has(a) && set.has(b)) return `${SPOT_NAME[a]}·${SPOT_NAME[b]} 양방 베팅은 할 수 없습니다.`;
  if (set.size && ALL_ROLLS.every((d) => [...set].some((k) => WIN[k](d)))) return "어떤 결과가 나와도 맞는 조합(양방 베팅)은 걸 수 없습니다.";
  return null;
}

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector(".bt-root");
  if (!root || !data) return;

  let s = STATE.get(parentElement);
  if (!s || s.root !== root) {
    const prev = s;
    s = createState(root, data);
    if (prev) Object.assign(s, { bets: prev.bets, placed: prev.placed, lastBets: prev.lastBets, chip: prev.chip });
    // JS가 새로 불러와지면(개발 중 파일 수정 등) 이전 버전의 연출 타이머를 멈춘다
    const old = window.__diceState;
    if (old && old !== s) old.alive = false;
    window.__diceState = s;
    STATE.set(parentElement, s);
    buildBoard(s);
    buildDice(s);
    bind(s);
    bindKeys(s, (code) => onKey(s, code));
  }
  s.data = data;
  s.trigger = setTriggerValue;
  sync(s);
}

// ── 상태 ────────────────────────────────────────────────────────────
function createState(root, data) {
  const els = {};
  root.querySelectorAll("[data-el]").forEach((el) => (els[el.dataset.el] = el));
  const actions = {};
  root.querySelectorAll("[data-act]").forEach((el) => (actions[el.dataset.act] = el));
  const last = data.view.last;
  return {
    root, els, actions, alive: true,
    bets: {},              // 판 위에 놓은 칩 {key: amount}
    placed: [],            // 되돌리기용 [[key, amount]]
    lastBets: null,        // 지난 판 베팅 (재베팅용)
    chip: data.chips.includes(10000) ? 10000 : data.chips[0],
    sending: false,
    rolling: null,         // 연출 중인 결과 {res, my}
    shownNonce: last ? last.nonce : null,  // 첫 마운트 때는 지난 결과를 연출하지 않는다
    lastErrorId: data.error ? data.error.id : null,
    lastRecent: null,
    roadCount: 0,
  };
}

const betTotal = (bets) => Object.values(bets).reduce((a, b) => a + b, 0);

// ── 베팅판 ─────────────────────────────────────────────────────────
function dieFace(n, cls) {
  const el = document.createElement("div");
  el.className = `${cls} f${n}`;
  PIPS[n].forEach(([x, y]) => {
    const pip = document.createElement("i");
    if (n === 1 || n === 4) pip.className = "red"; // 1·4는 붉은 점 (동양 주사위)
    pip.style.left = `${x}%`;
    pip.style.top = `${y}%`;
    el.appendChild(pip);
  });
  return el;
}

function buildBoard(s) {
  const box = s.els.board;
  box.innerHTML = "";
  s.spots = {};
  ROWS.forEach(([rowCls, spots]) => {
    const row = document.createElement("div");
    row.className = `dc-row ${rowCls}`;
    spots.forEach(([key, name, rule, cls, keyCode]) => {
      const btn = document.createElement("button");
      btn.className = `dc-spot ${cls}`;
      btn.innerHTML = `<span class="name">${name}</span><span class="rule">${rule}</span>` +
        `<span class="odds"></span><kbd class="spot-key">${keyCode.slice(3)}</kbd>`;
      btn.title = `${name}: ${rule}`;
      btn.onclick = () => placeChip(s, key);
      row.appendChild(btn);
      s.spots[key] = btn;
    });
    box.appendChild(row);
  });
}

function bind(s) {
  const a = s.actions;
  a.undo.onclick = () => {
    const last = s.placed.pop();
    if (!last) return;
    s.bets[last[0]] -= last[1];
    if (s.bets[last[0]] <= 0) delete s.bets[last[0]];
    render(s);
  };
  a.clear.onclick = () => {
    s.bets = {};
    s.placed = [];
    render(s);
  };
  a.rebet.onclick = () => {
    if (!s.lastBets) return toast(s, "지난 베팅이 없습니다.");
    if (busy(s)) return;
    const add = s.lastBets;
    if (betTotal(s.bets) + betTotal(add) > s.data.balance) return toast(s, "칩이 부족합니다.");
    const hedge = hedgeError([...Object.keys(s.bets), ...Object.keys(add)]);
    if (hedge) return toast(s, hedge);
    Object.entries(add).forEach(([k, v]) => {
      s.bets[k] = (s.bets[k] || 0) + v;
      s.placed.push([k, v]);
    });
    render(s);
  };
  a.roll.onclick = () => roll(s);
}

const busy = (s) => s.sending || !!s.rolling;

function placeChip(s, key) {
  if (busy(s)) return;
  if (betTotal(s.bets) + s.chip > s.data.balance) return toast(s, "칩이 부족합니다.");
  const hedge = hedgeError([...Object.keys(s.bets), key]);
  if (hedge) return toast(s, hedge);
  if ((s.bets[key] || 0) + s.chip > s.data.rules.max) return toast(s, `한 칸에 최대 ${fmt(s.data.rules.max)}까지 걸 수 있습니다.`);
  s.bets[key] = (s.bets[key] || 0) + s.chip;
  s.placed.push([key, s.chip]);
  clearWins(s);
  render(s);
}

// 칩이 없으면 지난 베팅 그대로 굴린다
function roll(s) {
  if (busy(s)) return;
  let bets = s.bets;
  if (!betTotal(bets)) {
    if (!s.lastBets) return toast(s, "베팅판에 칩을 놓아 주세요.");
    if (betTotal(s.lastBets) > s.data.balance) return toast(s, "칩이 부족합니다.");
    bets = { ...s.lastBets };
  }
  s.sending = true;
  s.lastBets = { ...bets };
  s.pendingBets = { ...bets };
  s.trigger("roll", { bets: { ...bets }, nonce: Date.now() });
  s.bets = {};
  s.placed = [];
  clearWins(s);
  startRoll(s);
  render(s);
  // 응답이 오지 않으면(오류 등) 굴리기를 멈춘다
  clearTimeout(s.sendGuard);
  s.sendGuard = setTimeout(() => {
    if (s.sending) {
      s.sending = false;
      stopRoll(s);
      render(s);
    }
  }, 8000);
}

function onKey(s, code) {
  if (chipFromKey(s, code)) return true;
  if (SPOT_KEYS[code]) {
    placeChip(s, SPOT_KEYS[code]);
    return true;
  }
  const click = (btn) => (btn.click(), true);
  switch (code) {
    case "Space":
    case "Enter": roll(s); return true;
    case "KeyZ":
    case "Backspace": return click(s.actions.undo);
    case "KeyC": return click(s.actions.clear);
    case "KeyR": return click(s.actions.rebet);
  }
  return false;
}

// ── 파이썬 → 화면 ───────────────────────────────────────────────────
function sync(s) {
  const d = s.data;
  const v = d.view;
  buildChipTray(s);

  if (d.error && d.error.id !== s.lastErrorId) {
    s.lastErrorId = d.error.id;
    toast(s, d.error.msg);
    if (s.sending) {
      // 베팅이 거절됨: 칩을 판에 돌려놓는다
      s.sending = false;
      s.bets = s.pendingBets || {};
      s.placed = Object.entries(s.bets);
      stopRoll(s);
    }
  }
  if (v.last && v.last.nonce !== s.shownNonce) {
    s.shownNonce = v.last.nonce;
    s.sending = false;
    clearTimeout(s.sendGuard);
    const my = d.my_last && d.my_last.nonce === v.last.nonce ? d.my_last : null;
    finishRoll(s, v.last, my);
  } else if (!s.rolling && !s.sending) {
    placeDice(s, v.last ? v.last.dice : null);
    showResult(s, v.last, d.my_last && v.last && d.my_last.nonce === v.last.nonce ? d.my_last : null, false);
  }
  render(s);
  renderRecent(s, v);
  renderStats(s, v.stats);
  renderRoad(s, v.road);
  renderFair(s, v);
}

// ── 3D 주사위 ───────────────────────────────────────────────────────
// 주사위마다 {el(자리·평면 회전), cube(정육면체), x·y(정육면체 회전), z(평면 회전), left·top(%)}
function buildDice(s) {
  const box = s.els.dice;
  box.innerHTML = "";
  s.dice3 = DIE_POS.map(([left, top, z], i) => {
    const el = document.createElement("div");
    el.className = "dc-die3";
    const cube = document.createElement("div");
    cube.className = "dc-cube";
    [1, 2, 3, 4, 5, 6].forEach((n) => {
      const face = dieFace(n, "face");
      face.style.transform = FACE_PLACE[n];
      cube.appendChild(face);
    });
    el.appendChild(cube);
    box.appendChild(el);
    const d = { el, cube, x: 0, y: 0, z, left, top, i };
    applyDie(d);
    return d;
  });
}

function applyDie(d) {
  d.el.style.left = `${d.left}%`;
  d.el.style.top = `${d.top}%`;
  d.el.style.transform = `rotateZ(${d.z}deg)`;
  d.cube.style.transform = `rotateX(${d.x}deg) rotateY(${d.y}deg)`;
}

function cancelAnims(d) {
  d.el.getAnimations().forEach((a) => a.cancel());
  d.cube.getAnimations().forEach((a) => a.cancel());
}

// 주사위 하나를 to 로 옮긴다. 가운데에서 살짝 떠올랐다가(hop) 내려앉는다.
function moveDie(d, to, ms, easing, hop) {
  const mid = { left: (d.left + to.left) / 2 + rand(-12, 12), top: (d.top + to.top) / 2 + rand(-12, 12) };
  const frames = [
    { left: `${d.left}%`, top: `${d.top}%`, transform: `rotateZ(${d.z}deg) scale(1)` },
    { left: `${mid.left}%`, top: `${mid.top}%`, transform: `rotateZ(${(d.z + to.z) / 2}deg) scale(${hop})`, offset: 0.45 },
    { left: `${to.left}%`, top: `${to.top}%`, transform: `rotateZ(${to.z}deg) scale(1)` },
  ];
  const spin = [
    { transform: `rotateX(${d.x}deg) rotateY(${d.y}deg)` },
    { transform: `rotateX(${to.x}deg) rotateY(${to.y}deg)` },
  ];
  cancelAnims(d);
  Object.assign(d, to);
  applyDie(d); // 끝 상태를 먼저 적어 두면 애니메이션이 끝난 뒤(또는 창이 가려져 건너뛰어도) 그 자리에 남는다
  d.el.animate(frames, { duration: ms, easing });
  d.cube.animate(spin, { duration: ms, easing });
}

// 굴리기 시작: 결과가 올 때까지 접시 안을 굴러다닌다
function startRoll(s) {
  s.rollToken = (s.rollToken || 0) + 1;
  s.rollAt = Date.now();
  s.target = null;
  s.els.plate.classList.add("rolling");
  s.dice3.forEach((d) => d.el.classList.remove("win"));
  s.els.result.innerHTML = `<span class="wait">굴러가는 중…</span>`;
  spinStep(s, s.rollToken);
}

function spinStep(s, token) {
  if (!s.alive || token !== s.rollToken) return;
  if (s.target && Date.now() - s.rollAt >= MIN_ROLL_MS) return settle(s, token);
  s.dice3.forEach((d) => {
    moveDie(d, {
      x: d.x + rand(300, 520), y: d.y + rand(360, 620), z: d.z + rand(-160, 160),
      left: rand(0, 64), top: rand(0, 62),
    }, SPIN_MS, "linear", 1.22);
  });
  setTimeout(() => spinStep(s, token), SPIN_MS);
}

// 결과 눈이 위로 오도록 계속 같은 방향으로 돌다가 제자리에 멈춘다
function settle(s, token) {
  const { res, my } = s.target;
  const next = (cur, f, extra) => f + 360 * Math.ceil((cur + extra - f) / 360); // cur+extra 이상에서 f 와 같은 각
  s.dice3.forEach((d) => {
    const n = res.dice[d.i];
    const [fx, fy] = FACE_ROT[n];
    const [left, top, z] = DIE_POS[d.i];
    moveDie(d, { x: next(d.x, fx, 200), y: next(d.y, fy, 260), z: z + ((n * 7) % 9) - 4, left, top },
      SETTLE_MS, "cubic-bezier(.2,.75,.3,1)", 1.1);
  });
  setTimeout(() => {
    if (!s.alive || token !== s.rollToken) return;
    s.els.plate.classList.remove("rolling");
    s.rolling = null;
    showResult(s, res, my, true);
    render(s);
  }, SETTLE_MS + 60);
}

// 새 결과가 왔다: 굴리는 중이면 멈출 목표로 넘기고, 아니면(다른 곳에서 굴린 결과 등) 굴리기부터
function finishRoll(s, res, my) {
  s.rolling = { res, my };
  if (!s.els.plate.classList.contains("rolling")) startRoll(s);
  s.target = { res, my };
  render(s);
}

function stopRoll(s) {
  s.rollToken = (s.rollToken || 0) + 1;
  s.els.plate.classList.remove("rolling");
  const last = s.data.view.last;
  placeDice(s, last ? last.dice : null);
  showResult(s, last, null, false);
}

// 연출 없이 결과 눈으로 놓는다 (결과가 없으면 1·2·3)
function placeDice(s, dice) {
  s.dice3.forEach((d) => {
    const n = dice ? dice[d.i] : d.i + 1;
    const [left, top, z] = DIE_POS[d.i];
    cancelAnims(d);
    [d.x, d.y] = FACE_ROT[n];
    Object.assign(d, { left, top, z: z + ((n * 7) % 9) - 4 });
    applyDie(d);
  });
}

function clearWins(s) {
  Object.values(s.spots).forEach((b) => b.classList.remove("won"));
}

function showResult(s, res, my, fresh) {
  if (!res) {
    s.els.result.innerHTML = `<span class="sub">베팅판에 칩을 놓고</span><span class="wait">굴리기</span>`;
    return;
  }
  const tags = res.triple
    ? `<b class="triple">트리플</b>`
    : `<b class="${res.parity}">${res.parity === "odd" ? "홀" : "짝"}</b><b class="size">${res.size === "small" ? "소" : "대"}</b>`;
  s.els.result.innerHTML =
    `<span class="sub">#${res.nonce}판 · ${res.dice.join(" · ")}</span>` +
    `<span class="sum">${res.sum}</span>` +
    `<span class="tags">${tags}</span>` +
    (my
      ? `<span class="net ${my.net > 0 ? "plus" : my.net < 0 ? "minus" : ""}">${my.net > 0 ? "+" : ""}${fmt(my.net)}</span>` +
        `<span class="sub">베팅 ${fmt(my.stake)} · 받음 ${fmt(my.returned)}</span>`
      : "");
  if (fresh) {
    Object.entries(s.spots).forEach(([key, btn]) => btn.classList.toggle("won", WIN[key](res.dice)));
    s.dice3.forEach((d) => d.el.classList.toggle("win", !!my && my.net > 0));
  }
}

function render(s) {
  const v = s.data.view;
  const isBusy = busy(s);
  Object.entries(s.spots).forEach(([key, btn]) => {
    btn.querySelector(".odds").textContent = `${v.payouts[key].toFixed(2)}배`;
    btn.querySelector(".stack")?.remove();
    const shown = s.bets[key] || (isBusy && s.pendingBets ? s.pendingBets[key] : 0);
    if (shown) {
      const chip = makeChip(shown, short(shown), true);
      chip.classList.add("stack");
      btn.appendChild(chip);
    }
    btn.disabled = isBusy;
  });
  const pending = betTotal(s.bets);
  const label = s.actions.roll.querySelector("span");
  s.actions.roll.disabled = isBusy || (!pending && !s.lastBets);
  label.textContent = isBusy ? "굴리는 중…" : pending ? `굴리기 ${fmt(pending)}` : s.lastBets ? `같은 베팅 굴리기 ${fmt(betTotal(s.lastBets))}` : "굴리기";
  s.actions.undo.disabled = isBusy || !s.placed.length;
  s.actions.clear.disabled = isBusy || !pending;
  s.actions.rebet.disabled = isBusy || !s.lastBets;
  // 연출이 끝나기 전에는 당첨금을 빼고(베팅액만 빠진) 잔액을 보여 준다
  const rolling = s.rolling && s.rolling.my ? s.rolling.my : null;
  const balance = s.data.balance - (rolling ? rolling.returned : 0);
  const staked = s.sending && s.pendingBets ? betTotal(s.pendingBets) : 0;
  s.els.totalbet.textContent = fmt(isBusy ? (rolling ? rolling.stake : staked) : pending);
  s.els.balance.textContent = fmt(balance - pending - staked);
  const profit = balance - s.data.start_chips;
  s.els.profit.textContent = profit > 0 ? `+${fmt(profit)}` : fmt(profit);
  s.els.profit.className = profit > 0 ? "up" : profit < 0 ? "down" : "";
  updateChipTray(s);
}

// ── 기록 표시 ───────────────────────────────────────────────────────
function renderRecent(s, v) {
  const key = v.recent.map((r) => r.nonce).join(",");
  if (key === s.lastRecent) return;
  const fresh = s.lastRecent !== null;
  s.lastRecent = key;
  s.els.recent.innerHTML = v.recent
    .map((r, i) => `<span class="${r.parity}${i === 0 && fresh ? " fresh" : ""}" title="#${r.nonce} ${r.dice.join("·")}">${r.sum}</span>`)
    .join("");
}

function renderStats(s, st) {
  if (!st.n) {
    s.els.stats.innerHTML = `<div class="t">아직 굴린 기록이 없습니다</div>`;
    return;
  }
  const bar = (a, b, ca, cb) => {
    const n = a + b || 1;
    return `<div class="bar"><i style="width:${(a / n) * 100}%;background:${ca}"></i><i style="flex:1;background:${cb}"></i></div>`;
  };
  const max = Math.max(...st.faces, 1);
  s.els.stats.innerHTML =
    `<div class="t">최근 ${st.n}판 · 트리플 ${st.triple}회</div>` +
    `<div class="row"><span>홀</span>${bar(st.odd, st.even, "var(--odd)", "var(--even)")}<span>짝</span></div>` +
    `<div class="t">${st.odd} : ${st.even}</div>` +
    `<div class="row"><span>소</span>${bar(st.small, st.big, "#b98a3a", "#6b4a1c")}<span>대</span></div>` +
    `<div class="t">${st.small} : ${st.big}</div>` +
    `<div class="faces">${st.faces.map((c, i) => `<div title="${i + 1}: ${c}회"><i style="height:${(c / max) * 100}%"></i><b>${i + 1}</b></div>`).join("")}</div>`;
}

// 6칸씩 위에서 아래로 채우는 기록판 (칸 안에 합계)
function renderRoad(s, road) {
  const box = s.els.road;
  const sums = s.data.view.road_sums;
  box.innerHTML = road.map((p, i) => `<i class="${p}">${sums[i] ?? ""}</i>`).join("");
  if (road.length !== s.roadCount && s.roadCount && box.lastElementChild) box.lastElementChild.classList.add("fresh");
  s.roadCount = road.length;
  box.scrollLeft = box.scrollWidth;
}

function renderFair(s, v) {
  const last = v.last;
  s.els.fair.textContent = `다음 판 해시 ${v.commit.slice(0, 16)}…` +
    (last ? `  ·  #${last.nonce}판 시드 ${last.server_seed.slice(0, 12)}… 공개` : "");
}

// ── 칩 트레이 ───────────────────────────────────────────────────────
function buildChipTray(s) {
  const tray = s.els.chiptray;
  if (!tray.childElementCount) {
    s.data.chips.forEach((v) => {
      const chip = makeChip(v, short(v));
      chip.dataset.v = v;
      chip.dataset.key = tray.childElementCount + 1;
      chip.onclick = () => {
        s.chip = v;
        updateChipTray(s);
      };
      tray.appendChild(chip);
    });
  }
  updateChipTray(s);
}

function updateChipTray(s) {
  const free = s.data.balance - betTotal(s.bets);
  s.els.chiptray.querySelectorAll(".bt-chip").forEach((c) => {
    const v = Number(c.dataset.v);
    c.classList.toggle("sel", v === s.chip);
    c.classList.toggle("off", v > free);
  });
}
