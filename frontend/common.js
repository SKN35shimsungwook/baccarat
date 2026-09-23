// 바카라·블랙잭 테이블이 함께 쓰는 코드 (파이썬에서 각 게임 JS 앞에 이어 붙인다)

const SUIT = { S: "♠", H: "♥", D: "♦", C: "♣" };
const CHIP_COLORS = {
  1000: "#7d7263", 5000: "#b3241b", 10000: "#1f3f7a", 50000: "#1f6b4a",
  100000: "#1a1411", 500000: "#5b2a86", 1000000: "#9c7426",
};
const RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"];
const FONT_URL =
  "https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700&family=Noto+Serif+KR:wght@500;700&display=swap";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fmt = (n) => Number(n).toLocaleString("ko-KR");
const short = (n) => (n >= 1e6 ? `${n / 1e6}M` : n >= 1e3 ? `${n / 1e3}K` : `${n}`);
const signed = (n) => (n > 0 ? `+${fmt(n)}` : fmt(n));
const sum = (obj) => Object.values(obj).reduce((a, b) => a + b, 0);

// ── 이미지·폰트 (한 번만) ────────────────────────────────────────────
let assetsLoaded = false;
function loadAssets(base) {
  if (assetsLoaded) return;
  assetsLoaded = true;
  // 폰트는 문서 전체에 등록돼야 Shadow DOM 안에서도 쓸 수 있다
  if (!document.querySelector(`link[href="${FONT_URL}"]`)) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = FONT_URL;
    document.head.appendChild(link);
  }
  // 카드를 공개할 때 깜빡이지 않도록 미리 받아 둔다
  const files = ["back", ...RANKS.flatMap((r) => ["S", "H", "D", "C"].map((su) => r + su))];
  files.forEach((f) => (new Image().src = `${base}cards/${f}.webp`));
  ["m", "f"].forEach((d) => (new Image().src = `${base}dealer_${d}_poster.jpg`));
}

// ── 딜러 영상: 동작별 클립 ──────────────────────────────────────────
// static/dealer_{m|f}_clips.mp4 한 파일에 deal / player / banker / show 구간이 이어져 있고,
// 구간 정보는 data.clips(JSON)로 받는다. 영상 두 개를 번갈아 쓰면서 겹쳐 전환한다.
function setDealer(s, who) {
  if (s.dealer === who) return;
  s.dealer = who;
  const base = s.data.asset_base;
  s.els.stage.style.setProperty("--stage-img", `url("${base}dealer_${who}_poster.jpg")`);
  stopClips(s, 0);
  s.videos = [s.els.video, s.els.video2];
  s.activeVideo = 1;
  s.heldMax = null;
  s.videos.forEach((v) => {
    v.src = `${base}dealer_${who}_clips.mp4`;
    v.load();
  });
}

function seekTo(v, t) {
  return new Promise((resolve) => {
    let timer;
    const done = () => {
      v.removeEventListener("seeked", done);
      clearTimeout(timer);
      resolve();
    };
    timer = setTimeout(done, 400);
    v.addEventListener("seeked", done);
    v.currentTime = t;
  });
}

