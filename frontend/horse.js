// 경마 화면 (Streamlit Custom Component v2). common.js 뒤에 이어 붙는다.
// - 파이썬(horse/game.py)이 출전표·순위·경주 대본을 정한다. 결과는 베팅이 확정된 뒤에 서버에서 계산된다.
// - JS → 파이썬: setTriggerValue("play", {bets: {레인: 금액}})
// - 화면은 저해상도 캔버스(높이 IH 픽셀)에 도트로 그린 뒤 픽셀 그대로 확대한다.
//   말·기수 스프라이트, 흙 트랙, 난간, 게이트, 결승선, 거리 표시, 관중을 모두 코드로 그린다.

const STATE = new WeakMap();
const LANES = 6;
const LANE_KEYS = ["KeyQ", "KeyW", "KeyE", "KeyA", "KeyS", "KeyD"];
// 안장천 색 (번호별 표준 색) [천, 숫자]
const LANE_COLOR = {
  1: ["#d32f2f", "#ffffff"], 2: ["#f5f5f5", "#222222"], 3: ["#1e5bd8", "#ffffff"],
  4: ["#f4c20d", "#222222"], 5: ["#2e8b3a", "#ffffff"], 6: ["#222222", "#f4c20d"],
};
const HR_FONT = "https://fonts.googleapis.com/css2?family=Do+Hyeon&family=Black+Han+Sans&display=swap";

// 연출 시간표 (초)
const GATE_S = 1.6;          // 게이트에서 대기 → 출발
const RESULT_AFTER_WIN = 1.3; // 1등 골인 후 결과판까지
const HOLD_MS = 3000;         // 결과판을 띄운 채 멈춰 있는 시간 → 그 뒤 다음 경주로

// 저해상도 화면 배치 (픽셀)
const IH = 180;
const RAIL_TOP = 12, TRACK_TOP = 16, TRACK_BOT = 148, RAIL_BOT = 152;
const LANE_H = (TRACK_BOT - TRACK_TOP) / LANES;
const GATE_X = 44, LEN = 2000, FINISH_X = GATE_X + LEN;   // 100m = 200px → 1000m 경주
const SPR_W = 38, SPR_H = 27, NOSE = 35;

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
    // JS가 새로 불러와지면(개발 중 파일 수정 등) 이전 버전의 그리기 루프를 멈춘다
    const old = window.__horseState;
    if (old && old !== s) old.alive = false;
    window.__horseState = s;
    STATE.set(parentElement, s);
    loadFont();
    bind(s);
    bindKeys(s, (code) => onKey(s, code));
    requestAnimationFrame((t) => frame(s, t));
  }
  s.data = data;
  s.trigger = setTriggerValue;
  sync(s);
}

function loadFont() {
  if (document.querySelector(`link[href="${HR_FONT}"]`)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = HR_FONT;
  document.head.appendChild(link);
}

// ── 상태 ────────────────────────────────────────────────────────────
function createState(root, data) {
  const els = {};
  root.querySelectorAll("[data-el]").forEach((el) => (els[el.dataset.el] = el));
  const actions = {};
  root.querySelectorAll("[data-act]").forEach((el) => (actions[el.dataset.act] = el));
  return {
    root, els, actions, alive: true,
    bets: {}, placed: [], lastBets: null, pendingBets: null,
    chip: data.chips.includes(10000) ? 10000 : data.chips[0],
    sending: false,
    shownRace: data.view.last ? data.view.last.race_no : null,  // 첫 마운트 때는 지난 경주를 연출하지 않는다
    anim: null,            // {race, my, t0, shown, events}
    scene: "gate",         // "gate": 다음 출전마가 게이트에 / "race": 방금 경주 (결과판 포함)
    lastErrorId: data.error ? data.error.id : null,
    buf: document.createElement("canvas"),
    sprites: new Map(),
    cardKey: null,
  };
}

const betTotal = (bets) => Object.values(bets).reduce((a, b) => a + b, 0);
const animating = (s) => !!(s.anim && !s.anim.shown);
const holding = (s) => performance.now() < (s.holdUntil || 0);   // 결과를 보여 주며 멈춘 3초
const busy = (s) => s.sending || animating(s) || holding(s);
const num = (lane) => `<span class="hr-num l${lane}">${lane}</span>`;
const tierBadge = (h) => `<span class="tier ${h.tier}">${h.tier_name}</span>`;

// 지금 베팅판에 보여 줄 출전표: 경주 중이면 달리는 말, 아니면 다음 경주
function cardLineup(s) {
  if (s.anim && (animating(s) || holding(s))) return s.anim.race.lineup;
  if (s.sending) return s.sendLineup || s.data.view.lineup;
  return s.data.view.lineup;
}

// ── 조작 ────────────────────────────────────────────────────────────
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
    if (new Set([...Object.keys(s.bets), ...Object.keys(add)]).size >= LANES) return toast(s, "6마리 모두에 거는 양방 베팅은 할 수 없습니다.");
    Object.entries(add).forEach(([k, v]) => {
      s.bets[k] = (s.bets[k] || 0) + v;
      s.placed.push([k, v]);
    });
    toGate(s);
    render(s);
  };
  a.start.onclick = () => play(s);
  s.els.result.onclick = () => {
    toGate(s);
    render(s);
  };
}

