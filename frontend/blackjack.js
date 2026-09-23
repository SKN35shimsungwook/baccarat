// 블랙잭 테이블 화면 (Streamlit Custom Component v2). common.js 뒤에 이어 붙는다.
// - 파이썬(bj/game.py)이 판을 진행하고, 화면은 data.view 를 그린다.
// - JS → 파이썬: setTriggerValue("deal" | "action" | "insurance")
// - 카드마다 id가 있어서, 이전 화면에 없던 카드만 날아오는 애니메이션을 준다 (딜링 순서 = id 순서).

const STATE = new WeakMap();
const SEAT_COUNT = 3;
const BET_KEYS = ["main", "pp", "t213"];
const RESULT_TEXT = { blackjack: "블랙잭", win: "승", lose: "패", push: "푸시", surrender: "서렌더" };
const ACTION_TEXT = { hit: "히트", stand: "스탠드", double: "더블", split: "스플릿", surrender: "서렌더" };
const DEAL_GAP = 0.34; // 카드 사이 간격(초)

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector(".bt-root");
  if (!root || !data) return;

  loadAssets(data.asset_base);
  let s = STATE.get(parentElement);
  if (!s || s.root !== root) {
    const prev = s;
    s = createState(root, data);
    if (prev) Object.assign(s, { chip: prev.chip, lastBets: prev.lastBets, lastStepId: prev.lastStepId, lastErrorId: prev.lastErrorId });
    STATE.set(parentElement, s);
    buildSeats(s);
    bind(s);
  }
  s.data = data;
  s.trigger = setTriggerValue;
  setDealer(s, data.dealer || "m");
  sync(s);
}

// ── 상태 ────────────────────────────────────────────────────────────
function createState(root, data) {
  const els = {};
  root.querySelectorAll("[data-el]").forEach((el) => (els[el.dataset.el] = el));
  const actions = {};
  root.querySelectorAll("[data-act]").forEach((el) => (actions[el.dataset.act] = el));
  const plays = {};
  root.querySelectorAll("[data-play]").forEach((el) => (plays[el.dataset.play] = el));
  return {
    root, els, actions, plays,
    ui: "betting",       // betting | waiting | animating | round | result
    bets: {},            // {seat: {main, pp, t213}}
    placed: [],          // 되돌리기용 [[seat, key, amount]]
    lastBets: null,
    chip: data.chips.includes(10000) ? 10000 : data.chips[0],
    known: new Map(),    // 화면에 이미 그린 카드 id → "face" | "hidden"
    lastStepId: data.step ? data.step.id : null,
    lastErrorId: data.error ? data.error.id : null,
    firstSync: true,
    insurance: {},
  };
}

function buildSeats(s) {
  const box = s.els.seats;
  box.innerHTML = "";
  s.seatEls = [];
  for (let i = 0; i < SEAT_COUNT; i++) {
    const seat = document.createElement("div");
    seat.className = "bj-seat";
    seat.innerHTML =
      `<div class="bj-hands"></div>` +
      `<div class="bj-spots">` +
      `<button class="bj-spot side" data-key="pp" title="퍼펙트 페어">PP</button>` +
      `<button class="bj-spot main" data-key="main" title="${i + 1}번 자리 메인 베팅">${i + 1}</button>` +
      `<button class="bj-spot side" data-key="t213" title="21+3">21+3</button>` +
      `</div><div class="bj-seat-net later"></div>`;
    seat.querySelectorAll(".bj-spot").forEach((b) => (b.onclick = () => placeChip(s, i, b.dataset.key)));
    box.appendChild(seat);
    s.seatEls.push({
      root: seat,
      hands: seat.querySelector(".bj-hands"),
      spots: Object.fromEntries([...seat.querySelectorAll(".bj-spot")].map((b) => [b.dataset.key, b])),
      net: seat.querySelector(".bj-seat-net"),
    });
  }
}