// 구간 하나를 재생하고, 끝나면 마지막 장면에서 멈춘다.
// card를 주면 딜러가 든 카드 자리(추적 데이터)에 실제 게임 카드를 덮어씌운다.
async function playClip(s, name, { rate = 1, card = null } = {}) {
  const meta = s.data.clips;
  if (!meta || !meta.segments[name] || !s.videos || s.revealAll) return;
  const token = (s.clipToken = (s.clipToken || 0) + 1);
  const [a, b] = meta.segments[name];
  const idx = s.activeVideo === 0 ? 1 : 0;
  const v = s.videos[idx];
  const prev = s.videos[1 - idx];
  v.pause();
  await seekTo(v, a + 0.001);
  if (token !== s.clipToken) return;
  v.playbackRate = rate;
  try {
    await v.play();
  } catch (e) {
    return; // 재생이 막히면 정지 화면 유지
  }
  // 새 영상을 켠 뒤 이전 영상을 끈다 (위아래 순서와 상관없이 겹쳐 전환된다)
  v.classList.add("on");
  s.activeVideo = idx;
  setTimeout(() => {
    if (s.activeVideo === idx) {
      prev.classList.remove("on");
      prev.pause();
    }
  }, 260);

  const track = card ? meta.track[name] : null;
  if (track) showHeld(s, card);
  return new Promise((resolve) => {
    // requestAnimationFrame은 창이 가려지면 멈추므로, 구간 끝 확인과 카드 위치 갱신은 타이머로 한다
    // (30ms ≈ 영상 24fps보다 촘촘함)
    const timer = setInterval(() => {
      if (token !== s.clipToken) return finish();
      if (track) placeHeld(s, meta, track, v.currentTime - a);
      if (v.currentTime >= b - 0.03 || v.ended) finish();
    }, 30);
    const safety = setTimeout(() => finish(), ((b - a) / rate) * 1000 + 900);
    function finish() {
      clearInterval(timer);
      clearTimeout(safety);
      if (token === s.clipToken) v.pause();
      hideHeld(s);
      resolve();
    }
  });
}

// 판이 끝나면 잠시 마지막 장면을 보여 준 뒤 정지 화면(포스터)으로 돌아간다.
function stopClips(s, delay = 900) {
  const token = (s.clipToken = (s.clipToken || 0) + 1);
  hideHeld(s);
  if (!s.videos) return;
  setTimeout(() => {
    if (token !== s.clipToken) return;
    s.videos.forEach((v) => {
      v.classList.remove("on");
      v.pause();
    });
  }, delay);
}

function showHeld(s, card) {
  const el = s.els.held;
  el.src = `${s.data.asset_base}cards/${card.rank}${card.suit}.webp`;
  el.style.opacity = "0";
  el.classList.add("on");
}

function hideHeld(s) {
  s.els.held.classList.remove("on");
}

// 추적 좌표(자른 영상 픽셀)를 무대 좌표로 바꿔 카드를 놓는다. 영상은 object-fit: cover, 위쪽 기준.
function placeHeld(s, meta, track, t) {
  const el = s.els.held;
  const box = track[Math.max(0, Math.min(track.length - 1, Math.round(t * meta.fps)))];
  if (!box) {
    el.style.opacity = "0";
    return;
  }
  const r = s.els.stage.getBoundingClientRect();
  const scale = Math.max(r.width / meta.width, r.height / meta.height);
  const ox = (r.width - meta.width * scale) / 2;
  const [x, y, w, h] = box;
  const H = h * 1.12 * scale;
  const W = Math.max(w * 1.08, h * 0.66) * scale;
  el.style.left = `${ox + (x + w / 2) * scale - W / 2}px`;
  el.style.top = `${(y + h / 2) * scale - H / 2}px`;
  el.style.width = `${W}px`;
  el.style.height = `${H}px`;
  // 카드가 막 보이기 시작하거나 뒤집히는 순간(작게 잡힘)은 흐리게
  const maxArea = s.heldMax || (s.heldMax = Math.max(...track.filter(Boolean).map((q) => q[2] * q[3])));
  el.style.opacity = String(Math.min(1, (w * h) / (maxArea * 0.55)));
}

// ── 칩 / 토스트 ─────────────────────────────────────────────────────
function makeChip(value, label, small = false) {
  const chip = document.createElement("div");
  const denom = [...Object.keys(CHIP_COLORS)].map(Number).filter((d) => d <= value).pop() || 1000;
  chip.className = `bt-chip${small ? " sm" : ""}`;
  chip.style.setProperty("--c", CHIP_COLORS[denom]);
  chip.textContent = label;
  return chip;
}

function toast(s, msg) {
  const t = s.els.toast;
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(s.toastHandle);
  s.toastHandle = setTimeout(() => t.classList.remove("show"), 1800);
}
