// 사다리 게임 화면 (Streamlit Custom Component v2). common.js 뒤에 이어 붙는다.
// - 파이썬(ladder/game.py)이 회차 시간표·추첨·정산을 한다. 결과는 추첨 시각이 지난 뒤에만 계산된다.
// - JS → 파이썬: setTriggerValue("bet" | "tick")
//   bet: 이번 회차에 칩 확정 / tick: 추첨 시각이 되면 결과를 받아 온다
// - 시계는 서버 시각(data.view.now)에 맞춰 보정한다.

const STATE = new WeakMap();
const SPOTS = [
  ["left", "좌", "left"], ["right", "우", "right"], ["three", "3줄", "three"], ["four", "4줄", "four"],
  ["odd", "홀", "odd"], ["even", "짝", "even"], null,
  ["L3E", "좌3짝", "combo"], ["L4O", "좌4홀", "combo"], ["R3O", "우3홀", "combo"], ["R4E", "우4짝", "combo"],
];
const WIN_RULE = {
  left: (r) => r.side === "L", right: (r) => r.side === "R",
  three: (r) => r.lines === 3, four: (r) => r.lines === 4,
  odd: (r) => r.finish === "odd", even: (r) => r.finish === "even",
  L3E: (r) => r.code === "L3E", L4O: (r) => r.code === "L4O", R3O: (r) => r.code === "R3O", R4E: (r) => r.code === "R4E",
};
const COLORS = { left: "#3b82f6", right: "#f97316", odd: "#2563eb", even: "#e11d48" };
const RING = 276.46; // 2πr (r = 44)

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
      clearInterval(prev.clock);
      Object.assign(s, { bets: prev.bets, placed: prev.placed, lastBets: prev.lastBets, chip: prev.chip });
    }
    // JS가 새로 불러와지면(개발 중 파일 수정 등) 이전 버전의 시계·그리기 루프를 확실히 멈춘다
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
    s.clock = setInterval(() => tickClock(s), 200);
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
    bets: {},              // 아직 확정 안 한 칩 {key: amount}
    placed: [],            // 되돌리기용 [[key, amount]]
    lastBets: null,        // 지난번 확정한 베팅 (재베팅용)
    chip: data.chips.includes(10000) ? 10000 : data.chips[0],
    offset: 0,             // 서버 시각 - 내 시각
    sending: false,
    shownRound: data.view.last ? data.view.last.round : null,  // 첫 마운트 때는 지난 결과를 연출하지 않는다
    anim: null,            // 추첨 연출 {res, t0}
    tickFor: null,         // 결과를 요청한 회차
    lastErrorId: data.error ? data.error.id : null,
    lastRecent: null,
    confetti: [],
    roadCount: 0,
  };
}

const serverNow = (s) => Date.now() / 1000 + s.offset;
const betTotal = (bets) => Object.values(bets).reduce((a, b) => a + b, 0);

