// 사다리 게임 화면 (Streamlit Custom Component v2). common.js 뒤에 이어 붙는다.
// - 파이썬(ladder/game.py)이 추첨·정산을 한다. 결과는 베팅이 확정된 뒤에 서버에서 계산된다.
// - JS → 파이썬: setTriggerValue("play", {bets}) — 칩을 놓고 추첨하기를 누르면 바로 추첨
// - 새 결과가 오면 사다리 연출 → 결과·내 정산 표시. 연출이 끝나기 전에는 결과가 반영된 숫자를 보여 주지 않는다.

const STATE = new WeakMap();
// 배치(ladder.css): 가운데 홀·짝 크게, 그 아래 좌·우·3줄·4줄, 왼쪽에 좌 조합, 오른쪽에 우 조합
const SPOTS = [
  ["L3E", "좌3짝", "combo"], ["L4O", "좌4홀", "combo"],
  ["odd", "홀", "odd"], ["even", "짝", "even"],
  ["left", "좌", "left"], ["right", "우", "right"], ["three", "3줄", "three"], ["four", "4줄", "four"],
  ["R3O", "우3홀", "combo"], ["R4E", "우4짝", "combo"],
];
const WIN_RULE = {
  left: (r) => r.side === "L", right: (r) => r.side === "R",
  three: (r) => r.lines === 3, four: (r) => r.lines === 4,
  odd: (r) => r.finish === "odd", even: (r) => r.finish === "even",
  L3E: (r) => r.code === "L3E", L4O: (r) => r.code === "L4O", R3O: (r) => r.code === "R3O", R4E: (r) => r.code === "R4E",
};
// 양방 베팅 금지 (ladder/game.py 의 hedge_error 와 같은 규칙)
const OPPOSITE = [["left", "right"], ["three", "four"], ["odd", "even"]];
const OUTCOMES = [["L", 3, "even", "L3E"], ["L", 4, "odd", "L4O"], ["R", 3, "odd", "R3O"], ["R", 4, "even", "R4E"]]
  .map(([side, lines, finish, code]) => ({ side, lines, finish, code }));
const SPOT_NAME = Object.fromEntries(SPOTS.map(([k, n]) => [k, n]));
function hedgeError(keys) {
  const set = new Set(keys);
  for (const [a, b] of OPPOSITE) if (set.has(a) && set.has(b)) return `${SPOT_NAME[a]}·${SPOT_NAME[b]} 양방 베팅은 할 수 없습니다.`;
  if (set.size && OUTCOMES.every((o) => [...set].some((k) => WIN_RULE[k](o)))) return "어떤 결과가 나와도 맞는 조합(양방 베팅)은 걸 수 없습니다.";
  return null;
}
const COLORS = { left: "#3b82f6", right: "#f97316", odd: "#2563eb", even: "#e11d48" };
const RESULT_FALLBACK_MS = 5000; // 창이 가려져 그리기가 멈춰도 이 시간이 지나면 결과를 보여 준다

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector(".bt-root");
  if (!root || !data) return;

  let s = STATE.get(parentElement);
  if (!s || s.root !== root) {
    const prev = s;
    s = createState(root, data);
    if (prev) {
      prev.alive = false;
      Object.assign(s, { bets: prev.bets, placed: prev.placed, lastBets: prev.lastBets, chip: prev.chip });
    }
    // JS가 새로 불러와지면(개발 중 파일 수정 등) 이전 버전의 그리기 루프를 확실히 멈춘다
    const old = window.__ladderState;
    if (old && old !== s) {
      old.alive = false;
      clearInterval(old.clock);
    }
    window.__ladderState = s;
    STATE.set(parentElement, s);
    buildSpots(s);
    bind(s);
    bindKeys(s, (code) => onKey(s, code));
    requestAnimationFrame((t) => frame(s, t));
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
  return {
    root, els, actions, alive: true,
    bets: {},              // 판 위에 놓은 칩 {key: amount}
    placed: [],            // 되돌리기용 [[key, amount]]
    lastBets: null,        // 지난 베팅 (재베팅용)
    pendingBets: null,     // 추첨을 요청한 베팅 (응답 전까지 판에 보여 줌)
    chip: data.chips.includes(10000) ? 10000 : data.chips[0],
    sending: false,
    shownRound: data.view.last ? data.view.last.round : null,  // 첫 마운트 때는 지난 결과를 연출하지 않는다
    anim: null,            // 추첨 연출 {res, my, t0, shown}
    lastErrorId: data.error ? data.error.id : null,
    lastRecent: null,
    confetti: [],
    roadCount: 0,
  };
}

