// 비행기(크래시) 게임 화면 (Streamlit Custom Component v2). common.js 뒤에 이어 붙는다.
// - 파이썬(crash/game.py)이 추락 지점을 정하고 멈추기를 검증한다. 화면은 canvas로 비행을 그린다.
// - JS → 파이썬: setTriggerValue("start" | "cashout1" | "cashout2" | "finish")
// - 배당 m(t) = e^(k·t). 추락 지점은 판 시작 때 data.view.crash 로 받는다(사용자가 고른 방식).

const STATE = new WeakMap();
const QUICK = [1_000, 5_000, 10_000, 50_000, 100_000];
const BALLOONS = [1.5, 2, 3, 5, 10, 20, 50, 100, 250, 500];
const BALLOON_COLORS = ["#e8453c", "#6cc04a", "#f2c21b", "#8e5bd8", "#2f8fe0"];
const CASH_KEYS = { 1: "A", 2: "L" };
const RESULT_HOLD = 3000; // 추락 후 결과를 보여 주는 시간(ms)

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector(".bt-root");
  if (!root || !data) return;

  let s = STATE.get(parentElement);
  if (!s || s.root !== root) {
    const prev = s;
    s = createState(root);
    if (prev) {
      prev.alive = false;
      Object.assign(s, { panels: prev.panels });
    }
    STATE.set(parentElement, s);
    buildPanels(s);
    bindKeys(s, (code) => onKey(s, code));
    s.els.takeoff.onclick = () => takeoff(s);
    requestAnimationFrame((t) => frame(s, t));
  }
  s.data = data;
  s.trigger = setTriggerValue;
  sync(s);
}

// ── 상태 ────────────────────────────────────────────────────────────
function createState(root) {
  const els = {};
  root.querySelectorAll("[data-el]").forEach((el) => (els[el.dataset.el] = el));
  return {
    root, els, alive: true,
    ui: "betting",            // betting | waiting | flying | crashed
    panels: {
      1: { on: true, stake: 10_000, auto: false, target: 2.0 },
      2: { on: false, stake: 10_000, auto: true, target: 1.5 },
    },
    round: null,              // {nonce, crash, k, t0, crashT, cashed: {1: m}, finishing}
    lastNonce: null,
    lastErrorId: null,
    lastRecentNonce: null,
    trail: [],
    pops: [],                 // 터진 풍선 효과
    floats: [],               // 떠오르는 "+13,700" 표시
    clouds: makeClouds(),
    firstSync: true,
  };
}

function makeClouds() {
  const out = [];
  let seed = 7;
  const rnd = () => ((seed = (seed * 9301 + 49297) % 233280) / 233280);
  for (let i = 0; i < 18; i++) out.push({ x: rnd(), a: rnd() * 3.2, w: 0.08 + rnd() * 0.1, speed: 0.4 + rnd() * 0.6 });
  return out;
}

// ── 베팅 패널 ───────────────────────────────────────────────────────
function buildPanels(s) {
  s.panelEls = {};
  s.root.querySelectorAll(".cr-panel").forEach((el) => {
    const p = Number(el.dataset.panel);
    el.innerHTML =
      `<div class="cr-head"><span>베팅 ${p}</span><span class="cr-state"></span></div>` +
      `<div class="cr-amount"><button data-a="-">−</button><input data-a="amount" inputmode="numeric"><button data-a="+">+</button></div>` +
      `<div class="cr-quick">${QUICK.map((v) => `<button data-q="${v}">${short(v)}</button>`).join("")}</div>` +
      `<label class="cr-auto"><input type="checkbox" data-a="auto"> 자동 멈춤 <input type="number" data-a="target" min="1.01" step="0.01"> x</label>` +
      `<button class="cr-main" data-a="main"></button>`;
    const q = (sel) => el.querySelector(sel);
    const pan = () => s.panels[p];
    const editable = () => s.ui === "betting" || s.ui === "crashed";
    q('[data-a="-"]').onclick = () => editable() && setStake(s, p, pan().stake - step(pan().stake - 1));
    q('[data-a="+"]').onclick = () => editable() && setStake(s, p, pan().stake + step(pan().stake));
    q('[data-a="amount"]').onchange = (e) => setStake(s, p, Number(String(e.target.value).replace(/[^0-9]/g, "")));
    el.querySelectorAll("[data-q]").forEach((b) => (b.onclick = () => editable() && setStake(s, p, Number(b.dataset.q))));
    q('[data-a="auto"]').onchange = (e) => { pan().auto = e.target.checked; renderPanels(s); };
    q('[data-a="target"]').onchange = (e) => {
      pan().target = Math.max(1.01, Math.round(Number(e.target.value || 2) * 100) / 100);
      renderPanels(s);
    };
    q('[data-a="main"]').onclick = () => panelMain(s, p);
    s.panelEls[p] = { el, q };
  });
}