function bind(s) {
  const a = s.actions;
  a.undo.onclick = () => {
    if (!canBet(s)) return;
    const last = s.placed.pop();
    if (!last) return;
    const [seat, key, amount] = last;
    s.bets[seat][key] -= amount;
    renderBetting(s);
  };
  a.clear.onclick = () => {
    if (!canBet(s)) return;
    s.bets = {};
    s.placed = [];
    renderBetting(s);
  };
  a.x2.onclick = () => canBet(s) && applyBets(s, s.bets);
  a.rebet.onclick = () => {
    if (!canBet(s)) return;
    if (!s.lastBets) return toast(s, "지난 판 베팅이 없습니다.");
    applyBets(s, s.lastBets);
  };
  a.deal.onclick = () => deal(s);
  Object.entries(s.plays).forEach(([act, btn]) => (btn.onclick = () => play(s, act)));
}

const betTotal = (bets) => Object.values(bets).reduce((t, b) => t + sum(b), 0);

// 결과 화면에서 칩을 놓으면 테이블을 비우고 새 베팅을 시작한다
function canBet(s) {
  if (s.ui === "waiting" || s.ui === "animating" || s.ui === "round") return false;
  if (s.ui === "result") {
    s.ui = "betting";
    clearRound(s);
  }
  return true;
}

function checkAdd(s, bets, seat, key, amount) {
  const r = s.data.rules;
  const cur = bets[seat] || {};
  if (key !== "main" && !cur.main) return "메인 베팅(가운데 원)을 먼저 놓으세요.";
  const limit = key === "main" ? r.max : r.side_max;
  if ((cur[key] || 0) + amount > limit) return `최대 베팅은 ${fmt(limit)}입니다.`;
  if (betTotal(bets) + amount > s.data.balance) return "칩이 부족합니다.";
  return null;
}

function placeChip(s, seat, key) {
  if (!canBet(s)) return;
  const err = checkAdd(s, s.bets, seat, key, s.chip);
  if (err) return toast(s, err);
  s.bets[seat] = s.bets[seat] || { main: 0, pp: 0, t213: 0 };
  s.bets[seat][key] += s.chip;
  s.placed.push([seat, key, s.chip]);
  renderBetting(s);
}

// 2배/재베팅: 전부 가능할 때만 반영 (메인 먼저 놓아야 사이드가 검사를 통과한다)
function applyBets(s, add) {
  const next = JSON.parse(JSON.stringify(s.bets));
  const steps = [];
  for (const [seat, b] of Object.entries(add)) {
    for (const key of BET_KEYS) {
      if (!b[key]) continue;
      const err = checkAdd(s, next, seat, key, b[key]);
      if (err) return toast(s, err);
      next[seat] = next[seat] || { main: 0, pp: 0, t213: 0 };
      next[seat][key] += b[key];
      steps.push([seat, key, b[key]]);
    }
  }
  if (!steps.length) return;
  s.bets = next;
  s.placed.push(...steps);
  renderBetting(s);
}

function deal(s) {
  if (s.ui !== "betting" && s.ui !== "result") return;
  if (!betTotal(s.bets)) return toast(s, "먼저 베팅하세요.");
  s.lastBets = JSON.parse(JSON.stringify(s.bets));
  s.ui = "waiting";
  setStatus(s, "베팅 마감 · 카드 분배 중");
  updateControls(s);
  s.trigger("deal", { bets: s.bets, nonce: Date.now() });
}

function play(s, act) {
  if (s.ui !== "round" || !s.data.view.legal.includes(act)) return;
  s.ui = "waiting";
  s.lastPlaySeat = s.data.view.active ? s.data.view.active.seat : null;
  updateControls(s);
  s.trigger("action", { action: act, nonce: Date.now() });
}

function sendInsurance(s) {
  if (s.ui !== "round") return;
  s.ui = "waiting";
  updateControls(s);
  s.trigger("insurance", { decisions: { ...s.insurance }, nonce: Date.now() });
}