const betTotal = (bets) => Object.values(bets).reduce((a, b) => a + b, 0);
const animating = (s) => !!(s.anim && !s.anim.shown);
const busy = (s) => s.sending || animating(s);
const winAmount = (s, key, amount) => Math.floor(amount * s.data.view.payouts[key]);
// 이 베팅으로 받을 수 있는 가장 큰 금액 (4가지 결과 중)
const maxWin = (s, bets) =>
  Math.max(0, ...OUTCOMES.map((o) => Object.entries(bets).reduce((t, [k, v]) => t + (WIN_RULE[k](o) ? winAmount(s, k, v) : 0), 0)));

// ── 베팅 칸 ─────────────────────────────────────────────────────────
function buildSpots(s) {
  const box = s.els.bets;
  box.innerHTML = "";
  s.spots = {};
  SPOTS.forEach(([key, name, cls]) => {
    const btn = document.createElement("button");
    btn.className = `ld-spot ${cls} k-${key}`;
    btn.innerHTML = `<span class="name">${name}</span><span class="odds"></span><span class="mine"></span>`;
    btn.onclick = () => placeChip(s, key);
    box.appendChild(btn);
    s.spots[key] = btn;
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
    clearWins(s);
    render(s);
  };
  a.confirm.onclick = () => play(s);
}

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

// 칩이 없으면 지난 베팅 그대로 추첨한다
function play(s) {
  if (busy(s)) return;
  let bets = s.bets;
  if (!betTotal(bets)) {
    if (!s.lastBets) return toast(s, "베팅 칸에 칩을 놓아 주세요.");
    if (betTotal(s.lastBets) > s.data.balance) return toast(s, "칩이 부족합니다.");
    bets = { ...s.lastBets };
  }
  s.sending = true;
  s.lastBets = { ...bets };
  s.pendingBets = { ...bets };
  s.trigger("play", { bets: { ...bets }, nonce: Date.now() });
  s.bets = {};
  s.placed = [];
  clearWins(s);
  s.els.result.innerHTML = `<span class="sub">#${s.data.view.round}회차</span><span class="big wait">추첨 중…</span>`;
  render(s);
  clearTimeout(s.sendGuard);
  s.sendGuard = setTimeout(() => {
    if (s.sending) {
      s.sending = false;
      render(s);
    }
  }, 8000);
}

function onKey(s, code) {
  if (chipFromKey(s, code)) return true;
  const click = (btn) => (btn.click(), true);
  switch (code) {
    case "Space":
    case "Enter": play(s); return true;
    case "KeyZ":
    case "Backspace": return click(s.actions.undo);
    case "KeyC": return click(s.actions.clear);
    case "KeyR": return click(s.actions.rebet);
  }
  return false;
}

function clearWins(s) {
  Object.values(s.spots).forEach((b) => b.classList.remove("won"));
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
      showResult(s);
    }
  }
  // 새 추첨 결과가 왔으면 연출
  if (v.last && v.last.round !== s.shownRound) {
    s.shownRound = v.last.round;
    s.sending = false;
    clearTimeout(s.sendGuard);
    const my = d.my_last && d.my_last.round === v.last.round ? d.my_last : null;
    const anim = { res: v.last, my, t0: performance.now(), won: false, shown: false };
    s.anim = anim;
    s.els.result.innerHTML = `<span class="sub">#${v.last.round}회차</span><span class="big wait">추첨 중…</span>`;
    setTimeout(() => {
      if (s.anim === anim && !anim.shown) {
        anim.shown = true;
        showResult(s);
      }
    }, RESULT_FALLBACK_MS);
  } else if (!s.anim) {
    const last = v.last;
    s.anim = last ? { res: last, my: d.my_last && d.my_last.round === last.round ? d.my_last : null,
                      t0: -1e9, won: true, shown: true } : null;
    showResult(s);
  }
  render(s);
  if (!animating(s)) renderAfterResult(s);
  renderFair(s, v);
}