function step(v) {
  return v < 10_000 ? 1_000 : v < 100_000 ? 10_000 : 100_000;
}

function setStake(s, p, v) {
  const r = s.data.rules;
  s.panels[p].stake = Math.min(r.max, Math.max(r.min, Math.round(v / 1000) * 1000 || r.min));
  renderPanels(s);
}

// 패널의 큰 버튼: 베팅 중엔 이번 판 참가 켜기/끄기, 비행 중엔 멈추기
function panelMain(s, p) {
  if (s.ui === "betting" || s.ui === "crashed") {
    s.panels[p].on = !s.panels[p].on;
    renderPanels(s);
  } else if (s.ui === "flying") {
    cashOut(s, p);
  }
}

function renderPanels(s) {
  const r = s.round;
  const flying = s.ui === "flying";
  const m = flying ? currentMultiplier(s) : 1;
  let total = 0;
  Object.entries(s.panelEls).forEach(([key, { el, q }]) => {
    const p = Number(key);
    const pan = s.panels[p];
    const bet = r && r.bets[p];
    const editable = s.ui === "betting" || s.ui === "crashed";
    const amount = q('[data-a="amount"]');
    if (s.root.querySelector(":focus") !== amount && el.getRootNode().activeElement !== amount) amount.value = fmt(pan.stake);
    amount.disabled = !editable;
    q('[data-a="-"]').disabled = q('[data-a="+"]').disabled = !editable;
    el.querySelectorAll("[data-q]").forEach((b) => (b.disabled = !editable));
    const auto = q('[data-a="auto"]');
    auto.checked = pan.auto;
    auto.disabled = !editable;
    const target = q('[data-a="target"]');
    if (el.getRootNode().activeElement !== target) target.value = pan.target.toFixed(2);
    target.disabled = !editable || !pan.auto;

    const main = q('[data-a="main"]');
    const state = q(".cr-state");
    main.className = "cr-main";
    main.disabled = false;
    state.textContent = "";
    const showResult = s.ui === "crashed" && bet; // 추락 직후에는 이번 판 결과를 먼저 보여 준다
    if (editable && !showResult) {
      el.classList.toggle("off", !pan.on);
      main.innerHTML = pan.on ? `이번 판 참가 ✓ <kbd>${CASH_KEYS[p]}</kbd>` : `참가 안 함 <kbd>${CASH_KEYS[p]}</kbd>`;
      if (!pan.on) main.classList.add("off");
      if (pan.on) total += pan.stake;
    } else if (bet) {
      total += bet.stake;
      const cashed = r.cashed[p];
      if (cashed) {
        main.classList.add("done");
        main.textContent = `멈춤 ${cashed.toFixed(2)}x · +${fmt(Math.floor(bet.stake * cashed))}`;
        main.disabled = true;
      } else if (s.ui === "crashed" || r.crashedShown) {
        main.classList.add("lost");
        main.textContent = `추락 · -${fmt(bet.stake)}`;
        main.disabled = true;
      } else {
        main.classList.add("cash");
        main.innerHTML = `멈추기 ${fmt(Math.floor(bet.stake * m))} <kbd>${CASH_KEYS[p]}</kbd>`;
        main.disabled = s.ui !== "flying";
      }
      if (bet.auto) state.textContent = `자동 ${bet.auto.toFixed(2)}x`;
    } else {
      main.classList.add("off");
      main.textContent = "이번 판 쉬는 중";
      main.disabled = true;
    }
  });
  s.els.totalbet.textContent = fmt(total);
  s.els.takeoff.disabled = !(s.ui === "betting" || s.ui === "crashed");
}

