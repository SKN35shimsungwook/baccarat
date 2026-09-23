// 바카라 테이블 화면 (Streamlit Custom Component v2)
// - 파이썬이 보낸 data로 화면을 그리고, 베팅이 끝나면 setTriggerValue("deal", ...)로 알린다.
// - 승패는 파이썬이 이미 정해서 보내므로, 여기서는 카드 분배/스퀴즈/정산 연출만 한다.

const STATE = new WeakMap();
const MAIN_BETS = ["player", "banker", "tie"];
const WIN_TEXT = { P: "플레이어 승", B: "뱅커 승", T: "타이" };
const BEAD_TEXT = { P: "플", B: "뱅", T: "타" };
const DERIVED = ["big_eye", "small", "cockroach"];

const handTotal = (cards) => cards.reduce((a, c) => a + c.value, 0) % 10;

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector(".bt-root");
  if (!root || !data) return;

  loadAssets(data.asset_base);
  let s = STATE.get(parentElement);
  if (!s || s.root !== root) {
    // HTML이 다시 주입되면(컴포넌트 재등록 등) 옛 DOM 참조를 버리고 새로 묶는다.
    const prev = s;
    s = createState(root, data);
    if (prev) {
      clearInterval(prev.timerHandle);
      Object.assign(s, {
        chip: prev.chip,
        lastBets: prev.lastBets,
        lastOutcomeId: prev.lastOutcomeId,
        lastErrorId: prev.lastErrorId,
      });
    }
    STATE.set(parentElement, s);
    bind(s);
    bindKeys(s, (code) => onKey(s, code));
    showKeyHints(s);
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
  const spots = {};
  root.querySelectorAll("[data-bet]").forEach((el) => (spots[el.dataset.bet] = el));
  const actions = {};
  root.querySelectorAll("[data-act]").forEach((el) => (actions[el.dataset.act] = el));
  return {
    root, els, spots, actions,
    phase: "betting",          // betting | waiting | animating | result
    bets: {},                  // 이번 판 베팅 {bet: amount}
    placed: [],                // 되돌리기용 [[bet, amount], ...]
    lastBets: null,
    chip: data.chips.includes(10000) ? 10000 : data.chips[0],
    // 첫 마운트 때 이미 끝난 판/에러를 다시 연출하지 않도록 기억해 둔다
    lastOutcomeId: data.fresh ? null : data.outcome?.id ?? null,
    lastErrorId: data.error?.id ?? null,
    firstSync: true,
    timerSetting: null,
    countdown: 0,
    timerHandle: null,
    pendingReveal: null,
    revealAll: false,
    roadCounts: null,
  };
}

function bind(s) {
  Object.entries(s.spots).forEach(([bet, el]) => (el.onclick = () => placeChip(s, bet)));
  const a = s.actions;
  a.undo.onclick = () => {
    if (!canBet(s)) return;
    const last = s.placed.pop();
    if (!last) return;
    const [bet, amount] = last;
    s.bets[bet] -= amount;
    if (s.bets[bet] <= 0) delete s.bets[bet];
    renderBets(s);
  };
  a.clear.onclick = () => {
    if (!canBet(s)) return;
    s.bets = {};
    s.placed = [];
    renderBets(s);
  };
  a.double.onclick = () => {
    if (!canBet(s) || !sum(s.bets)) return;
    tryApply(s, Object.entries(s.bets));
  };
  a.rebet.onclick = () => {
    if (!canBet(s)) return;
    if (!s.lastBets) return toast(s, "지난 판 베팅이 없습니다.");
    tryApply(s, Object.entries(s.lastBets));
  };
  a.deal.onclick = () => deal(s);
  a.reveal.onclick = () => {
    s.revealAll = true;
    stopClips(s, 300);
    if (s.pendingReveal) s.pendingReveal();
  };
  a.newshoe.onclick = () => {
    s.els.overlay.classList.remove("show");
    clearTable(s);
    s.trigger("new_shoe", Date.now());
  };
}