// ── 베팅 칸 ─────────────────────────────────────────────────────────
function buildSpots(s) {
  const box = s.els.bets;
  box.innerHTML = "";
  s.spots = {};
  SPOTS.forEach((sp) => {
    if (!sp) {
      box.insertAdjacentHTML("beforeend", `<span class="gap"></span>`);
      return;
    }
    const [key, name, cls] = sp;
    const btn = document.createElement("button");
    btn.className = `ld-spot ${cls}`;
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
    if (locked(s)) return toast(s, "베팅이 마감되었습니다.");
    const add = s.lastBets;
    if (betTotal(s.bets) + betTotal(add) > s.data.balance) return toast(s, "칩이 부족합니다.");
    Object.entries(add).forEach(([k, v]) => {
      s.bets[k] = (s.bets[k] || 0) + v;
      s.placed.push([k, v]);
    });
    render(s);
  };
  a.confirm.onclick = () => confirmBets(s);
}

function locked(s) {
  return serverNow(s) >= s.data.view.lock_at;
}

function placeChip(s, key) {
  if (locked(s)) return toast(s, "베팅이 마감되었습니다. 다음 회차를 기다려 주세요.");
  if (betTotal(s.bets) + s.chip > s.data.balance) return toast(s, "칩이 부족합니다.");
  const mine = (s.data.view.mine[key] || 0) + (s.bets[key] || 0);
  if (mine + s.chip > s.data.rules.max) return toast(s, `한 칸에 최대 ${fmt(s.data.rules.max)}까지 걸 수 있습니다.`);
  s.bets[key] = (s.bets[key] || 0) + s.chip;
  s.placed.push([key, s.chip]);
  render(s);
}

function confirmBets(s) {
  if (s.sending || !betTotal(s.bets)) return;
  if (locked(s)) return toast(s, "베팅이 마감되었습니다.");
  s.sending = true;
  s.lastBets = { ...s.bets };
  s.trigger("bet", { bets: { ...s.bets }, round: s.data.view.round, nonce: Date.now() });
  s.bets = {};
  s.placed = [];
  render(s);
}

function onKey(s, code) {
  if (chipFromKey(s, code)) return true;
  const click = (btn) => (btn.click(), true);
  switch (code) {
    case "Space":
    case "Enter": confirmBets(s); return true;
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
  s.offset = v.now - Date.now() / 1000;
  s.sending = false;
  buildChipTray(s);

  if (d.error && d.error.id !== s.lastErrorId) {
    s.lastErrorId = d.error.id;
    toast(s, d.error.msg);
  }
  // 새 추첨 결과가 왔으면 연출
  if (v.last && v.last.round !== s.shownRound) {
    s.shownRound = v.last.round;
    const anim = { res: v.last, t0: performance.now(), won: false };
    s.anim = anim;
    s.els.result.innerHTML = `<span class="sub">#${v.last.round}회차 추첨 중…</span>`;
    // 창이 가려져 그리기가 멈춰도 연출 시간이 지나면 결과를 보여 준다
    setTimeout(() => {
      if (s.anim === anim && !anim.shown) {
        anim.shown = true;
        showResult(s);
      }
    }, 8000);
  } else if (!s.anim && v.last) {
    s.anim = { res: v.last, t0: -1e9, won: true }; // 연출 없이 지난 결과만 (색종이도 없이)
    showResult(s);
  }
  render(s);
  renderRecent(s, v);
  renderStats(s, v.stats);
  renderRoad(s, v.finishes);
  renderFair(s, v);
}

function render(s) {
  const v = s.data.view;
  const isLocked = locked(s);
  Object.entries(s.spots).forEach(([key, btn]) => {
    btn.querySelector(".odds").textContent = `${v.payouts[key].toFixed(2)}배`;
    const confirmed = v.mine[key] || 0;
    btn.querySelector(".mine").textContent = confirmed ? `확정 ${short(confirmed)}` : "";
    btn.querySelector(".stack")?.remove();
    if (s.bets[key]) {
      const chip = makeChip(s.bets[key], short(s.bets[key]), true);
      chip.classList.add("stack");
      btn.appendChild(chip);
    }
    btn.disabled = isLocked;
  });
  const pending = betTotal(s.bets);
  s.actions.confirm.disabled = !pending || isLocked || s.sending;
  s.actions.confirm.firstChild.textContent = pending ? `베팅 확정 ${fmt(pending)} ` : "베팅 확정 ";
  s.actions.undo.disabled = !s.placed.length;
  s.actions.clear.disabled = !pending;
  s.actions.rebet.disabled = !s.lastBets || isLocked;
  const confirmedTotal = betTotal(v.mine);
  s.els.totalbet.textContent = fmt(confirmedTotal + pending);
  const bal = s.data.balance - pending;
  s.els.balance.textContent = fmt(bal);
  const profit = s.data.balance - s.data.start_chips;
  s.els.profit.textContent = profit > 0 ? `+${fmt(profit)}` : fmt(profit);
  s.els.profit.className = profit > 0 ? "up" : profit < 0 ? "down" : "";
  updateChipTray(s);
}

// 0.2초마다: 남은 시간, 마감, 추첨 요청
function tickClock(s) {
  if (!s.alive || !s.root.isConnected) return clearInterval(s.clock);
  const v = s.data.view;
  const now = serverNow(s);
  const left = v.draw_at - now;
  const toLock = v.lock_at - now;
  const ring = s.els.ring;
  let phase;
  if (toLock > 0) {
    phase = "베팅 중";
    ring.setAttribute("class", "bar");
    ring.style.strokeDashoffset = RING * (1 - toLock / (v.period - (v.draw_at - v.lock_at)));
  } else if (left > 0) {
    phase = "베팅 마감";
    ring.setAttribute("class", "bar lock");
    ring.style.strokeDashoffset = RING * (1 - left / (v.draw_at - v.lock_at));
    if (betTotal(s.bets)) {
      s.bets = {};
      s.placed = [];
      toast(s, "마감되어 확정하지 않은 칩은 돌려놓았습니다.");
    }
  } else {
    phase = "추첨 중";
    ring.setAttribute("class", "bar draw");
    ring.style.strokeDashoffset = 0;
    // 추첨 시각이 지났으면 결과를 요청. 내 시계가 서버보다 빨라 아직 추첨 전이었으면 2초 뒤 다시 요청
    if (left < -0.2 && (s.tickFor !== v.round || Date.now() - s.tickAt > 2000)) {
      s.tickFor = v.round;
      s.tickAt = Date.now();
      s.trigger("tick", { round: v.round, nonce: Date.now() });
    }
  }
  s.els.round.textContent = `${v.round}회차`;
  s.els.count.textContent = toLock > 0 ? Math.ceil(toLock) : left > 0 ? Math.ceil(left) : "…";
  s.els.phase.textContent = phase;
  const wasLocked = s.wasLocked;
  s.wasLocked = toLock <= 0;
  if (wasLocked !== s.wasLocked) render(s);
}

// ── 결과 / 기록 표시 ────────────────────────────────────────────────
function showResult(s) {
  const a = s.anim;
  if (!a) return;
  const r = a.res;
  const my = s.data.my_last && s.data.my_last.round === r.round ? s.data.my_last : null;
  const sideName = r.side === "L" ? "좌" : "우";
  const finName = r.finish === "odd" ? "홀" : "짝";
  s.els.result.innerHTML =
    `<span class="sub">#${r.round}회차 결과</span>` +
    `<span class="big" style="color:${COLORS[r.finish]}">${r.text}</span>` +
    `<span class="sub">${sideName} 출발 · ${r.lines}줄 · ${finName}</span>` +
    (my ? `<span class="net ${my.net > 0 ? "plus" : my.net < 0 ? "minus" : ""}">내 수익 ${my.net > 0 ? "+" : ""}${fmt(my.net)}</span>` : "");
  Object.entries(s.spots).forEach(([key, btn]) => btn.classList.toggle("won", WIN_RULE[key](r)));
  if (my && my.net > 0 && !a.won) {
    a.won = true;
    burstConfetti(s);
  }
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
    (last ? `  ·  지난 #${last.round}회차 시드 ${last.seed.slice(0, 12)}… 공개` : "");
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
const T_COVER = 0.6, T_RUNG = 0.3, SPEED = 0.55; // SPEED: 초당 이동 (사다리 높이 기준 비율)

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
    const moved = drawing ? Math.max(0, (t - startMove) * SPEED * (bot - top)) : total;
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