// ── 파이썬과 주고받기 ───────────────────────────────────────────────
function takeoff(s) {
  if (s.ui !== "betting" && s.ui !== "crashed") return;
  const bets = {};
  Object.entries(s.panels).forEach(([p, pan]) => {
    if (pan.on) bets[p] = { stake: pan.stake, auto: pan.auto ? pan.target : null };
  });
  if (!Object.keys(bets).length) return toast(s, "베팅 패널을 하나 이상 켜세요.");
  const total = Object.values(bets).reduce((t, b) => t + b.stake, 0);
  if (total > s.data.balance) return toast(s, "칩이 부족합니다.");
  s.ui = "waiting";
  s.trail = [];
  renderPanels(s);
  s.trigger("start", { bets, nonce: Date.now() });
}

function cashOut(s, p) {
  const r = s.round;
  if (s.ui !== "flying" || !r || !r.bets[p] || r.cashed[p]) return;
  const m = Math.floor(currentMultiplier(s) * 100) / 100;
  r.cashed[p] = m; // 화면에는 바로 반영하고, 파이썬이 거절하면 되돌린다
  r.pending[p] = true;
  addFloat(s, `+${fmt(Math.floor(r.bets[p].stake * m))}`, "good");
  renderPanels(s);
  s.trigger(`cashout${p}`, { m, nonce: Date.now() });
}

function finishRound(s) {
  const r = s.round;
  if (!r || r.finishing) return;
  r.finishing = true;
  s.trigger("finish", { nonce: r.nonce });
}

function sync(s) {
  const d = s.data;
  const v = d.view;
  if (d.error && d.error.id !== s.lastErrorId) {
    const first = s.lastErrorId === null && s.firstSync;
    s.lastErrorId = d.error.id;
    if (!first) toast(s, d.error.msg);
    if (s.ui === "waiting") s.ui = "betting";
    // 거절된 멈추기는 되돌린다
    if (s.round) Object.keys(s.round.pending).forEach((p) => {
      const conf = v.bets[p];
      if (!conf || conf.cashed_at == null) delete s.round.cashed[p];
      delete s.round.pending[p];
    });
  }

  if (v.phase === "flying") {
    if (!s.round || s.round.nonce !== v.nonce) startRound(s, v);
    // 파이썬이 확인한 멈춤 배당으로 맞춘다
    Object.entries(v.bets).forEach(([p, b]) => {
      if (b.cashed_at != null) s.round.cashed[p] = b.cashed_at;
      delete s.round.pending[p];
    });
  } else if (s.round && !s.round.done && v.last && v.last.nonce === s.round.nonce) {
    endRound(s, v.last);
  } else if (s.ui === "waiting") {
    s.ui = "betting";
  }

  renderRecent(s, v);
  renderFair(s, v);
  setBalance(s);
  renderPanels(s);
  s.firstSync = false;
}

function startRound(s, v) {
  const now = performance.now();
  const bets = {};
  Object.entries(v.bets).forEach(([p, b]) => (bets[p] = b));
  s.round = {
    nonce: v.nonce, crash: v.crash, k: v.k,
    t0: now - (v.elapsed || 0) * 1000,   // 다른 페이지에 다녀오면 서버 기준 경과 시간부터 이어서
    crashT: Math.log(v.crash) / v.k,
    bets, cashed: {}, pending: {}, finishing: false, done: false, crashedShown: false,
  };
  s.ui = "flying";
  s.trail = [];
  s.pops = [];
  s.els.msg.textContent = "";
  s.els.msg.className = "cr-msg";
  // 창이 가려져 애니메이션이 멈춰도 판이 끝나도록
  const left = Math.max(0, s.round.crashT * 1000 - (now - s.round.t0));
  const nonce = v.nonce;
  setTimeout(() => {
    if (s.round && s.round.nonce === nonce && !s.round.crashedShown) crashNow(s);
  }, left + 50);
}