// 결과판을 닫고 다음 출전마를 게이트에 세운다
function toGate(s) {
  if (animating(s) || holding(s)) return;
  s.scene = "gate";
  s.els.result.classList.remove("show");
  s.els.hud.innerHTML = "";
  if (!s.sending) setCaster(s, "출전표를 보고 칩을 놓은 뒤 출발을 눌러 주세요.");
}

function placeChip(s, lane) {
  if (busy(s)) return;
  const key = String(lane);
  if (betTotal(s.bets) + s.chip > s.data.balance) return toast(s, "칩이 부족합니다.");
  if (!s.bets[key] && Object.keys(s.bets).length >= LANES - 1) return toast(s, "6마리 모두에 거는 양방 베팅은 할 수 없습니다.");
  if ((s.bets[key] || 0) + s.chip > s.data.rules.max) return toast(s, `한 마리에 최대 ${fmt(s.data.rules.max)}까지 걸 수 있습니다.`);
  s.bets[key] = (s.bets[key] || 0) + s.chip;
  s.placed.push([key, s.chip]);
  toGate(s);
  render(s);
}

// 칩이 없으면 지난 베팅 그대로 출발
function play(s) {
  if (busy(s)) return;
  let bets = s.bets;
  if (!betTotal(bets)) {
    if (!s.lastBets) return toast(s, "출전표에서 말을 눌러 칩을 놓아 주세요.");
    if (betTotal(s.lastBets) > s.data.balance) return toast(s, "칩이 부족합니다.");
    bets = { ...s.lastBets };
  }
  toGate(s);
  s.sending = true;
  s.sendLineup = s.data.view.lineup;
  s.lastBets = { ...bets };
  s.pendingBets = { ...bets };
  s.trigger("play", { bets: { ...bets }, nonce: Date.now() });
  s.bets = {};
  s.placed = [];
  setCaster(s, "각 말이 게이트에 들어갑니다…");
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
  const lane = LANE_KEYS.indexOf(code);
  if (lane >= 0) {
    placeChip(s, lane + 1);
    return true;
  }
  const click = (btn) => (btn.click(), true);
  switch (code) {
    case "Space":
    case "Enter": play(s); return true;
    case "KeyZ":
    case "Backspace": return click(s.actions.undo);
    case "KeyC": return click(s.actions.clear);
    case "KeyR": return click(s.actions.rebet);
    case "Escape": toGate(s); render(s); return true;
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
      s.sending = false;
      s.bets = s.pendingBets || {};
      s.placed = Object.entries(s.bets);
      s.pendingBets = null;
      setCaster(s, "출전표를 보고 칩을 놓은 뒤 출발을 눌러 주세요.");
    }
  }
  if (v.last && v.last.race_no !== s.shownRace) {
    // 새 경주 결과: 연출 시작
    s.shownRace = v.last.race_no;
    s.sending = false;
    clearTimeout(s.sendGuard);
    const my = d.my_last && d.my_last.race_no === v.last.race_no ? d.my_last : null;
    const race = v.last;
    const winT = race.script.finish[race.winner - 1];
    const anim = { race, my, t0: performance.now(), shown: false, ev: { leader: null, lastLine: -9, said: {} } };
    s.anim = anim;
    s.scene = "race";
    s.els.result.classList.remove("show");
    // 창이 가려져 그리기가 멈춰도 결과는 보여 준다
    setTimeout(() => finishRace(s, anim), (GATE_S + winT + RESULT_AFTER_WIN) * 1000 + 200);
  } else if (!s.anim && !s.sending) {
    setCaster(s, "출전표를 보고 칩을 놓은 뒤 출발을 눌러 주세요.");
  }
  render(s);
  if (!animating(s)) renderAfterResult(s);
  renderFair(s);
}

function renderAfterResult(s) {
  renderMine(s, s.data.my);
  renderRecent(s, s.data.view);
  renderTipster(s, s.data.view);
}

// 팁스터: 지난 경주 기록으로 본 출전마별 RTP (그 말에 매번 같은 금액을 걸었다면 돌려받은 비율)
function renderTipster(s, v) {
  const tip = v.tipster;
  const pct = (r) => (r.rtp === null ? "-" : `${r.rtp}%`);
  const cls = (r) => (r.rtp === null ? "" : r.rtp >= 100 ? "hi" : r.rtp < 60 ? "lo" : "");
  const pick = tip.pick ? v.lineup[tip.pick - 1] : null;
  s.els.choice.innerHTML =
    `<div class="title">팁스터 추천</div>` +
    (pick
      ? `<div class="row">${num(pick.lane)}<span class="nm">${pick.name}</span><span class="pct ${cls(tip.lineup[pick.lane])}">${pct(tip.lineup[pick.lane])}</span></div>`
      : `<div class="row"><span class="nm">기록이 쌓이면 추천합니다</span></div>`) +
    `<div class="cap">지난 경주 ${tip.n}회의 RTP 기준</div>`;
  s.els.tipster.innerHTML =
    v.lineup.map((h) => {
      const r = tip.lineup[h.lane];
      const title = r.starts ? `${r.starts}전 ${r.wins}승 · 3위 안 ${r.top3}회 · 평균 ${r.avg}위` : "지난 기록 없음";
      return `<div class="row${tip.pick === h.lane ? " pick" : ""}" title="${title}">${num(h.lane)}<span class="nm">${h.name}</span>` +
        `<span class="pct ${cls(r)}">${pct(r)}</span></div>`;
    }).join("") +
    `<div class="cap">지난 레이스 ${Math.max(tip.n, 0)}회의 RTP · 참고용 (미래를 보장하지 않음)</div>`;
  s.els.top.innerHTML = tip.top.length
    ? tip.top.map((h, i) => `<span class="t"><span>${i + 1}. ${h.name}</span><span><b>${h.wins}승</b> / ${h.starts}전 · RTP ${h.rtp}%</span></span>`).join("")
    : `<span class="empty">아직 기록이 없습니다</span>`;
}