// 결과가 공개된 뒤에 바뀌어야 하는 것들 (연출 중에 미리 보이면 결과를 알게 되므로)
function renderAfterResult(s) {
  const v = s.data.view;
  renderRecent(s, v);
  renderStats(s, v.stats);
  renderRoad(s, v.finishes);
  renderMine(s, s.data.my);
}

function render(s) {
  const v = s.data.view;
  const isBusy = busy(s);
  const shownBets = s.sending && s.pendingBets ? s.pendingBets : animating(s) ? s.pendingBets || {} : s.bets;
  Object.entries(s.spots).forEach(([key, btn]) => {
    btn.querySelector(".odds").textContent = `${v.payouts[key].toFixed(2)}배`;
    const amount = shownBets[key] || 0;
    btn.querySelector(".mine").textContent = amount ? `맞으면 ${fmt(winAmount(s, key, amount))}` : "";
    btn.querySelector(".stack")?.remove();
    if (amount) {
      const chip = makeChip(amount, short(amount), true);
      chip.classList.add("stack");
      btn.appendChild(chip);
    }
    btn.disabled = isBusy;
  });
  const pending = betTotal(s.bets);
  const label = s.actions.confirm.querySelector("span");
  s.actions.confirm.disabled = isBusy || (!pending && !s.lastBets);
  label.textContent = isBusy ? "추첨 중…" : pending ? `추첨하기 ${fmt(pending)}` : s.lastBets ? `같은 베팅 추첨 ${fmt(betTotal(s.lastBets))}` : "추첨하기";
  s.actions.undo.disabled = isBusy || !s.placed.length;
  s.actions.clear.disabled = isBusy || !pending;
  s.actions.rebet.disabled = isBusy || !s.lastBets;

  // 이번 베팅 요약: 합계 · 가장 크게 받을 수 있는 금액
  const shownTotal = betTotal(shownBets);
  s.els.betinfo.innerHTML = shownTotal
    ? `<span>이번 베팅 <b>${fmt(shownTotal)}</b></span><span>최대 당첨 <b class="plus">${fmt(maxWin(s, shownBets))}</b></span>`
    : `<span class="hint">칸을 눌러 칩을 놓고 <b>추첨하기</b>(Space)</span>`;

  // 연출이 끝나기 전에는 당첨금을 빼고(베팅액만 빠진) 잔액을 보여 준다
  const hidden = animating(s) && s.anim.my ? s.anim.my : null;
  const balance = s.data.balance - (hidden ? hidden.returned : 0);
  const staked = s.sending && s.pendingBets ? betTotal(s.pendingBets) : 0;
  s.els.totalbet.textContent = fmt(shownTotal);
  s.els.balance.textContent = fmt(balance - pending - staked);
  const profit = balance - s.data.start_chips;
  s.els.profit.textContent = profit > 0 ? `+${fmt(profit)}` : fmt(profit);
  s.els.profit.className = profit > 0 ? "up" : profit < 0 ? "down" : "";
  updateChipTray(s);
}