function crashNow(s) {
  const r = s.round;
  r.crashedShown = true;
  r.crashAt = performance.now();
  s.els.msg.textContent = `추락! ${r.crash.toFixed(2)}x`;
  s.els.msg.className = "cr-msg bad";
  renderPanels(s);
  finishRound(s);
}

function endRound(s, last) {
  const r = s.round;
  r.done = true;
  if (!r.crashedShown) crashNow(s);
  last.bets.forEach((b) => {
    if (b.cashed_at != null) r.cashed[b.panel] = b.cashed_at;
  });
  const net = last.net;
  s.els.msg.textContent = `추락 ${last.crash.toFixed(2)}x · ${net > 0 ? `+${fmt(net)}` : net < 0 ? `-${fmt(-net)}` : "본전"}`;
  s.els.msg.className = `cr-msg ${net > 0 ? "good" : net < 0 ? "bad" : ""}`;
  s.ui = "crashed";
  const nonce = r.nonce;
  setTimeout(() => {
    if (s.round && s.round.nonce === nonce && s.ui === "crashed") {
      s.ui = "betting";
      s.els.msg.textContent = "";
      s.els.msg.className = "cr-msg";
      renderPanels(s);
    }
  }, RESULT_HOLD);
}

function currentMultiplier(s) {
  const r = s.round;
  if (!r) return 1;
  const t = (performance.now() - r.t0) / 1000;
  return Math.min(Math.exp(r.k * Math.max(0, t)), r.crash);
}

// ── 표시 ────────────────────────────────────────────────────────────
function setBalance(s) {
  const bal = s.data.balance;
  s.els.balance.textContent = fmt(bal);
  const profit = bal - s.data.start_chips;
  s.els.profit.textContent = profit > 0 ? `+${fmt(profit)}` : fmt(profit);
  s.els.profit.className = profit > 0 ? "up" : profit < 0 ? "down" : "";
}

function renderRecent(s, v) {
  const box = s.els.recent;
  const newest = v.last ? v.last.nonce : null;
  if (newest === s.lastRecentNonce && box.childElementCount === v.recent.length) return;
  // 비행 중에는 이번 판 결과를 아직 보여 주지 않는다
  box.innerHTML = v.recent
    .map((x, i) => `<span class="${x < 2 ? "low" : x < 10 ? "mid" : "high"}${i === 0 && s.lastRecentNonce !== null ? " fresh" : ""}">${x.toFixed(2)}x</span>`)
    .join("");
  s.lastRecentNonce = newest;
}

function renderFair(s, v) {
  const last = v.last;
  s.els.fair.textContent = `이번 판 #${v.phase === "flying" ? v.nonce : v.nonce + 1} 해시 ${v.commit.slice(0, 16)}…` +
    (last ? `  ·  지난 판 #${last.nonce} 서버 시드 ${last.server_seed.slice(0, 12)}… 공개` : "");
}

function addFloat(s, text, kind) {
  s.floats.push({ text, kind, t: performance.now() });
}

// ── 단축키 ──────────────────────────────────────────────────────────
function onKey(s, code) {
  if (code === "Space" || code === "Enter") {
    takeoff(s);
    return true;
  }
  if (code === "KeyA") { panelMain(s, 1); return true; }
  if (code === "KeyL") { panelMain(s, 2); return true; }
  return false;
}