function finishRace(s, anim) {
  if (s.anim !== anim || anim.shown || !s.alive) return;
  anim.shown = true;
  s.holdUntil = performance.now() + HOLD_MS;
  showResult(s);
  render(s);
  renderAfterResult(s);
  // 3초 동안 결과를 보여 준 뒤 (버튼에 남은 초를 세며) 다음 경주 출전마를 게이트에 세운다
  for (let k = 1; k <= 2; k++) setTimeout(() => s.anim === anim && render(s), k * 1000);
  setTimeout(() => {
    if (s.anim !== anim || !s.alive) return;
    s.holdUntil = 0;
    s.pendingBets = null;
    toGate(s);
    render(s);
  }, HOLD_MS);
}

function render(s) {
  const lineup = cardLineup(s);
  const isBusy = busy(s);
  const shownBets = isBusy && s.pendingBets ? s.pendingBets : s.bets;
  const key = lineup.map((h) => h.id).join(",") + (isBusy ? "b" : "");
  if (key !== s.cardKey) buildCards(s, lineup, isBusy);
  lineup.forEach((h) => {
    const card = s.cards[h.lane];
    const amount = shownBets[h.lane] || 0;
    card.classList.toggle("bet", !!amount);
    card.querySelector(".mine").textContent = amount ? `맞으면 ${fmt(Math.floor(amount * h.odds))}` : "";
    card.querySelector(".stack")?.remove();
    if (amount) {
      const chip = makeChip(amount, short(amount), true);
      chip.classList.add("stack");
      card.appendChild(chip);
    }
    card.disabled = isBusy;
  });
  const pending = betTotal(s.bets);
  const label = s.actions.start.querySelector("span");
  s.actions.start.disabled = isBusy || (!pending && !s.lastBets);
  label.textContent = holding(s) ? `다음 경주까지 ${Math.ceil((s.holdUntil - performance.now()) / 1000)}초` : isBusy ? "경주 중…" : pending ? `출발 ${fmt(pending)}` : s.lastBets ? `같은 베팅 출발 ${fmt(betTotal(s.lastBets))}` : "출발";
  s.actions.undo.disabled = isBusy || !s.placed.length;
  s.actions.clear.disabled = isBusy || !pending;
  s.actions.rebet.disabled = isBusy || !s.lastBets;

  const total = betTotal(shownBets);
  const best = Math.max(0, ...lineup.map((h) => Math.floor((shownBets[h.lane] || 0) * h.odds)));
  s.els.betinfo.innerHTML = total
    ? `<span>이번 경주 베팅 <b>${fmt(total)}</b></span><span>최대 당첨 <b class="plus">${fmt(best)}</b></span>`
    : `<span>말을 눌러 칩을 놓고 <b>출발</b> (Space) · 여러 마리에 걸 수 있어요 (6마리 전부는 불가)</span>`;

  // 연출이 끝나기 전에는 당첨금을 빼고(베팅액만 빠진) 잔액을 보여 준다
  const hidden = animating(s) && s.anim.my ? s.anim.my : null;
  const balance = s.data.balance - (hidden ? hidden.returned : 0);
  const staked = s.sending && s.pendingBets ? betTotal(s.pendingBets) : 0;
  s.els.totalbet.textContent = fmt(total);
  s.els.balance.textContent = fmt(balance - pending - staked);
  const profit = balance - s.data.start_chips;
  s.els.profit.textContent = profit > 0 ? `+${fmt(profit)}` : fmt(profit);
  s.els.profit.className = profit > 0 ? "up" : profit < 0 ? "down" : "";
  updateChipTray(s);
}

function buildCards(s, lineup, isBusy) {
  s.cardKey = lineup.map((h) => h.id).join(",") + (isBusy ? "b" : "");
  const box = s.els.cards;
  box.innerHTML = "";
  s.cards = {};
  lineup.forEach((h) => {
    const card = document.createElement("button");
    const pick = !isBusy && s.data.view.tipster.pick === h.lane;
    card.className = `hr-card${pick ? " tip" : ""}`;
    const form = h.form.map((r) => (r === 1 ? `<b>1</b>` : r)).join("-");
    card.innerHTML =
      `<span class="block l${h.lane}">${h.lane}</span>` +
      `<span class="odds">${h.odds.toFixed(2)}배 ${tierBadge(h)}</span>` +
      `<span class="name">${h.name}</span>` +
      `<span class="form">${h.style_name} · 최근 ${form}</span>` +
      `<span class="mine"></span><kbd class="spot-key">${LANE_KEYS[h.lane - 1].slice(3)}</kbd>`;
    card.title = `${h.lane}번 ${h.name} · ${h.tier_name} · ${h.style_name} · 1등 확률 약 ${(h.prob * 100).toFixed(1)}% · 통산 ${h.starts}전 ${h.wins}승`;
    card.onclick = () => placeChip(s, h.lane);
    box.appendChild(card);
    s.cards[h.lane] = card;
  });
}