// 단축키를 버튼·베팅 칸에 작게 표시한다
const ACTION_KEYS = { undo: "Z", clear: "C", double: "X", rebet: "R", deal: "Space", reveal: "Space" };
const SPOT_KEYS = { player: "P", banker: "B", tie: "T" };

function showKeyHints(s) {
  Object.entries(ACTION_KEYS).forEach(([act, k]) => s.actions[act]?.insertAdjacentHTML("beforeend", ` <kbd>${k}</kbd>`));
  Object.entries(SPOT_KEYS).forEach(([bet, k]) => s.spots[bet].insertAdjacentHTML("beforeend", `<kbd class="spot-key">${k}</kbd>`));
}

function onKey(s, code) {
  if (chipFromKey(s, code)) return true;
  const click = (btn) => (btn.click(), true); // 비활성 버튼은 click()이 무시된다
  switch (code) {
    case "KeyP": placeChip(s, "player"); return true;
    case "KeyB": placeChip(s, "banker"); return true;
    case "KeyT": placeChip(s, "tie"); return true;
    case "Space":
    case "Enter":
      if (s.phase === "animating") return click(s.actions.reveal);
      deal(s);
      return true;
    case "KeyZ":
    case "Backspace": return click(s.actions.undo);
    case "KeyR": return click(s.actions.rebet);
    case "KeyX": return click(s.actions.double);
    case "KeyC": return click(s.actions.clear);
  }
  return false;
}

function canBet(s) {
  if (s.phase === "waiting" || s.phase === "animating") return false;
  if (s.data.phase === "shoe_end") return false;
  if (s.phase === "result") {
    clearTable(s);
    s.phase = "betting";
    renderStatus(s);
  }
  return true;
}

// 베팅 한 건 추가 전 검사. 문제가 있으면 메시지, 없으면 null
function checkAdd(s, bets, bet, amount) {
  const r = s.data.rules;
  const other = bet === "player" ? "banker" : bet === "banker" ? "player" : null;
  if (other && bets[other]) return "플레이어와 뱅커에 동시에 걸 수 없습니다.";
  const limit = MAIN_BETS.includes(bet) ? r.max : r.side_max;
  if ((bets[bet] || 0) + amount > limit) return `최대 베팅은 ${fmt(limit)}입니다.`;
  if (sum(bets) + amount > s.data.balance) return "칩이 부족합니다.";
  return null;
}

function placeChip(s, bet) {
  if (!canBet(s)) return;
  const err = checkAdd(s, s.bets, bet, s.chip);
  if (err) return toast(s, err);
  s.bets[bet] = (s.bets[bet] || 0) + s.chip;
  s.placed.push([bet, s.chip]);
  renderBets(s);
}

// 2배/재베팅: 전부 가능할 때만 한꺼번에 반영
function tryApply(s, entries) {
  const next = { ...s.bets };
  for (const [bet, amount] of entries) {
    const err = checkAdd(s, next, bet, amount);
    if (err) return toast(s, err);
    next[bet] = (next[bet] || 0) + amount;
  }
  entries.forEach(([bet, amount]) => s.placed.push([bet, amount]));
  s.bets = next;
  renderBets(s);
}

function deal(s) {
  if (s.phase === "waiting" || s.phase === "animating") return;
  if (s.data.phase === "shoe_end") return;
  if (!sum(s.bets)) return toast(s, "먼저 베팅하세요.");
  s.phase = "waiting";
  renderStatus(s, "베팅 마감 · 카드 분배 준비 중");
  updateButtons(s);
  s.trigger("deal", { bets: { ...s.bets }, nonce: Date.now() });
}