// ── canvas 그리기 ───────────────────────────────────────────────────
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

  const r = s.round;
  const flying = s.ui === "flying" && r;
  let t = r ? (now - r.t0) / 1000 : 0;
  if (flying && !r.crashedShown && t >= r.crashT) crashNow(s);
  const crashed = r && r.crashedShown;
  const showRound = r && (s.ui === "flying" || s.ui === "crashed" || s.ui === "waiting" && crashed);
  const m = showRound ? (crashed ? r.crash : Math.min(Math.exp(r.k * Math.max(0, t)), r.crash)) : 1;

  // 자동 멈춤: 화면에 바로 보여 준다 (지급은 파이썬이 판 끝에 한다)
  if (flying && !crashed) {
    Object.entries(r.bets).forEach(([p, b]) => {
      if (b.auto && !r.cashed[p] && m >= b.auto) {
        r.cashed[p] = b.auto;
        addFloat(s, `+${fmt(Math.floor(b.stake * b.auto))}`, "good");
      }
    });
  }

  // 월드 좌표: 고도 a = ln(m) · S. 비행기가 화면 높이의 42%까지 오르면 카메라가 따라 올라간다.
  const S = H * 0.55;
  const baseY = H * 0.8;
  const A = Math.log(m) * S;
  const cam = Math.max(0, A - H * 0.42);
  const toY = (a) => baseY - (a - cam);
  const flyT = showRound ? (crashed ? r.crashT : t) : 0;

  drawSky(ctx, W, H, cam, S);
  drawClouds(s, ctx, W, H, now, cam, S, toY);
  drawCity(ctx, W, H, toY(0));
  drawBalloons(s, ctx, W, H, m, S, toY, now);

  // 비행기 위치: 처음 5초 동안 오른쪽으로 나아가고, 그 뒤엔 화면 안에서 살짝 흔들린다
  const p = Math.min(1, flyT / 5);
  let px = W * (0.12 + 0.42 * (1 - Math.pow(1 - p, 2)));
  let py = toY(A) - (showRound ? 0 : 0);
  let angle = showRound ? -0.18 - Math.min(0.2, A / (H * 4)) : 0;
  if (!showRound) {
    px = W * 0.12;
    py = toY(0) - 6;
  }
  if (crashed) {
    const ct = (now - (r.crashAt || now)) / 1000;
    px += ct * W * 0.08;
    py += ct * ct * H * 0.9;
    angle = Math.min(1.3, -0.2 + ct * 2.4);
  } else if (showRound) {
    py += Math.sin(now / 420) * 3;
  }

  if (showRound && !crashed && (!s.trail.length || now - s.trail[s.trail.length - 1].t > 60)) {
    s.trail.push({ x: px, a: A + (baseY - py) - (baseY - toY(A)), t: now });
    if (s.trail.length > 70) s.trail.shift();
  }
  drawTrail(s, ctx, W, now, toY);
  drawPlane(ctx, px, py, angle, now, Math.max(0.7, Math.min(1.25, W / 700)), crashed);
  if (crashed) drawSmoke(ctx, px, py, now, r.crashAt);
  drawFloats(s, ctx, px, py, now);

  // 큰 배당 숫자
  const mult = s.els.mult;
  const text = `${m.toFixed(2)}x`;
  if (mult.textContent !== text) mult.textContent = text;
  mult.className = `cr-mult${!showRound ? " idle" : crashed ? " crashed" : ""}`;
  if (flying && !crashed && now - (s.lastPanelPaint || 0) > 120) {
    s.lastPanelPaint = now;
    renderPanels(s);
  }
  if (!showRound && !s.els.msg.textContent) {
    s.els.msg.textContent = "베팅하고 이륙하세요";
  } else if (showRound && s.els.msg.textContent === "베팅하고 이륙하세요") {
    s.els.msg.textContent = "";
  }
}

function drawSky(ctx, W, H, cam, S) {
  // 높이 오를수록 하늘이 조금씩 짙어진다
  const k = Math.min(1, cam / (S * 5));
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, mix("#3fa9f5", "#1b4f9c", k));
  g.addColorStop(1, mix("#bfe6ff", "#6fb3ea", k));
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
}