// ── 결과 · 기록 ─────────────────────────────────────────────────────
// 도트 트로피 (16×16). G 테두리, Y 금색, H 반짝임, D 받침
const TROPHY = [
  "................",
  "...GGGGGGGGGG...",
  ".GGYHYYYYYYYYGG.",
  ".G.YHYYYYYYYY.G.",
  ".G.YHYYYYYYYY.G.",
  "..GYYYYYYYYYYG..",
  "...GYYYYYYYYG...",
  "....GYYYYYYG....",
  ".....GYYYYG.....",
  "......GYYG......",
  ".......YY.......",
  "......GYYG......",
  ".....DDDDDD.....",
  "....DDDDDDDD....",
  "....DDDDDDDD....",
  "................",
];
function trophySvg(lane) {
  const col = { G: "#9a6b12", Y: "#ffc83d", H: "#fff3b0", D: "#7a4a1f" };
  const rects = TROPHY.flatMap((row, y) => [...row].map((c, x) => (col[c] ? `<rect x="${x}" y="${y}" width="1" height="1" fill="${col[c]}"/>` : "")));
  const [bg, fg] = LANE_COLOR[lane];
  return `<svg class="trophy" viewBox="0 0 16 16" shape-rendering="crispEdges">${rects.join("")}` +
    `<rect x="6" y="2" width="4" height="4" fill="${bg}"/>` +
    `<text x="8" y="5.4" font-size="4" text-anchor="middle" fill="${fg}" font-family="Do Hyeon, sans-serif">${lane}</text></svg>`;
}

function showResult(s) {
  const a = s.anim;
  const r = a.race;
  const w = r.lineup[r.winner - 1];
  const my = a.my;
  const rest = r.order.slice(1).map((lane, i) => `<span>${i + 2}위 ${num(lane)}</span>`).join("");
  let youwin = "";
  if (my) {
    youwin = my.returned > 0
      ? `<div class="youwin">당첨! 받은 금액 ${fmt(my.returned)}<b class="plus">${signed(my.net)}</b></div>`
      : `<div class="youwin">아쉽네요 · 베팅 ${fmt(my.stake)}<b class="minus">${signed(my.net)}</b></div>`;
  }
  s.els.result.innerHTML =
    `<div class="panel">${trophySvg(w.lane)}<div><span class="ribbon">${w.name}</span></div>` +
    `<div class="sub">제 ${r.race_no}경주 1위 · ${w.lane}번 · ${w.tier_name} · ${w.odds.toFixed(2)}배</div>` +
    youwin + `<div class="rest">${rest}</div>` +
    `<div class="next">잠시 뒤 다음 경주로 넘어갑니다</div></div>`;
  s.els.result.classList.add("show");
  setCaster(s, `골인! 1위는 ${w.lane}번 ${w.name}! (${w.tier_name}, ${w.odds.toFixed(2)}배)`);
}

function renderMine(s, my) {
  if (!my) return;
  const cls = (n) => (n > 0 ? "plus" : n < 0 ? "minus" : "");
  s.els.mystats.innerHTML =
    `<div class="hr-panel-title">경마 누적 손익</div>` +
    `<b class="total ${cls(my.net)}">${signed(my.net)}</b>` +
    `<span class="row"><span>경주</span><b>${my.rounds}</b></span>` +
    `<span class="row"><span>적중한 경주</span><b>${my.wins}${my.rounds ? ` (${Math.round((my.wins / my.rounds) * 100)}%)` : ""}</b></span>` +
    `<span class="row"><span>총 베팅</span><b>${fmt(my.stake)}</b></span>` +
    `<span class="row"><span>총 받음</span><b>${fmt(my.returned)}</b></span>`;
  s.els.mylist.innerHTML = my.list.length
    ? `<table><thead><tr><th>경주</th><th>1위</th><th>내 베팅</th><th>베팅액</th><th>받음</th><th>손익</th></tr></thead><tbody>` +
      my.list.map((h) =>
        `<tr><td>#${h.race_no}</td><td>${num(h.winner)} ${h.result.replace(/^\d+번 /, "")}</td><td class="bets">${h.bets}</td>` +
        `<td>${fmt(h.stake)}</td><td>${fmt(h.returned)}</td><td class="${cls(h.net)}">${signed(h.net)}</td></tr>`).join("") +
      `</tbody></table>`
    : `<p class="empty">아직 건 경주가 없습니다.</p>`;
}