// ── 결과 / 기록 표시 ────────────────────────────────────────────────
function showResult(s) {
  const a = s.anim;
  if (!a) {
    s.els.result.innerHTML = `<span class="sub">#${s.data.view.round}회차</span><span class="big wait">베팅하고 추첨</span>`;
    return;
  }
  const r = a.res;
  const my = a.my;
  const sideName = r.side === "L" ? "좌" : "우";
  const finName = r.finish === "odd" ? "홀" : "짝";
  s.els.result.innerHTML =
    `<span class="sub">#${r.round}회차 결과</span>` +
    `<span class="big" style="color:${COLORS[r.finish]}">${r.text}</span>` +
    `<span class="sub">${sideName} 출발 · ${r.lines}줄 · ${finName}</span>` +
    (my
      ? `<span class="settle"><span>베팅 ${fmt(my.stake)} → 받음 ${fmt(my.returned)}</span>` +
        `<b class="net ${my.net > 0 ? "plus" : my.net < 0 ? "minus" : ""}">${my.net > 0 ? "+" : ""}${fmt(my.net)}</b></span>`
      : "");
  Object.entries(s.spots).forEach(([key, btn]) => btn.classList.toggle("won", WIN_RULE[key](r)));
  if (my && my.net > 0 && !a.won) {
    a.won = true;
    burstConfetti(s);
  }
  s.pendingBets = null;
  render(s);
  renderAfterResult(s);
}

// 사다리 누적 손익 + 내 회차 기록
function renderMine(s, my) {
  if (!my) return;
  const cls = (n) => (n > 0 ? "plus" : n < 0 ? "minus" : "");
  s.els.mystats.innerHTML =
    `<span class="t">사다리 누적 손익</span>` +
    `<b class="total ${cls(my.net)}">${signed(my.net)}</b>` +
    `<span class="row"><span>회차</span><b>${my.rounds}</b></span>` +
    `<span class="row"><span>이긴 회차</span><b>${my.wins}${my.rounds ? ` (${Math.round((my.wins / my.rounds) * 100)}%)` : ""}</b></span>` +
    `<span class="row"><span>총 베팅</span><b>${fmt(my.stake)}</b></span>` +
    `<span class="row"><span>총 받음</span><b>${fmt(my.returned)}</b></span>`;
  s.els.mylist.innerHTML = my.list.length
    ? `<table><thead><tr><th>회차</th><th>결과</th><th>베팅</th><th>베팅액</th><th>받음</th><th>손익</th></tr></thead><tbody>` +
      my.list.map((h) =>
        `<tr><td>#${h.round}</td><td><b class="code ${h.code.endsWith("O") ? "odd" : "even"}">${h.result}</b></td>` +
        `<td class="bets">${h.bets}</td><td>${fmt(h.stake)}</td><td>${fmt(h.returned)}</td>` +
        `<td class="${cls(h.net)}">${signed(h.net)}</td></tr>`).join("") +
      `</tbody></table>`
    : `<p class="empty">아직 건 회차가 없습니다.</p>`;
}

function renderRecent(s, v) {
  const key = v.recent.map((r) => r.round).join(",");
  if (key === s.lastRecent) return;
  const fresh = s.lastRecent !== null;
  s.lastRecent = key;
  s.els.recent.innerHTML = v.recent
    .map((r, i) => `<span class="${r.finish}${i === 0 && fresh ? " fresh" : ""}" title="#${r.round}">${r.text}</span>`)
    .join("");
}

function renderStats(s, st) {
  const bar = (p, a, b) => `<div class="bar"><i style="width:${p * 100}%;background:${a}"></i><i style="flex:1;background:${b}"></i></div>`;
  const pct = (p) => `${Math.round(p * 100)}`;
  s.els.stats.innerHTML = st.n
    ? `<div class="t">최근 ${st.n}회차</div>` +
      `<div class="row"><span>좌</span>${bar(st.left, COLORS.left, COLORS.right)}<span>우</span></div>` +
      `<div class="row"><span>3</span>${bar(st.three, "#8b5cf6", "#c4b5fd")}<span>4</span></div>` +
      `<div class="row"><span>홀</span>${bar(st.odd, COLORS.odd, COLORS.even)}<span>짝</span></div>` +
      `<div class="t">좌 ${pct(st.left)}% · 3줄 ${pct(st.three)}% · 홀 ${pct(st.odd)}%</div>`
    : `<div class="t">아직 추첨 기록이 없습니다</div>`;
}