function drawClouds(s, ctx, W, H, now, cam, S, toY) {
  const band = 3.2 * S; // 구름 무늬가 반복되는 높이
  s.clouds.forEach((c) => {
    const x = (((c.x - (now / 1000) * c.speed * 0.02) % 1) + 1) % 1;
    let a = c.a * S;
    a += Math.floor((cam - a + H * 0.5) / band) * band; // 카메라 근처로 반복
    const y = toY(a) - H * 0.25;
    if (y < -60 || y > H + 60) return;
    cloud(ctx, x * (W + 200) - 100, y, c.w * W);
  });
}

function cloud(ctx, x, y, w) {
  ctx.fillStyle = "rgba(255,255,255,.92)";
  ctx.beginPath();
  ctx.ellipse(x, y, w * 0.5, w * 0.16, 0, 0, Math.PI * 2);
  ctx.ellipse(x - w * 0.18, y - w * 0.08, w * 0.22, w * 0.16, 0, 0, Math.PI * 2);
  ctx.ellipse(x + w * 0.12, y - w * 0.12, w * 0.26, w * 0.2, 0, 0, Math.PI * 2);
  ctx.fill();
}

function drawCity(ctx, W, H, groundY) {
  if (groundY > H + 120) return;
  // 멀리 보이는 도시: 낮고 흐린 색 (무대 높이의 약 1/5)
  ctx.fillStyle = "rgba(16, 38, 63, .78)";
  const blocks = [[0, 40], [0.05, 70], [0.1, 50], [0.14, 95], [0.2, 60], [0.26, 110], [0.31, 55], [0.36, 80],
    [0.42, 45], [0.47, 120], [0.52, 65], [0.58, 90], [0.64, 50], [0.7, 100], [0.76, 60], [0.82, 85], [0.88, 55], [0.94, 75]];
  const scale = Math.min(0.62, H / 560);
  blocks.forEach(([x, h], i) => {
    const bw = W * 0.06;
    ctx.fillRect(x * W, groundY - h * scale, bw, h * scale + 200);
    if (i % 4 === 1) ctx.fillRect(x * W + bw * 0.4, groundY - h * scale - 18 * scale, 3, 18 * scale); // 안테나
  });
  // 관람차 (사진의 오른쪽 아래 느낌)
  ctx.strokeStyle = "#10263f";
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.arc(W * 0.9, groundY - 60 * scale, 34 * scale, 0, Math.PI * 2);
  ctx.stroke();
}

function drawBalloons(s, ctx, W, H, m, S, toY, now) {
  BALLOONS.forEach((b, i) => {
    const y = toY(Math.log(b) * S) - 30;
    const x = W * (0.6 + (i % 3) * 0.12);
    if (m >= b) {
      if (!s.pops.includes(b) && s.ui === "flying") {
        s.pops.push(b);
        s.popAt = { ...(s.popAt || {}), [b]: now };
      }
      const pt = s.popAt && s.popAt[b];
      if (pt && now - pt < 400) burst(ctx, x, y, (now - pt) / 400, BALLOON_COLORS[i % BALLOON_COLORS.length]);
      return;
    }
    if (y < -60 || y > H + 60) return;
    balloon(ctx, x, y + Math.sin(now / 700 + i) * 4, BALLOON_COLORS[i % BALLOON_COLORS.length], `${b}x`, Math.min(1.2, W / 600));
  });
}