function renderRecent(s, v) {
  s.els.recent.innerHTML = v.recent.length
    ? v.recent.map((r) => `<span class="w" title="제 ${r.race_no}경주">${num(r.lane)}<span class="tier ${r.tier}">${r.odds.toFixed(1)}</span></span>`).join("")
    : `<span class="empty">아직 경주 기록이 없습니다</span>`;
  const t = v.tier_wins;
  const n = v.n || 1;
  s.els.tierstat.innerHTML = v.n
    ? `최근 ${v.n}경주 우승 등급: 강자 ${t.S} · 중간 ${t.A} · 복병 ${t.O}` +
      `<div class="bar"><i style="width:${(t.S / n) * 100}%;background:var(--tier-S)"></i>` +
      `<i style="width:${(t.A / n) * 100}%;background:var(--tier-A)"></i><i style="flex:1;background:var(--tier-O)"></i></div>`
    : "";
}

function renderFair(s) {
  const v = s.data.view;
  const last = v.last;
  s.els.fair.textContent = `제 ${v.race_no}경주 해시 ${v.commit.slice(0, 16)}…` +
    (last && !animating(s) ? `  ·  지난 제 ${last.race_no}경주 시드 ${last.seed.slice(0, 12)}… 공개` : "");
}

function setCaster(s, text) {
  if (s.casterText === text) return;
  s.casterText = text;
  s.els.caster.textContent = text;
}

function shout(s, text) {
  const el = s.els.shout;
  el.textContent = text;
  el.classList.remove("show");
  void el.offsetWidth;
  el.classList.add("show");
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

// ── 경주 진행 (대본 보간) · 해설 ────────────────────────────────────
function positionsAt(script, t) {
  if (t <= 0) return new Array(LANES).fill(0);
  const k = t / script.dt;
  const i = Math.floor(k);
  const f = k - i;
  return script.pos.map((row) => {
    if (i >= row.length - 1) return row[row.length - 1];
    return row[i] + (row[i + 1] - row[i]) * f;
  });
}

function rankOf(pos) {
  return pos.map((p, i) => [p, i + 1]).sort((a, b) => b[0] - a[0]).map((x) => x[1]);
}

// 경주 중 해설 · 순위 표시 · "출발!" · 골인 번쩍임
function raceEvents(s, a, e, t, pos) {
  const ev = a.ev;
  const r = a.race;
  const nameOf = (lane) => `${lane}번 ${r.lineup[lane - 1].name}`;
  const once = (key, fn) => {
    if (!ev.said[key]) {
      ev.said[key] = true;
      fn();
    }
  };
  if (e < GATE_S) {
    once("ready", () => setCaster(s, "모든 말이 게이트에 들어섰습니다. 출발 준비!"));
    return;
  }
  once("go", () => {
    shout(s, "출발!");
    setCaster(s, "출발했습니다! 6마리 모두 힘차게 게이트를 나섭니다!");
    ev.lastLine = t;
  });
  const order = rankOf(pos);
  const winT = r.script.finish[r.winner - 1];
  if (t < winT) {
    s.els.hud.innerHTML = `<span class="rk">순위</span>` + order.map((l) => num(l)).join("");
    const leader = order[0];
    if (ev.leader !== null && leader !== ev.leader && t - ev.lastLine > 1.3 && t < winT - 0.6) {
      setCaster(s, `${nameOf(leader)}, 선두로 나섭니다!`);
      ev.lastLine = t;
    }
    ev.leader = leader;
    if (t > 4 && t - ev.lastLine > 2) once("mid", () => {
      setCaster(s, `선두 ${nameOf(order[0])}, 2위 ${order[1]}번, 3위 ${order[2]}번이 바짝 쫓습니다!`);
      ev.lastLine = t;
    });
    // 추입: 1.5초 사이 두 계단 이상 올라온 말
    if (t > 7.5 && t < winT - 0.4) {
      const before = rankOf(positionsAt(r.script, t - 1.5));
      order.slice(0, 3).forEach((lane, i) => {
        if (before.indexOf(lane) - i >= 2 && t - ev.lastLine > 1.2) once(`surge${lane}`, () => {
          setCaster(s, `${nameOf(lane)}, 무서운 추입!`);
          ev.lastLine = t;
        });
      });
    }
    if (t > 9.2) once("stretch", () => {
      if (t - ev.lastLine > 0.8) setCaster(s, `마지막 직선 주로! 선두는 ${nameOf(order[0])}!`);
      ev.lastLine = t;
    });
  } else {
    once("goal", () => {
      s.els.flash.classList.remove("show");
      void s.els.flash.offsetWidth;
      s.els.flash.classList.add("show");
      shout(s, "골인!");
      const second = r.script.finish[r.order[1] - 1] - winT;
      setCaster(s, second < 0.12 ? `사진 판정 접전! 1위는 ${nameOf(r.winner)}!` : `골인! ${nameOf(r.winner)} 1위로 들어옵니다!`);
    });
    s.els.hud.innerHTML = `<span class="rk">도착</span>` +
      r.order.filter((l) => t >= r.script.finish[l - 1]).map((l) => num(l)).join("");
    if (t >= winT + RESULT_AFTER_WIN) finishRace(s, a);
  }
}

// ── 그리기 ──────────────────────────────────────────────────────────
function frame(s, now) {
  if (!s.alive || !s.root.isConnected) return;
  requestAnimationFrame((t) => frame(s, t));
  const cv = s.els.canvas;
  const W = cv.clientWidth, H = cv.clientHeight;
  if (!W || !H) return;
  const dpr = window.devicePixelRatio || 1;
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) {
    cv.width = Math.round(W * dpr);
    cv.height = Math.round(H * dpr);
  }
  const IW = Math.max(220, Math.round((IH * W) / H));
  if (s.buf.width !== IW || s.buf.height !== IH) {
    s.buf.width = IW;
    s.buf.height = IH;
  }
  const b = s.buf.getContext("2d");
  b.imageSmoothingEnabled = false;

  // 장면: 게이트 대기 또는 경주
  let lineup, pos, running = false, t = 0;
  const a = s.anim;
  if (s.scene === "race" && a) {
    lineup = a.race.lineup;
    const e = (now - a.t0) / 1000;
    t = e - GATE_S;
    pos = positionsAt(a.race.script, t);
    running = t > 0;
    if (!a.shown) raceEvents(s, a, e, t, pos);
  } else {
    lineup = s.sending && s.sendLineup ? s.sendLineup : s.data.view.lineup;
    pos = new Array(LANES).fill(0);
  }

  // 카메라: 선두를 화면 62% 지점에, 끝에서는 결승선이 보이게 멈춘다
  const lead = Math.max(...pos);
  const camMax = FINISH_X + 90 - IW;
  const camX = Math.round(Math.max(0, Math.min(camMax, GATE_X + lead * LEN - IW * 0.62)));

  drawTrack(b, camX, IW, now, running);
  for (let i = 0; i < LANES; i++) {
    const h = lineup[i];
    const noseX = GATE_X + pos[i] * LEN;
    const x = Math.round(noseX - NOSE - camX);
    const base = Math.round(TRACK_TOP + (i + 1) * LANE_H);
    const gallop = running && pos[i] > 0;
    const f = gallop ? Math.floor((pos[i] * LEN) / 7) % 4 : -1;
    if (gallop) drawDust(b, x, base, now, i);
    b.drawImage(sprite(s, h, i + 1, f), x, base - SPR_H + 1);
  }

  const ctx = cv.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(s.buf, 0, 0, IW, IH, 0, 0, cv.width, cv.height);
}