// 홀·짝 흐름표: 같은 결과가 이어지면 한 열로, 6칸이 넘으면 오른쪽으로 꺾는다 (바카라 원매와 같은 방식)
function renderRoad(s, finishes) {
  const cols = [];
  finishes.forEach((f) => {
    if (cols.length && cols[cols.length - 1][0] === f) cols[cols.length - 1].push(f);
    else cols.push([f]);
  });
  const occupied = new Set();
  const cells = [];
  let start = -1;
  cols.forEach((col) => {
    start += 1;
    while (occupied.has(`${start},0`)) start += 1;
    let x = start, y = 0, turned = false;
    col.forEach((f, i) => {
      if (i > 0) {
        if (!turned && y + 1 < 6 && !occupied.has(`${x},${y + 1}`)) y += 1;
        else {
          turned = true;
          x += 1;
          while (occupied.has(`${x},${y}`)) x += 1;
        }
      }
      occupied.add(`${x},${y}`);
      cells.push(`<i class="${f}" style="grid-column:${x + 1};grid-row:${y + 1}"></i>`);
    });
  });
  const box = s.els.road;
  const grew = finishes.length !== s.roadCount;
  box.innerHTML = cells.join("");
  if (grew && s.roadCount && box.lastElementChild) box.lastElementChild.classList.add("fresh");
  s.roadCount = finishes.length;
  box.scrollLeft = box.scrollWidth;
}

function renderFair(s, v) {
  const last = v.last;
  s.els.fair.textContent = `#${v.round}회차 해시 ${v.commit.slice(0, 16)}…` +
    (last && !animating(s) ? `  ·  지난 #${last.round}회차 시드 ${last.seed.slice(0, 12)}… 공개` : "");
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

// ── canvas: 사다리 그리기 ───────────────────────────────────────────
// 연출 시간표 (초): 가림막 걷힘 0~0.6 → 가로줄 하나씩 0.6~ → 공 이동 → 도착
const T_COVER = 0.4, T_RUNG = 0.18, TRAVEL = 1.6; // TRAVEL: 공이 끝까지 가는 시간(초, 화면 크기와 무관). 전체 연출 약 3초

function frame(s, now) {
  if (!s.alive || !s.root.isConnected) return;
  requestAnimationFrame((t) => frame(s, t));
  const cv = s.els.canvas;
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight;
  if (!W || !H) return;
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) {
    cv.width = Math.round(W * dpr);
    cv.height = Math.round(H * dpr);
  }
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);

  const L = W * 0.3, R = W * 0.7, top = H * 0.16, bot = H * 0.84;
  const a = s.anim;
  const res = a ? a.res : null;
  const t = a ? (now - a.t0) / 1000 : 0;
  const drawing = a && t >= 0 && t < 30;

  // 기둥
  ctx.lineCap = "round";
  ctx.strokeStyle = "#7c5a2a";
  ctx.lineWidth = 8;
  [L, R].forEach((x) => {
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, bot);
    ctx.stroke();
  });

  let pathDone = false;
  if (res) {
    const y = (h) => top + (bot - top) * h;
    const rungsShown = drawing ? Math.max(0, Math.min(res.lines, Math.floor((t - T_COVER) / T_RUNG) + 1)) : res.lines;
    ctx.strokeStyle = "#a47a3d";
    ctx.lineWidth = 7;
    res.heights.slice(0, rungsShown).forEach((h) => {
      ctx.beginPath();
      ctx.moveTo(L, y(h));
      ctx.lineTo(R, y(h));
      ctx.stroke();
    });

    // 공의 길: 출발 → (가로줄마다 건너감) → 도착
    const pts = [[res.side === "L" ? L : R, top]];
    let x = pts[0][0];
    res.heights.forEach((h) => {
      pts.push([x, y(h)]);
      x = x === L ? R : L;
      pts.push([x, y(h)]);
    });
    pts.push([x, bot]);
    const lens = pts.slice(1).map((p, i) => Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1]));
    const total = lens.reduce((q, w) => q + w, 0);
    const startMove = T_COVER + res.lines * T_RUNG + 0.2;
    const moved = drawing ? Math.max(0, ((t - startMove) / TRAVEL) * total) : total;
    pathDone = moved >= total;
    // 지나간 길 칠하기
    let left = Math.min(moved, total);
    ctx.strokeStyle = COLORS[res.side === "L" ? "left" : "right"];
    ctx.lineWidth = 6;
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    let ball = pts[0];
    for (let i = 1; i < pts.length && left > 0; i++) {
      const seg = lens[i - 1];
      const f = Math.min(1, left / seg);
      ball = [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * f, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * f];
      ctx.lineTo(ball[0], ball[1]);
      left -= seg;
    }
    ctx.stroke();
    if (moved > 0) drawBall(ctx, ball[0], ball[1], Math.min(W, H) * 0.035);

    if (drawing && t < T_COVER) drawCover(ctx, L, R, top, bot, 1 - t / T_COVER);
    if (pathDone && drawing && !a.shown) {
      a.shown = true;
      showResult(s);
    }
  } else {
    drawCover(ctx, L, R, top, bot, 1);
  }

  // 위: 출발점, 아래: 도착칸
  const r = Math.min(W, H) * 0.075;
  label(ctx, L, top - r * 0.6, r, "좌", COLORS.left, res && res.side === "L" && pathDone);
  label(ctx, R, top - r * 0.6, r, "우", COLORS.right, res && res.side === "R" && pathDone);
  label(ctx, L, bot + r * 0.6, r, "홀", COLORS.odd, res && res.finish === "odd" && pathDone);
  label(ctx, R, bot + r * 0.6, r, "짝", COLORS.even, res && res.finish === "even" && pathDone);

  drawConfetti(s, ctx, W, H, now);
}