// ── 파이썬 → 화면 ───────────────────────────────────────────────────
function sync(s) {
  const d = s.data;
  buildChipTray(s);
  renderRules(s);

  if (d.error && d.error.id !== s.lastErrorId) {
    s.lastErrorId = d.error.id;
    toast(s, d.error.msg);
    if (s.ui === "waiting") s.ui = d.view.phase === "insurance" || d.view.phase === "player" ? "round" : "betting";
  }

  const fresh = d.step && d.step.id !== s.lastStepId;
  if (fresh) s.lastStepId = d.step.id;
  if (s.ui === "animating" && !fresh) return; // 연출 중 다른 이유로 다시 실행된 경우

  if (fresh && !s.firstSync) {
    animateStep(s, d.view, d.step);
  } else {
    showStatic(s, d.view);
  }
  s.firstSync = false;
}

function inRound(view) {
  return view.phase === "insurance" || view.phase === "player";
}

// 연출 없이 현재 상태를 그린다 (첫 마운트, 페이지 이동 후 복귀 등)
function showStatic(s, view) {
  if (view.seats.length && (inRound(view) || s.ui !== "betting")) {
    renderRound(s, view, false);
    s.ui = inRound(view) ? "round" : "result";
    revealLabels(s);
    if (view.phase === "done") showResult(s, view, false);
  } else {
    s.ui = "betting";
    clearRound(s);
  }
  setBalance(s, s.data.balance, s.ui === "betting" ? betTotal(s.bets) : roundStakeOf(view));
  updateControls(s);
}

async function animateStep(s, view, step) {
  s.ui = "animating";
  updateControls(s);
  if (step.shuffled) toast(s, "컷 카드가 나와 새 슈로 섞었습니다.");
  if (step.kind === "deal") {
    // 베팅은 이제 판에 올라갔으니 비운다 (재베팅용으로 lastBets에 남아 있다)
    s.bets = {};
    s.placed = [];
    s.els.banner.className = "bt-banner";
    clearRound(s, true);
  }
  // 이번 단계에서 딜러 홀카드가 공개되면, 딜러가 카드를 들어 보인 뒤 테이블에서 뒤집는다
  const hole = view.dealer.cards[1];
  const revealing = hole && !hole.hidden && s.known.get(hole.id) === "hidden";
  if (step.kind === "deal") playClip(s, "deal");
  else if (revealing) await playClip(s, "show", { card: hole });
  else playClip(s, step.seat === 0 ? "player" : step.seat === 2 ? "banker" : "deal", { rate: 1.2 });

  // 판이 끝나며 돌려받은 금액은 연출이 끝난 뒤에 보유 칩에 반영한다
  setBalance(s, s.data.balance - (step.credited || 0), roundStakeOf(view));
  const ms = renderRound(s, view, true);
  await sleep(ms);
  revealLabels(s);
  setBalance(s, s.data.balance, view.phase === "done" ? 0 : roundStakeOf(view));

  if (view.phase === "done") {
    s.ui = "result";
    showResult(s, view, true);
    stopClips(s);
  } else {
    s.ui = "round";
    if (view.phase === "insurance") s.insurance = {};
  }
  updateControls(s);
}

// ── 그리기 ──────────────────────────────────────────────────────────
function cardEl(s, c) {
  const el = document.createElement("div");
  el.className = "bt-card";
  el.dataset.id = c.id;
  const base = s.data.asset_base;
  el.innerHTML =
    (c.hidden ? "" : `<div class="face"><img src="${base}cards/${c.rank}${c.suit}.webp" alt="${c.rank}${SUIT[c.suit]}"></div>`) +
    `<div class="back"><img src="${base}cards/back.webp" alt=""></div>`;
  if (!c.hidden) el.classList.add("revealed");
  return el;
}