// ── 파이썬 → 화면 동기화 ────────────────────────────────────────────
function sync(s) {
  const d = s.data;
  buildChipTray(s);
  renderPayouts(s);

  if (d.error && d.error.id !== s.lastErrorId) {
    s.lastErrorId = d.error.id;
    toast(s, d.error.msg);
    if (s.phase === "waiting") s.phase = "betting";
  }

  if (d.fresh && d.outcome && d.outcome.id !== s.lastOutcomeId) {
    s.lastOutcomeId = d.outcome.id;
    animate(s, d.outcome, d.roads_prev || d.roads);
    return;
  }
  if (s.phase === "animating") return; // 연출이 끝나면 최신 data로 다시 그린다

  if (s.firstSync && d.outcome) showFinalHands(s, d.outcome);
  if (!d.outcome && s.phase !== "waiting") clearTable(s); // 새 슈 등으로 결과가 사라진 경우
  s.firstSync = false;

  renderRoads(s, d.roads, false);
  renderStats(s, d.stats);
  renderBets(s);
  s.els.overlay.classList.toggle("show", d.phase === "shoe_end");
  ensureTimer(s);
}

// ── 연출 ────────────────────────────────────────────────────────────
async function animate(s, o, roadsPrev) {
  s.phase = "animating";
  s.revealAll = false;
  updateButtons(s);
  s.firstSync = false;

  const res = o.result;
  s.lastBets = { ...o.bets };
  s.bets = { ...o.bets };
  s.placed = [];
  renderSpotStacks(s, s.bets);
  setBalance(s, o.balance_after - o.total_returned, o.total_stake);
  renderRoads(s, roadsPrev, false);
  clearTable(s, true);

  const dealerMode = !s.data.squeeze;
  const P = res.player, B = res.banker;
  const els = { P: [], B: [] };
  renderStatus(s, "카드 분배 중");
  const dealClip = playClip(s, "deal");
  for (const [side, i] of [["P", 0], ["B", 0], ["P", 1], ["B", 1]]) {
    els[side][i] = addCard(s, side, side === "P" ? P[i] : B[i], false);
    await sleep(260);
  }
  if (dealerMode) await dealClip;

  const shown = { P: [], B: [] };
  const revealOne = async (side, i, label, dramatic = i > 0) => {
    renderStatus(s, label);
    // 딜러 모드: 첫 장은 바로 뒤집고, 둘째 장·3번째 카드는 천천히 젖힌다
    await reveal(s, els[side][i], dramatic);
    shown[side].push((side === "P" ? P : B)[i]);
    setScore(s, side, handTotal(shown[side]));
    await sleep(180);
  };
  const who = dealerMode ? "딜러 공개" : "스퀴즈";
  s.actions.reveal.classList.add("show");

  // 딜러가 플레이어 쪽(왼쪽)으로 손을 뻗는 동안 플레이어 카드, 뱅커 쪽(오른쪽)일 때 뱅커 카드
  for (const side of ["P", "B"]) {
    const name = side === "P" ? "플레이어" : "뱅커";
    const clip = dealerMode ? playClip(s, side === "P" ? "player" : "banker", { rate: 0.8 }) : null;
    await revealOne(side, 0, `${who} · ${name} 카드`);
    await revealOne(side, 1, `${who} · ${name} 카드`);
    await clip;
    renderStatus(s, `${name} ${handTotal(shown[side])}`);
    await sleep(s.revealAll ? 150 : 450);
  }

  if (res.natural) {
    renderStatus(s, "내추럴!");
    await sleep(500);
  }
  // 3번째 카드: 딜러가 카드를 들어 보인다. 추적 데이터가 있으면 딜러 손에 실제 카드가 보인다.
  for (const side of ["P", "B"]) {
    const hand = side === "P" ? P : B;
    if (hand.length < 3) continue;
    const name = side === "P" ? "플레이어" : "뱅커";
    renderStatus(s, `${name} 3번째 카드`);
    const tracked = dealerMode && s.data.clips && s.data.clips.track && s.data.clips.track.show;
    if (tracked) {
      await playClip(s, "show", { card: hand[2] });
      els[side][2] = addCard(s, side, hand[2], true);
      await sleep(320);
      await revealOne(side, 2, `${name} 3번째 카드`, false);
    } else {
      const clip = dealerMode ? playClip(s, "show") : null;
      await sleep(350);
      els[side][2] = addCard(s, side, hand[2], true);
      await sleep(320);
      await revealOne(side, 2, `${who} · ${name} 3번째 카드`);
      await clip;
    }
  }

  finishRound(s, o);
}