// 좌표로 정해지는 의사 난수 (스크롤해도 같은 자리에 같은 무늬)
function hash(x, y) {
  let h = (x * 374761393 + y * 668265263) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

function drawTrack(b, camX, IW, now, running) {
  // 위 잔디
  b.fillStyle = "#2f9a3a";
  b.fillRect(0, 0, IW, RAIL_TOP);
  b.fillStyle = "#267f30";
  for (let x = -((camX) % 24); x < IW; x += 24) b.fillRect(x, 0, 12, RAIL_TOP);
  // 흙 트랙
  b.fillStyle = "#c98b40";
  b.fillRect(0, TRACK_TOP - 4, IW, TRACK_BOT - TRACK_TOP + 8);
  b.fillStyle = "#b97c36";
  for (let k = 1; k < LANES; k++) {
    const y = Math.round(TRACK_TOP + k * LANE_H);
    for (let x = -(camX % 6); x < IW; x += 6) b.fillRect(x, y, 3, 1);
  }
  // 흙 알갱이
  for (let tx = Math.floor(camX / 8); tx <= Math.floor((camX + IW) / 8); tx++) {
    for (let row = 0; row < 16; row++) {
      const r = hash(tx, row);
      if (r < 0.35) {
        b.fillStyle = r < 0.12 ? "#dca25a" : "#a86d2c";
        b.fillRect(tx * 8 - camX + Math.floor(r * 40) % 8, TRACK_TOP + row * 8 + Math.floor(r * 97) % 8, 1, 1);
      }
    }
  }
  // 난간 (위·아래)
  railLine(b, camX, IW, RAIL_TOP);
  railLine(b, camX, IW, TRACK_BOT);
  // 아래 잔디 + 관중
  b.fillStyle = "#34a043";
  b.fillRect(0, RAIL_BOT, IW, IH - RAIL_BOT);
  b.fillStyle = "#2c8f3a";
  for (let x = -(camX % 32); x < IW; x += 32) b.fillRect(x, RAIL_BOT, 16, IH - RAIL_BOT);
  drawCrowd(b, camX, IW, now, running);
  // 거리 표시 (결승선까지 남은 m)
  for (let m = 0; m <= 1000; m += 100) {
    const wx = FINISH_X - m * 2;
    const x = wx - camX;
    if (x < -30 || x > IW + 30) continue;
    b.fillStyle = "#ffffff";
    b.fillRect(x, TRACK_BOT - 6, 2, 8);
    drawDigits(b, String(m), x, RAIL_BOT + 3, 2, "#ffffff", "#1a3d1f");
  }
  // 출발 게이트
  const gx = GATE_X + 2 - camX;
  if (gx > -20 && gx < IW + 20) {
    for (let k = 0; k <= LANES; k++) {
      const y = Math.round(TRACK_TOP + k * LANE_H);
      b.fillStyle = "#6b4a2e";
      b.fillRect(gx - 12, y - 1, 14, 2);
    }
    b.fillStyle = "#7a5230";
    b.fillRect(gx, TRACK_TOP - 4, 3, TRACK_BOT - TRACK_TOP + 6);
    b.fillStyle = "#9c6b3f";
    b.fillRect(gx, TRACK_TOP - 4, 1, TRACK_BOT - TRACK_TOP + 6);
  }
  // 결승선 (체크무늬) + 기둥
  const fx = FINISH_X - camX;
  if (fx > -10 && fx < IW + 10) {
    for (let y = TRACK_TOP - 4; y < TRACK_BOT + 2; y += 2) {
      for (let c = 0; c < 2; c++) {
        b.fillStyle = ((y / 2 + c) & 1) ? "#111111" : "#ffffff";
        b.fillRect(fx + c * 2, y, 2, 2);
      }
    }
    b.fillStyle = "#e0e0e0";
    b.fillRect(fx, 0, 4, RAIL_TOP);
    b.fillStyle = "#d32f2f";
    b.fillRect(fx - 3, 0, 10, 4);
  }
}

function railLine(b, camX, IW, y) {
  b.fillStyle = "#6f6f6f";
  b.fillRect(0, y + 3, IW, 1);
  b.fillStyle = "#f2f2f2";
  b.fillRect(0, y, IW, 3);
  b.fillStyle = "#cfcfcf";
  for (let x = -(camX % 16); x < IW; x += 16) b.fillRect(x, y + 3, 2, 3);
}

const SHIRTS = ["#e53935", "#1e88e5", "#fdd835", "#8e24aa", "#fb8c00", "#ffffff", "#43a047", "#f06292", "#6d4c41"];
const HAIRS = ["#2b1d14", "#5a3a1a", "#d9a856", "#1a1a1a", "#8b4a2b"];
function drawCrowd(b, camX, IW, now, running) {
  const slot = 7;
  for (let sx = Math.floor(camX / slot); sx <= Math.floor((camX + IW) / slot); sx++) {
    const wx = sx * slot;
    const nearFinish = wx > FINISH_X - 900 && wx < FINISH_X + 120;
    for (let row = 0; row < 2; row++) {
      const r = hash(sx, row + 7);
      if (r > (nearFinish ? 0.72 : 0.12)) continue;
      const x = wx - camX + (row ? 3 : 0);
      // 경주 중에는 들썩인다
      const jump = running && nearFinish && hash(sx, Math.floor(now / 180) + row) < 0.25 ? 1 : 0;
      const y = IH - 18 + row * 8 - jump;
      b.fillStyle = HAIRS[Math.floor(r * 97) % HAIRS.length];
      b.fillRect(x + 1, y, 2, 1);
      b.fillStyle = "#f1c27d";
      b.fillRect(x + 1, y + 1, 2, 2);
      b.fillStyle = SHIRTS[Math.floor(r * 331) % SHIRTS.length];
      b.fillRect(x, y + 3, 4, 3);
      if (jump) b.fillRect(x - 1, y + 1, 1, 2), b.fillRect(x + 4, y + 1, 1, 2);   // 팔을 든다
      b.fillStyle = "#3b3b5c";
      b.fillRect(x + 1, y + 6, 2, 2);
    }
  }
}

function drawDust(b, x, base, now, i) {
  b.fillStyle = "rgba(233, 196, 140, .85)";
  for (let k = 0; k < 4; k++) {
    const r = hash(Math.floor(now / 60) + k * 13, i);
    b.fillRect(x + 4 - Math.floor(r * 12) - k * 2, base - 1 - Math.floor(r * 4), 2, 1);
  }
}

// ── 도트 숫자 (3×5) ─────────────────────────────────────────────────
const DIGITS = {
  0: "111101101101111", 1: "010110010010111", 2: "111001111100111", 3: "111001111001111", 4: "101101111001001",
  5: "111100111001111", 6: "111100111101111", 7: "111001001010010", 8: "111101111101111", 9: "111101111001111",
};
function drawDigits(b, text, x, y, scale, color, shadow) {
  let cx = x;
  for (const ch of text) {
    const bits = DIGITS[ch];
    for (let i = 0; i < 15; i++) {
      if (bits[i] !== "1") continue;
      const px = cx + (i % 3) * scale, py = y + Math.floor(i / 3) * scale;
      if (shadow) {
        b.fillStyle = shadow;
        b.fillRect(px + 1, py + 1, scale, scale);
      }
      b.fillStyle = color;
      b.fillRect(px, py, scale, scale);
    }
    cx += 4 * scale;
  }
}

// ── 말 · 기수 스프라이트 (오른쪽을 봄, 38×27) ─────────────────────────
// 다리 자세: [무릎 dx, 무릎 dy, 발굽 dx, 발굽 y] × (앞다리 가까운/먼, 뒷다리 가까운/먼). 엉덩이 기준.
const POSES = [
  [[4, 3, 8, 25], [3, 4, 6, 26], [-3, 3, -7, 25], [-2, 4, -5, 26]],   // 쭉 뻗음
  [[2, 4, 2, 26], [4, 3, 7, 24], [-1, 4, -2, 26], [-3, 3, -6, 25]],
  [[2, 3, -1, 24], [1, 4, 0, 26], [2, 3, 4, 25], [1, 4, 2, 26]],      // 모음 (공중)
  [[3, 2, 6, 23], [2, 4, 1, 26], [0, 4, -1, 26], [-2, 3, -4, 25]],
];
const STAND = [[0, 4, 1, 26], [1, 4, 2, 26], [0, 4, -1, 26], [1, 4, 0, 26]];
const BOB = [0, -1, 0, 1];

function sprite(s, h, lane, f) {
  const key = `${h.id}:${lane}:${f}`;
  let c = s.sprites.get(key);
  if (c) return c;
  c = document.createElement("canvas");
  c.width = SPR_W;
  c.height = SPR_H;
  const g = c.getContext("2d");
  drawHorse(g, h, lane, f);
  outline(g, SPR_W, SPR_H, "#2a1608");
  s.sprites.set(key, c);
  return c;
}

function shade(hex, k) {
  const n = parseInt(hex.slice(1), 16);
  const r = Math.round(((n >> 16) & 255) * k), g = Math.round(((n >> 8) & 255) * k), bl = Math.round((n & 255) * k);
  return `rgb(${Math.min(255, r)},${Math.min(255, g)},${Math.min(255, bl)})`;
}

function drawHorse(g, h, lane, f) {
  const body = h.coat, mane = h.mane, far = shade(h.coat, 0.72);
  const dy = f < 0 ? 0 : BOB[f];
  const pose = f < 0 ? STAND : POSES[f];
  const R = (x, y, w, hh, col) => {
    g.fillStyle = col;
    g.fillRect(x, y + dy, w, hh);
  };
  // 다리 (굵기 2px 선). 먼 쪽 다리를 먼저, 어둡게
  const leg = (hipX, [kx, ky, hx, hy], col) => {
    const hipY = 18 + dy;
    const knee = [hipX + kx, hipY + ky];
    line(g, hipX, hipY, knee[0], knee[1], col);
    line(g, knee[0], knee[1], hipX + hx, hy - 1, col);
    g.fillStyle = "#1a1a1a";
    g.fillRect(hipX + hx, hy - 1, 2, 1);
  };
  leg(24, pose[1], far);
  leg(11, pose[3], far);

  // 꼬리 (달릴 때 흩날림)
  const tw = f < 0 ? 0 : (f % 2);
  R(5, 12, 6, 2, mane);
  R(3, 13 + tw, 3, 3, mane);
  R(1, 15 + tw, 3, 2, mane);
  // 몸통
  R(10, 12, 16, 6, body);
  R(9, 13, 18, 4, body);
  R(11, 18, 13, 1, far);
  // 목 · 머리
  R(24, 9, 4, 5, body);
  R(26, 7, 4, 4, body);
  R(28, 5, 6, 4, body);
  R(32, 7, 4, 3, body);
  R(29, 3, 2, 2, body);               // 귀
  R(25, 6, 2, 5, mane);               // 갈기
  R(27, 4, 2, 3, mane);
  R(31, 6, 1, 1, "#111111");          // 눈
  R(35, 8, 1, 1, "#3a2a20");          // 콧구멍
  // 가까운 다리
  leg(24, pose[0], body);
  leg(11, pose[2], body);
  // 안장천 + 번호
  const [cloth, digit] = LANE_COLOR[lane];
  R(13, 12, 8, 7, cloth);
  R(13, 12, 8, 1, shade(cloth === "#222222" ? "#555555" : cloth, 0.8));
  g.save();
  g.translate(0, dy);
  drawDigits(g, String(lane), 15, 13, 1, digit, null);
  g.restore();
  // 기수: 흰 바지, 검은 장화, 몸통(옷 색), 팔, 헬멧(옷 색), 얼굴
  const silk = h.silk;
  R(17, 9, 4, 3, "#f5f5f5");
  R(19, 12, 2, 4, "#1a1a1a");
  R(14, 5, 6, 4, silk);
  R(15, 4, 4, 1, silk);
  R(19, 6, 4, 2, shade(silk, 0.85));
  R(23, 7, 1, 1, "#f1c27d");          // 손
  R(24, 7, 4, 1, "#3a2a20");          // 고삐
  R(19, 1, 4, 2, silk);               // 헬멧
  R(22, 2, 1, 1, "#111111");          // 챙
  R(20, 3, 3, 2, "#f1c27d");          // 얼굴
}

// 1px 외곽선: 밝은 털색도 흙 트랙 위에서 또렷하게 보이도록
function outline(g, w, h, col) {
  const d = g.getImageData(0, 0, w, h).data;
  const on = (x, y) => x >= 0 && y >= 0 && x < w && y < h && d[(y * w + x) * 4 + 3] > 0;
  g.fillStyle = col;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (!on(x, y) && (on(x - 1, y) || on(x + 1, y) || on(x, y - 1) || on(x, y + 1))) g.fillRect(x, y, 1, 1);
    }
  }
}

// 2px 굵기 픽셀 선 (브레젠햄)
function line(g, x0, y0, x1, y1, col) {
  g.fillStyle = col;
  let dx = Math.abs(x1 - x0), sx = x0 < x1 ? 1 : -1;
  let dy = -Math.abs(y1 - y0), sy = y0 < y1 ? 1 : -1;
  let err = dx + dy;
  for (;;) {
    g.fillRect(x0, y0, 2, 1);
    if (x0 === x1 && y0 === y1) break;
    const e2 = 2 * err;
    if (e2 >= dy) {
      err += dy;
      x0 += sx;
    }
    if (e2 <= dx) {
      err += dx;
      y0 += sy;
    }
  }
}