// 카드를 다시 그리고, 새로 나온 카드와 뒤집힌 카드에 순서대로 애니메이션을 건다. 걸리는 시간(ms)을 돌려준다.
function renderRound(s, view, animate) {
  const moves = [];
  const place = (box, c) => {
    const el = cardEl(s, c);
    const before = s.known.get(c.id);
    if (!before) moves.push({ el, kind: "new", id: c.id });
    else if (before === "hidden" && !c.hidden) moves.push({ el, kind: "flip", id: c.id });
    box.appendChild(el);
  };

  // 딜러
  s.els.dcards.innerHTML = "";
  view.dealer.cards.forEach((c) => place(s.els.dcards, c));
  const d = view.dealer;
  s.els.dtotal.textContent = d.cards.length ? (d.blackjack ? "블랙잭" : totalText(d.total, d.soft && d.revealed)) : "";
  s.els.dtotal.className = `bj-total later${d.bust ? " bust" : d.blackjack ? " bj" : ""}`;

  // 자리
  const bySeat = Object.fromEntries(view.seats.map((st) => [st.index, st]));
  s.seatEls.forEach((se, i) => {
    const st = bySeat[i];
    se.hands.innerHTML = "";
    se.root.classList.toggle("active", !!(view.active && view.active.seat === i));
    Object.values(se.spots).forEach((b) => b.classList.remove("won"));
    renderStacks(se, st ? { main: st.main, pp: st.pp, t213: st.t213 } : {});
    se.net.textContent = "";
    if (!st) return;
    st.hands.forEach((h, hi) => {
      const hand = document.createElement("div");
      hand.className = "bj-hand";
      if (view.active && view.active.seat === i && view.active.hand === hi) hand.classList.add("active");
      const cards = document.createElement("div");
      cards.className = "bj-cards";
      h.cards.forEach((c) => place(cards, c));
      const meta = document.createElement("div");
      meta.className = "bj-hand-meta later";
      const total = h.blackjack ? "블랙잭" : totalText(h.total, h.soft);
      meta.innerHTML =
        `<span class="bj-total${h.bust ? " bust" : h.blackjack ? " bj" : ""}">${h.bust ? `${h.total} 버스트` : total}</span>` +
        (h.doubled ? `<span class="bj-tag">더블</span>` : "") +
        (h.result ? `<span class="bj-tag ${h.result}">${RESULT_TEXT[h.result]}</span>` : "");
      hand.append(cards, meta);
      se.hands.appendChild(hand);
    });
    // 사이드 베팅 결과는 첫 두 장이 깔린 뒤 바로 나온다
    st.side.forEach((e) => {
      if (e.outcome === "win") se.spots[e.bet === "bj_pp" ? "pp" : "t213"].classList.add("won");
    });
    if (view.phase === "done") {
      const net = seatNet(view, st);
      se.net.textContent = net ? signed(net) : "본전";
      se.net.className = `bj-seat-net later ${net > 0 ? "plus" : net < 0 ? "minus" : ""}`;
    }
  });

  if (!animate) {
    moves.forEach((m) => s.known.set(m.id, m.el.classList.contains("revealed") ? "face" : "hidden"));
    rememberAll(s, view);
    return 0;
  }
  // 뒤집기(딜러 홀카드)가 먼저, 그 다음 새 카드를 딜링 순서(id)대로
  moves.sort((a, b) => (a.kind === "flip" ? 0 : 1) - (b.kind === "flip" ? 0 : 1) || a.id - b.id);
  moves.forEach((m, k) => {
    m.el.style.setProperty("--d", `${k * DEAL_GAP}s`);
    m.el.classList.add(m.kind);
  });
  rememberAll(s, view);
  s.root.querySelectorAll(".later").forEach((el) => el.classList.add("pending"));
  return moves.length ? (moves.length - 1) * DEAL_GAP * 1000 + 480 : 0;
}