function finishRound(s, o) {
  stopClips(s);
  const res = o.result;
  const w = res.winner;
  const banner = s.els.banner;
  banner.className = `bt-banner show ${w}`;
  banner.textContent = `${WIN_TEXT[w]}  ${res.player_total} : ${res.banker_total}`;
  s.root.querySelector(".bt-hand.player").classList.toggle("win", w === "P");
  s.root.querySelector(".bt-hand.banker").classList.toggle("win", w === "B");
  renderSpotResults(s, o);

  // 최신 data(연출 도중 다시 실행됐을 수 있음)로 잔액·출목표·통계를 갱신
  const d = s.data;
  setBalance(s, d.balance, 0);
  renderRoads(s, d.roads, true);
  renderStats(s, d.stats);
  s.els.hint.textContent = "";
  s.actions.reveal.classList.remove("show");

  renderStatus(s, o.net > 0 ? `${WIN_TEXT[w]} · ${signed(o.net)} 획득` : o.net < 0 ? `${WIN_TEXT[w]} · ${signed(o.net)}` : `${WIN_TEXT[w]} · 본전`);
  s.bets = {};
  s.placed = [];
  s.phase = "result";
  updateButtons(s);
  s.els.overlay.classList.toggle("show", d.phase === "shoe_end");
  s.countdown = d.timer;
  ensureTimer(s);
}

function addCard(s, side, card, third) {
  const el = document.createElement("div");
  el.className = `bt-card${third ? " third" : ""}`;
  const base = s.data.asset_base;
  const name = `${card.rank}${SUIT[card.suit]}`;
  el.innerHTML =
    `<div class="face"><img src="${base}cards/${card.rank}${card.suit}.webp" alt="${name}"></div>` +
    `<div class="back"><img src="${base}cards/back.webp" alt=""></div>`;
  if (!s.data.squeeze) el.classList.add("from-dealer");
  (side === "P" ? s.els.pcards : s.els.bcards).appendChild(el);
  return el;
}

function flip(el) {
  el.classList.add("flip");
  setTimeout(() => el.classList.add("revealed"), 400);
}

// 한 장 공개. 스퀴즈 모드면 사용자가 드래그해서 젖힐 때까지 기다린다.
function reveal(s, el, dramatic = false) {
  if (s.revealAll) {
    flip(el);
    return sleep(420);
  }
  if (!s.data.squeeze) return dealerReveal(s, el, dramatic);
  return new Promise((resolve) => {
    el.classList.add("active");
    s.els.hint.textContent = "카드를 드래그해서 젖히세요 · 두 번 누르면 바로 공개";
    s.actions.reveal.classList.add("show");
    const done = (instant) => {
      if (s.pendingReveal !== finish) return;
      s.pendingReveal = null;
      el.classList.remove("active");
      el.onpointerdown = el.ondblclick = null;
      s.els.hint.textContent = "";
      if (instant) flip(el);
      else el.classList.add("revealed");
      setTimeout(resolve, instant ? 420 : 250);
    };
    const finish = () => done(true);
    s.pendingReveal = finish;
    attachSqueeze(el, () => done(false));
    el.ondblclick = finish;
  });
}

// 딜러 모드: 평범한 카드는 뒤집고, 결정적인 카드는 조금 젖혔다 멈춘 뒤 끝까지 연다.
// "모두 공개"를 누르면 남은 동작을 건너뛴다.
async function dealerReveal(s, el, dramatic) {
  if (!dramatic) {
    flip(el);
    return sleep(460);
  }
  const back = el.querySelector(".back");
  // 90° 돌린 3번째 카드는 카드 기준 오른쪽이 화면 아래쪽
  const partial = el.classList.contains("third") ? "inset(0% 32% 0% 0%)" : "inset(0% 0% 32% 0%)";
  el.classList.add("peel");
  back.style.clipPath = "inset(0% 0% 0% 0%)";
  await sleep(60);
  back.style.clipPath = partial;
  for (let t = 0; t < 9 && !s.revealAll; t++) await sleep(100);
  el.classList.add("revealed");
  await sleep(s.revealAll ? 200 : 650);
}

