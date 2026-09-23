"""딜러 원본 영상에서 동작별 클립을 잘라 한 파일로 이어 붙이고, 구간 정보(JSON)를 만든다.

    python tools/build_dealer_clips.py <원본 폴더>

- 원본 영상 아래쪽 테이블(블랙잭 문구)이 보이지 않도록 위쪽 456픽셀만 쓴다.
- 구간 경계로 바로 이동할 수 있게 6프레임(0.25초)마다 키프레임을 넣는다.
- "show" 구간(딜러가 카드를 들어 보이는 장면)은 카드 위치를 프레임마다 추적해서,
  화면에서 실제 게임 카드 이미지를 그 자리에 덮어씌울 수 있게 한다.
"""
import glob
import json
import os
import subprocess
import sys

import cv2
import imageio_ffmpeg
import numpy as np

FPS = 24
CROP_H = 456
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "..", "static")

# 원본 파일 이름(일부) → 짧은 이름
SOURCES = {
    "m1": "a black tuxedo with gold satin lapels, black shirt and .mp4",
    "m2": "black tuxedo with gold satin lapels, black shirt and bl.mp4",
    "f0": "gold flower hair ornament, black traditional-style to.mp4",
    "f1": "black traditional-st (1).mp4",
    "f2": "a gold flower hair ornament, black traditional-style .mp4",
}

# 딜러별 동작 구간: (이름, 원본, 시작 프레임, 끝 프레임)
SEGMENTS = {
    "m": [
        ("deal", "m2", 18, 54),     # 왼쪽 슈로 손을 뻗어 카드를 꺼낸다
        ("player", "m2", 54, 84),   # 왼쪽 아래(플레이어 쪽)로 팔을 뻗는다
        ("banker", "m2", 90, 132),  # 오른쪽 아래(뱅커 쪽)로 팔을 뻗는다
        ("show", "m1", 46, 70),     # 카드를 가슴 앞에 들어 보인다 (카드 추적)
    ],
    "f": [
        ("deal", "f1", 30, 62),
        ("player", "f2", 54, 87),
        ("banker", "f2", 96, 141),
        ("show", "f0", 42, 72),     # 가운데에서 카드를 다룬다
    ],
}
TRACK = {("m", "show")}


def find(folder, key):
    hits = [p for p in glob.glob(os.path.join(folder, "*.mp4")) if p.endswith(key)]
    if len(hits) != 1:
        sys.exit(f"원본을 하나로 특정할 수 없습니다: {key} → {hits}")
    return hits[0]


def track_card(path, f0, f1):
    """딜러가 든 흰 카드의 위치 (자른 영상 기준 픽셀). 못 찾은 프레임은 None."""
    cap = cv2.VideoCapture(path)
    out = []
    for i in range(f0, f1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = cap.read()
        box = None
        if ok:
            x0, y0 = 380, 150
            hsv = cv2.cvtColor(fr[y0:CROP_H, x0:1000], cv2.COLOR_BGR2HSV)
            mask = ((hsv[..., 1] < 45) & (hsv[..., 2] > 185)).astype(np.uint8) * 255
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
            best = None
            for k in range(1, n):
                x, y, w, h, a = stats[k]
                if a > 250 and 15 < w < 160 and 15 < h < 160 and (best is None or a > best[4]):
                    best = (int(x + x0), int(y + y0), int(w), int(h), int(a))
            if best:
                box = list(best[:4])
        out.append(box)
    return out


def build(dealer, folder, ffmpeg):
    segs = SEGMENTS[dealer]
    names = sorted({src for _, src, _, _ in segs})
    paths = {src: find(folder, SOURCES[src]) for src in names}
    inputs, filters, labels = [], [], []
    for src in names:
        inputs += ["-i", paths[src]]
    meta = {"fps": FPS, "height": CROP_H, "segments": {}, "track": {}}
    t = 0.0
    for k, (name, src, a, b) in enumerate(segs):
        idx = names.index(src)
        filters.append(f"[{idx}:v]trim=start_frame={a}:end_frame={b},setpts=PTS-STARTPTS,crop=iw:{CROP_H}:0:0[s{k}]")
        labels.append(f"[s{k}]")
        dur = (b - a) / FPS
        meta["segments"][name] = [round(t, 4), round(t + dur, 4)]
        if (dealer, name) in TRACK:
            meta["track"][name] = track_card(paths[src], a, b)
        t += dur
    width = int(cv2.VideoCapture(paths[names[0]]).get(cv2.CAP_PROP_FRAME_WIDTH))
    meta["width"] = width
    filt = ";".join(filters) + ";" + "".join(labels) + f"concat=n={len(segs)}:v=1:a=0[out]"
    out = os.path.join(STATIC, f"dealer_{dealer}_clips.mp4")
    cmd = [ffmpeg, "-y", "-loglevel", "error", *inputs, "-filter_complex", filt, "-map", "[out]",
           "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "24", "-g", "6", "-keyint_min", "6",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True)
    with open(os.path.join(STATIC, f"dealer_{dealer}_clips.json"), "w", encoding="utf-8") as fp:
        json.dump(meta, fp)
    print(dealer, os.path.getsize(out) // 1024, "KB", meta["segments"])


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Downloads")
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    for d in SEGMENTS:
        build(d, folder, ff)