function rememberAll(s, view) {
  s.known.clear();
  view.dealer.cards.forEach((c) => s.known.set(c.id, c.hidden ? "hidden" : "face"));
  view.seats.forEach((st) => st.hands.forEach((h) => h.cards.forEach((c) => s.known.set(c.id, "face"))));
}

function revealLabels(s) {
  s.root.querySelectorAll(".later.pending").forEach((el) => el.classList.remove("pending"));
}

function totalText(total, soft) {
  return soft && total < 21 ? `${total - 10}/${total}` : `${total}`;
}

function seatNet(view, st) {
  const main = st.hands.reduce((t, h) => t + h.returned - h.bet, 0);
  const side = st.side.reduce((t, e) => t + e.returned - e.stake, 0);
  const ins = st.insurance ? (view.dealer.blackjack ? st.insurance * 2 : -st.insurance) : 0;
  return main + side + ins;
}

function roundStakeOf(view) {
  return view.seats.reduce(
    (t, st) => t + st.pp + st.t213 + (st.insurance || 0) + st.hands.reduce((a, h) => a + h.bet, 0), 0);
}

function clearRound(s, keepStacks = false) {
  s.els.dcards.innerHTML = "";
  s.els.dtotal.textContent = "";
  s.known.clear();
  s.seatEls.forEach((se, i) => {
    se.hands.innerHTML = "";
    se.net.textContent = "";
    se.root.classList.remove("active");
    Object.values(se.spots).forEach((b) => b.classList.remove("won"));
    if (!keepStacks) renderStacks(se, s.bets[i] || {});
  });
  s.els.banner.className = "bt-banner";
  if (!keepStacks) renderBetting(s);
}

function renderStacks(se, bets) {
  BET_KEYS.forEach((key) => {
    const spot = se.spots[key];
    spot.querySelector(".stack")?.remove();
    if (bets[key]) {
      const chip = makeChip(bets[key], short(bets[key]), true);
      chip.classList.add("stack");
      spot.appendChild(chip);
    }
  });
}

function renderBetting(s) {
  s.seatEls.forEach((se, i) => renderStacks(se, s.bets[i] || {}));
  const total = betTotal(s.bets);
  setBalance(s, s.data.balance - total, total);
  updateChipTray(s);
  updateControls(s);
}

function showResult(s, view, withBanner) {
  const net = view.round ? view.round.net : 0;
  const d = view.dealer;
  const dealerText = d.blackjack ? "딜러 블랙잭" : d.bust ? "딜러 버스트" : `딜러 ${d.total}`;
  setStatus(s, `${dealerText} · ${net > 0 ? `${signed(net)} 획득` : net < 0 ? signed(net) : "본전"}`);
  if (withBanner) {
    s.els.banner.className = `bt-banner show ${net > 0 ? "P" : net < 0 ? "B" : "T"}`;
    s.els.banner.textContent = net ? signed(net) : "본전";
  }
}

function renderRules(s) {
  const r = s.data.rules;
  s.els.rule1.textContent = `BLACKJACK PAYS ${r.bj_payout.replace(":", " TO ")}`;
  s.els.rule2.textContent =
    `${r.h17 ? "DEALER HITS SOFT 17" : "DEALER MUST STAND ON ALL 17s"} · INSURANCE PAYS 2 TO 1`;
}

function setBalance(s, shown, totalBet) {
  s.els.balance.textContent = fmt(shown);
  s.els.totalbet.textContent = fmt(totalBet);
  const inPlay = s.ui === "betting" ? totalBet : 0;
  const profit = shown + inPlay - s.data.start_chips;
  s.els.profit.textContent = signed(profit);
  s.els.profit.className = profit > 0 ? "up" : profit < 0 ? "down" : "";
}

function setStatus(s, text) {
  s.els.status.textContent = text;
}