// 드래그 방향에 따라 카드 뒷면을 잘라내서 앞면이 조금씩 보이게 한다.
function attachSqueeze(el, onDone) {
  const back = el.querySelector(".back");
  const rotated = el.classList.contains("third");
  // 90° 돌린 카드는 화면 기준 방향과 카드 기준 방향이 다르다
  const ROT = { bottom: "right", top: "left", left: "bottom", right: "top" };
  el.onpointerdown = (e) => {
    e.preventDefault();
    el.setPointerCapture(e.pointerId);
    back.classList.add("dragging");
    const x0 = e.clientX, y0 = e.clientY;
    const rect = el.getBoundingClientRect();
    let p = 0;
    el.onpointermove = (ev) => {
      const dx = ev.clientX - x0, dy = ev.clientY - y0;
      let side, dist, size;
      if (Math.abs(dy) >= Math.abs(dx)) {
        side = dy < 0 ? "bottom" : "top"; dist = Math.abs(dy); size = rect.height;
      } else {
        side = dx < 0 ? "right" : "left"; dist = Math.abs(dx); size = rect.width;
      }
      if (rotated) side = ROT[side];
      p = Math.min(1, dist / (size * 0.9));
      const inset = { top: 0, right: 0, bottom: 0, left: 0 };
      inset[side] = (p * 100).toFixed(1);
      back.style.clipPath = `inset(${inset.top}% ${inset.right}% ${inset.bottom}% ${inset.left}%)`;
    };
    el.onpointerup = el.onpointercancel = () => {
      el.onpointermove = el.onpointerup = el.onpointercancel = null;
      back.classList.remove("dragging");
      if (p > 0.55) {
        back.style.clipPath = back.style.clipPath.replace(/[\d.]+%/g, (v) => (parseFloat(v) > 0 ? "100%" : v));
        onDone();
      } else {
        back.style.clipPath = "inset(0% 0% 0% 0%)";
      }
    };
  };
}

function showFinalHands(s, o) {
  clearTable(s, true);
  o.result.player.forEach((c, i) => addCard(s, "P", c, i === 2).classList.add("revealed"));
  o.result.banker.forEach((c, i) => addCard(s, "B", c, i === 2).classList.add("revealed"));
  setScore(s, "P", o.result.player_total);
  setScore(s, "B", o.result.banker_total);
  s.root.querySelectorAll(".bt-card").forEach((c) => (c.style.animation = "none"));
}

function clearTable(s, keepStacks = false) {
  s.els.pcards.innerHTML = "";
  s.els.bcards.innerHTML = "";
  s.els.banner.className = "bt-banner";
  s.els.hint.textContent = "";
  ["P", "B"].forEach((side) => setScore(s, side, null));
  s.root.querySelectorAll(".bt-hand").forEach((h) => h.classList.remove("win"));
  Object.values(s.spots).forEach((el) => {
    el.classList.remove("won", "lost");
    el.querySelector(".net")?.remove();
    if (!keepStacks) el.querySelector(".stack")?.remove();
  });
}

function setScore(s, side, value) {
  const el = side === "P" ? s.els.pscore : s.els.bscore;
  el.textContent = value ?? "";
  el.classList.toggle("show", value !== null && value !== undefined);
}