function drawCover(ctx, L, R, top, bot, alpha) {
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.fillStyle = "#fde68a";
  ctx.strokeStyle = "#f59e0b";
  ctx.lineWidth = 3;
  const x = L - 26, w = R - L + 52, yy = top + 20, h = bot - top - 40;
  ctx.beginPath();
  ctx.roundRect(x, yy, w, h, 18);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#b45309";
  ctx.font = `900 ${Math.round(h * 0.28)}px system-ui, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("?", (L + R) / 2, top + (bot - top) / 2);
  ctx.restore();
}

function label(ctx, x, y, r, text, color, hit) {
  ctx.save();
  ctx.fillStyle = color;
  ctx.shadowColor = hit ? color : "transparent";
  ctx.shadowBlur = hit ? 24 : 0;
  ctx.beginPath();
  ctx.arc(x, y, hit ? r * 1.15 : r, 0, Math.PI * 2);
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.strokeStyle = "#fff";
  ctx.lineWidth = 3;
  ctx.stroke();
  ctx.fillStyle = "#fff";
  ctx.font = `900 ${Math.round(r * 0.9)}px system-ui, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, x, y + 1);
  ctx.restore();
}

function drawBall(ctx, x, y, r) {
  ctx.save();
  ctx.fillStyle = "#facc15";
  ctx.strokeStyle = "#b45309";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "rgba(255,255,255,.8)";
  ctx.beginPath();
  ctx.arc(x - r * 0.35, y - r * 0.35, r * 0.3, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function burstConfetti(s) {
  const colors = ["#ef4444", "#f59e0b", "#22c55e", "#3b82f6", "#a855f7", "#ec4899"];
  const now = performance.now();
  for (let i = 0; i < 90; i++) {
    s.confetti.push({
      x: 0.5, y: 0.45, vx: (Math.random() - 0.5) * 0.9, vy: -Math.random() * 0.9 - 0.2,
      c: colors[i % colors.length], t0: now, rot: Math.random() * 6,
    });
  }
}

function drawConfetti(s, ctx, W, H, now) {
  s.confetti = s.confetti.filter((p) => now - p.t0 < 2200);
  s.confetti.forEach((p) => {
    const t = (now - p.t0) / 1000;
    const x = (p.x + p.vx * t) * W;
    const y = (p.y + p.vy * t + 0.7 * t * t) * H;
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(p.rot + t * 6);
    ctx.fillStyle = p.c;
    ctx.fillRect(-4, -2, 8, 4);
    ctx.restore();
  });
}