// 버튼·안내 문구를 현재 단계에 맞춘다
function updateControls(s) {
  const view = s.data.view;
  const betting = s.ui === "betting" || s.ui === "result";
  const playing = s.ui === "round" && view.phase === "player";
  const insuring = s.ui === "round" && view.phase === "insurance";

  s.els.betacts.classList.toggle("hide", !betting);
  const has = betTotal(s.bets) > 0;
  s.actions.undo.disabled = !s.placed.length;
  s.actions.clear.disabled = !has;
  s.actions.x2.disabled = !has;
  s.actions.rebet.disabled = !s.lastBets || has;
  s.actions.deal.disabled = !has;
  s.els.chiptray.style.display = betting ? "" : "none";

  s.els.playacts.classList.toggle("show", playing || s.ui === "waiting" && view.phase === "player");
  const hint = s.data.show_hint && playing ? view.hint : null;
  Object.entries(s.plays).forEach(([act, btn]) => {
    btn.disabled = !playing || !view.legal.includes(act);
    btn.classList.toggle("hinted", act === hint);
  });

  renderInsurance(s, insuring);
  renderCount(s);

  let hintText = "";
  if (s.data.show_hint && playing && hint) hintText = `기본 전략: ${ACTION_TEXT[hint]}`;
  if (s.data.show_hint && insuring) hintText = "기본 전략: 인슈어런스는 걸지 않는 것이 유리합니다";
  s.els.hint.textContent = hintText;

  if (s.ui === "betting") setStatus(s, has ? "딜을 누르면 시작합니다" : "칩을 고르고 자리에 베팅하세요");
  else if (insuring) setStatus(s, "딜러 업카드 A · 인슈어런스를 걸까요?");
  else if (playing && view.active) {
    const st = view.seats.find((x) => x.index === view.active.seat);
    const h = st.hands[view.active.hand];
    const multi = st.hands.length > 1 ? ` ${view.active.hand + 1}번째 손` : "";
    setStatus(s, `${view.active.seat + 1}번 자리${multi} · ${totalText(h.total, h.soft)}`);
  }
}

function renderInsurance(s, show) {
  const box = s.els.insbox;
  box.classList.toggle("show", show);
  if (!show) {
    box.innerHTML = "";
    return;
  }
  const cost = s.data.view.insurance_cost || {};
  box.innerHTML = "";
  Object.entries(cost).forEach(([seat, amount]) => {
    const row = document.createElement("div");
    row.className = "seat-ins";
    const on = !!s.insurance[seat];
    row.innerHTML = `<span>${+seat + 1}번 자리 (${fmt(amount)})</span>`;
    const yes = document.createElement("button");
    yes.textContent = "건다";
    yes.classList.toggle("on", on);
    yes.onclick = () => { s.insurance[seat] = true; renderInsurance(s, true); };
    const no = document.createElement("button");
    no.textContent = "안 건다";
    no.classList.toggle("on", !on);
    no.onclick = () => { s.insurance[seat] = false; renderInsurance(s, true); };
    row.append(yes, no);
    box.appendChild(row);
  });
  const ok = document.createElement("button");
  ok.className = "primary";
  ok.textContent = "확인";
  ok.onclick = () => sendInsurance(s);
  box.appendChild(ok);
}

function renderCount(s) {
  const c = s.data.view.count;
  if (!s.data.show_count || !c) {
    s.els.count.textContent = "";
    return;
  }
  const sign = (n) => (n > 0 ? `+${n}` : `${n}`);
  s.els.count.innerHTML = `러닝 <b>${sign(c.rc)}</b> · 트루 <b>${sign(c.tc)}</b> · 남은 덱 ${c.decks_left}`;
}

// ── 칩 트레이 ───────────────────────────────────────────────────────
function buildChipTray(s) {
  const tray = s.els.chiptray;
  if (!tray.childElementCount) {
    s.data.chips.forEach((v) => {
      const chip = makeChip(v, short(v));
      chip.dataset.v = v;
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