// ── 렌더링 ──────────────────────────────────────────────────────────
function buildChipTray(s) {
  const tray = s.els.chiptray;
  if (!tray.childElementCount) {
    s.data.chips.forEach((v) => {
      const chip = makeChip(v, short(v));
      chip.dataset.v = v;
      chip.dataset.key = tray.childElementCount + 1; // 숫자 키 표시
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
  const free = s.data.balance - sum(s.bets);
  s.els.chiptray.querySelectorAll(".bt-chip").forEach((c) => {
    const v = Number(c.dataset.v);
    c.classList.toggle("sel", v === s.chip);
    c.classList.toggle("off", v > free);
  });
}

function renderPayouts(s) {
  const r = s.data.rules;
  const pay = {
    player: "1:1",
    banker: r.no_commission ? "1:1 · 6점 승 0.5:1" : "0.95:1",
    tie: `${r.tie}:1`,
    player_pair: `${r.pair}:1`,
    banker_pair: `${r.pair}:1`,
    tiger: `B 6점 승 ${r.tiger2}:1 / 3장 ${r.tiger3}:1`,
  };
  Object.entries(pay).forEach(([bet, text]) => (s.spots[bet].querySelector(".pay").textContent = text));
  s.root.querySelector(".bt-rule").textContent = r.no_commission
    ? `NO COMMISSION · BANKER 6 PAYS 1 TO 2 · TIE PAYS ${r.tie} TO 1`
    : `BANKER PAYS 0.95 TO 1 · TIE PAYS ${r.tie} TO 1`;
}

function renderBets(s) {
  if (s.phase === "animating") return;
  if (s.phase === "result") {
    // 결과 화면(칩 스택, 순이익 표시)은 다음 베팅을 시작할 때까지 유지
    setBalance(s, s.data.balance, 0);
    updateChipTray(s);
    updateButtons(s);
    return;
  }
  renderSpotStacks(s, s.bets);
  const total = sum(s.bets);
  setBalance(s, s.data.balance - total, total);
  updateChipTray(s);
  updateButtons(s);
  renderStatus(s);
}

function renderSpotStacks(s, bets) {
  Object.entries(s.spots).forEach(([bet, el]) => {
    el.querySelector(".stack")?.remove();
    if (bets[bet]) {
      const chip = makeChip(bets[bet], short(bets[bet]), true);
      chip.classList.add("stack");
      el.appendChild(chip);
    }
  });
}

function renderSpotResults(s, o) {
  const res = o.result;
  const winning = new Set();
  if (res.winner === "P") winning.add("player");
  if (res.winner === "B") winning.add("banker");
  if (res.winner === "T") winning.add("tie");
  if (res.player_pair) winning.add("player_pair");
  if (res.banker_pair) winning.add("banker_pair");
  if (res.winner === "B" && res.banker_total === 6) winning.add("tiger");
  Object.entries(s.spots).forEach(([bet, el]) => el.classList.toggle("won", winning.has(bet)));

  o.settlements.forEach((st) => {
    const el = s.spots[st.bet];
    const net = document.createElement("span");
    if (st.outcome === "push") {
      net.className = "net push";
      net.textContent = "환불";
    } else {
      net.className = `net ${st.net > 0 ? "plus" : "minus"}`;
      net.textContent = signed(st.net);
      if (st.outcome === "lose") el.classList.add("lost");
    }
    el.appendChild(net);
  });
}

function setBalance(s, shown, totalBet) {
  s.els.balance.textContent = fmt(shown);
  s.els.totalbet.textContent = fmt(totalBet);
  const profit = shown + totalBet - s.data.start_chips;
  s.els.profit.textContent = signed(profit);
  s.els.profit.className = profit > 0 ? "up" : profit < 0 ? "down" : "";
}

function renderStatus(s, text) {
  const el = s.els.status;
  el.classList.remove("urgent");
  if (text) {
    el.textContent = text;
    return;
  }
  if (s.data.phase === "shoe_end") el.textContent = "슈 종료";
  else if (s.data.timer && s.countdown > 0) {
    el.textContent = `베팅 마감까지 ${s.countdown}초`;
    el.classList.toggle("urgent", s.countdown <= 5);
  } else if (s.phase === "result") return; // 결과 문구 유지
  else el.textContent = sum(s.bets) ? "딜을 누르면 시작합니다" : "칩을 고르고 베팅 구역을 누르세요";
}

function updateButtons(s) {
  const busy = s.phase === "waiting" || s.phase === "animating" || s.data.phase === "shoe_end";
  const has = sum(s.bets) > 0;
  const a = s.actions;
  a.undo.disabled = busy || !s.placed.length;
  a.clear.disabled = busy || !has;
  a.double.disabled = busy || !has;
  a.rebet.disabled = busy || !s.lastBets || has;
  a.deal.disabled = busy || !has;
}

function renderStats(s, st) {
  const c = st.counts;
  const n = st.rounds || 1;
  const pct = (k) => `${Math.round((c[k] / n) * 100)}%`;
  s.els.stats.innerHTML =
    `<span><i class="dot" style="background:var(--banker)"></i>뱅커 ${c.B} (${st.rounds ? pct("B") : "-"})</span>` +
    `<span><i class="dot" style="background:var(--player)"></i>플레이어 ${c.P} (${st.rounds ? pct("P") : "-"})</span>` +
    `<span><i class="dot" style="background:var(--tie)"></i>타이 ${c.T}</span>` +
    `<span>B페어 ${st.banker_pairs} · P페어 ${st.player_pairs}</span>` +
    `<span>#${st.rounds}판 · 남은 카드 ${st.cards_remaining}장 · ${st.shoe_no}번째 슈</span>`;
}

function renderRoads(s, roads, blink) {
  const prev = s.roadCounts || {};
  const counts = {};
  const cell = (col, row, cls) => {
    const el = document.createElement("div");
    el.className = `c ${cls}`;
    el.style.gridColumn = col + 1;
    el.style.gridRow = row + 1;
    return el;
  };
  const fill = (name, items, make) => {
    const box = s.els[name];
    box.innerHTML = "";
    items.forEach((it) => box.appendChild(make(it)));
    counts[name] = items.length;
    if (blink && items.length > (prev[name] || 0) && box.lastElementChild) {
      box.lastElementChild.classList.add("fresh");
    }
    box.scrollLeft = box.scrollWidth;
  };
  const dots = (el, it) => {
    if (it.banker_pair) el.insertAdjacentHTML("beforeend", '<i class="bp"></i>');
    if (it.player_pair) el.insertAdjacentHTML("beforeend", '<i class="pp"></i>');
  };

  fill("bead", roads.bead, (it) => {
    const el = cell(it.col, it.row, it.winner);
    el.textContent = BEAD_TEXT[it.winner];
    dots(el, it);
    return el;
  });
  fill("big", roads.big, (it) => {
    const el = cell(it.col, it.row, it.winner);
    if (it.ties) el.insertAdjacentHTML("beforeend", `<span class="ties">${it.ties > 1 ? it.ties : ""}</span>`);
    dots(el, it);
    return el;
  });
  DERIVED.forEach((name) => fill(name, roads[name], (it) => cell(it.col, it.row, `${name} ${it.color}`)));
  s.roadCounts = counts;

  const icon = (name, color) => (color ? `<span class="c ${name} ${color}"></span>` : '<span class="none">-</span>');
  s.els.ask.innerHTML = ["B", "P"]
    .map((side) => {
      const pr = roads.predict[side] || {};
      return (
        `<div class="ask ${side}" title="다음 판이 ${side === "B" ? "뱅커" : "플레이어"}라면 찍힐 표시">` +
        `<span class="who">${side === "B" ? "뱅" : "플"}</span>` +
        DERIVED.map((n) => icon(n, pr[n])).join("") +
        `</div>`
      );
    })
    .join("");
}

// ── 타이머 ──────────────────────────────────────────────────────────
function ensureTimer(s) {
  const setting = s.data.timer || 0;
  if (setting !== s.timerSetting) {
    s.timerSetting = setting;
    clearInterval(s.timerHandle);
    s.timerHandle = null;
    s.countdown = setting;
  }
  if (!setting || s.timerHandle) {
    renderStatus(s);
    return;
  }
  s.timerHandle = setInterval(() => {
    if (!s.root.isConnected) return clearInterval(s.timerHandle);
    if (s.phase !== "betting" && s.phase !== "result") return;
    if (s.data.phase === "shoe_end") return;
    s.countdown -= 1;
    if (s.countdown <= 0) {
      s.countdown = s.data.timer;
      if (sum(s.bets)) return deal(s);
    }
    renderStatus(s);
  }, 1000);
  renderStatus(s);
}