function balloon(ctx, x, y, color, label, k) {
  const rx = 17 * k, ry = 21 * k;
  ctx.strokeStyle = "rgba(16,38,63,.6)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(x, y + ry);
  ctx.quadraticCurveTo(x - 6, y + ry + 14, x + 2, y + ry + 26);
  ctx.stroke();
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "rgba(255,255,255,.35)";
  ctx.beginPath();
  ctx.ellipse(x - rx * 0.35, y - ry * 0.35, rx * 0.25, ry * 0.3, -0.4, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#fff";
  ctx.font = `800 ${Math.round(12 * k)}px system-ui, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(label, x, y);
}

function burst(ctx, x, y, p, color) {
  ctx.strokeStyle = color;
  ctx.lineWidth = 3;
  for (let i = 0; i < 8; i++) {
    const a = (i / 8) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(x + Math.cos(a) * 10 * (1 + p), y + Math.sin(a) * 10 * (1 + p));
    ctx.lineTo(x + Math.cos(a) * 26 * (1 + p), y + Math.sin(a) * 26 * (1 + p));
    ctx.stroke();
  }
}

function drawTrail(s, ctx, W, now, toY) {
  s.trail.forEach((pt, i) => {
    const age = (now - pt.t) / 1000;
    const x = pt.x - age * W * 0.12;
    const y = toY(pt.a);
    const alpha = Math.max(0, 0.55 - age * 0.12);
    if (alpha <= 0) return;
    ctx.fillStyle = `rgba(255,255,255,${alpha})`;
    ctx.beginPath();
    ctx.arc(x, y + 4, 3 + age * 5, 0, Math.PI * 2);
    ctx.fill();
  });
}

function drawPlane(ctx, x, y, angle, now, k, crashed) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(angle);
  ctx.scale(k, k);
  // 꼬리 날개
  ctx.fillStyle = "#d8322a";
  ctx.beginPath();
  ctx.moveTo(-38, -4);
  ctx.lineTo(-46, -22);
  ctx.lineTo(-32, -22);
  ctx.lineTo(-24, -4);
  ctx.fill();
  // 몸통
  ctx.fillStyle = "#2b4fd8";
  ctx.beginPath();
  ctx.ellipse(0, 0, 40, 10, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#1c3aa8";
  ctx.fillRect(-40, 2, 70, 4);
  // 조종석 창
  ctx.fillStyle = "#bfe9ff";
  ctx.beginPath();
  ctx.ellipse(12, -6, 9, 5, 0, Math.PI, 0);
  ctx.fill();
  // 날개
  ctx.fillStyle = "#e8453c";
  ctx.beginPath();
  ctx.moveTo(-8, 2);
  ctx.lineTo(8, 2);
  ctx.lineTo(-2, 20);
  ctx.lineTo(-16, 20);
  ctx.fill();
  // 기수와 프로펠러
  ctx.fillStyle = "#f2c21b";
  ctx.beginPath();
  ctx.ellipse(40, 0, 5, 7, 0, 0, Math.PI * 2);
  ctx.fill();
  const spin = crashed ? 0.3 : Math.abs(Math.sin(now / 30));
  ctx.fillStyle = "rgba(60,60,60,.75)";
  ctx.beginPath();
  ctx.ellipse(45, 0, 2.5, 16 * spin + 2, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawSmoke(ctx, x, y, now, at) {
  const ct = (now - (at || now)) / 1000;
  for (let i = 0; i < 6; i++) {
    const age = ct - i * 0.08;
    if (age < 0) continue;
    ctx.fillStyle = `rgba(60,60,70,${Math.max(0, 0.5 - age * 0.3)})`;
    ctx.beginPath();
    ctx.arc(x - 20 - i * 10, y - 10 - age * 30, 8 + age * 14, 0, Math.PI * 2);
    ctx.fill();
  }
  if (ct < 0.25) {
    ctx.fillStyle = `rgba(255,190,60,${0.8 - ct * 3})`;
    ctx.beginPath();
    ctx.arc(x, y, 30 + ct * 120, 0, Math.PI * 2);
    ctx.fill();
  }
}

function drawFloats(s, ctx, x, y, now) {
  s.floats = s.floats.filter((f) => now - f.t < 1500);
  s.floats.forEach((f) => {
    const p = (now - f.t) / 1500;
    ctx.globalAlpha = 1 - p;
    ctx.fillStyle = f.kind === "good" ? "#1f9d55" : "#e0463a";
    ctx.font = "900 20px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 4;
    ctx.strokeText(f.text, x, y - 30 - p * 50);
    ctx.fillText(f.text, x, y - 30 - p * 50);
    ctx.globalAlpha = 1;
  });
}

function mix(a, b, k) {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  return `rgb(${pa.map((v, i) => Math.round(v + (pb[i] - v) * k)).join(",")})`;
}
