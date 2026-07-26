#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import math
import subprocess
from pathlib import Path

import edge_tts

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "xiangyu_real_clips_v3_work"
DOWNLOADS = WORK / "downloads"
VOICE = WORK / "voice"
OUT = ROOT / "out"
FONT_DIR = "/usr/share/fonts/opentype/noto"

# CCTV short highlights: every source is directly about Xiang Yu.
SOURCES = [
    ("julu", "https://tv.cctv.com/2019/10/29/VIDEnBn42nbaDBGMehnHfXL5191029.shtml", "《楚汉》巨鹿之战：项羽破釜沉舟"),
    ("pengcheng", "https://tv.cctv.com/2019/10/29/VIDEeiXDYhSlhFm9pNFQfePn191029.shtml", "《楚汉》彭城之战：项羽大获全胜"),
    ("fanzeng", "https://tv.cctv.com/2019/10/29/VIDEzqvuyrCbvW5GYntjRt9V191029.shtml", "《楚汉》反间计：范增离开项羽"),
    ("gaixia", "https://tv.cctv.com/2019/10/29/VIDEfkkiTQoriYBwYSE8Gp0I191029.shtml", "《楚汉》垓下决战：项羽唯一一次失利"),
    ("farewell", "https://tv.cctv.com/2019/10/29/VIDEUZh04nKQePv7Gvj5oU9M191029.shtml", "《楚汉》霸王别姬：英雄与美人泪别"),
]

PHRASES = [
    "项羽一生打了七十多场仗，几乎从没输过。",
    "巨鹿之战，他破釜沉舟，打垮秦军主力。",
    "彭城之战，他又用三万精兵，击溃刘邦数十万联军。",
    "可这样一个人，为什么最后还是输掉了天下？",
    "因为项羽能赢一场仗，却没能把胜利变成组织。",
    "韩信得不到重用，陈平转投刘邦，范增也被气走。",
    "刘邦不如项羽能打，却敢把兵交给韩信，把后方交给萧何，把谋略交给张良。",
    "项羽靠一个人的威望压住天下，刘邦靠一群人把天下接住。",
    "所以垓下之败，不是突然失败，而是此前所有用人选择的总账。",
    "项羽输的不是勇武，是组织。",
]


def run(cmd: list[str], *, check: bool = True, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    try:
        p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        text = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        print(f"TIMEOUT after {timeout}s\n{text[-3000:]}", flush=True)
        return subprocess.CompletedProcess(cmd, 124, text + "\nTIMEOUT")
    if p.stdout:
        print(p.stdout[-5000:], flush=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(cmd)}")
    return p


def duration(path: Path) -> float:
    p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
    return float(p.stdout.strip())


def valid_video(path: Path) -> bool:
    try:
        return path.exists() and path.stat().st_size > 250_000 and duration(path) > 3
    except Exception:
        return False


def download(name: str, url: str) -> Path | None:
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    template = str(DOWNLOADS / f"{name}.%(ext)s")
    run([
        "yt-dlp", "--no-playlist", "--no-warnings",
        "--retries", "3", "--fragment-retries", "3", "--socket-timeout", "20",
        "--download-sections", "*0-100", "--force-keyframes-at-cuts",
        "--merge-output-format", "mp4",
        "-f", "bv*[height<=720]+ba/b[height<=720]/best[height<=720]/best",
        "-o", template, url,
    ], check=False, timeout=180)
    candidates = sorted(DOWNLOADS.glob(f"{name}.*"), key=lambda p: p.stat().st_size, reverse=True)
    for candidate in candidates:
        if not valid_video(candidate):
            continue
        if candidate.suffix.lower() == ".mp4":
            return candidate
        converted = DOWNLOADS / f"{name}.mp4"
        run(["ffmpeg", "-y", "-i", str(candidate), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "128k", str(converted)], timeout=180)
        return converted
    return None


def collect() -> tuple[list[Path], list[str]]:
    clips: list[Path] = []
    credits: list[str] = []
    for name, url, label in SOURCES:
        clip = download(name, url)
        if clip:
            clips.append(clip)
            credits.append(f"{label} | {url}")
    if len(clips) < 3:
        raise RuntimeError(f"只有 {len(clips)} 段项羽专题视频下载成功")
    return clips, credits


async def voice() -> tuple[Path, list[tuple[float, float, str]]]:
    VOICE.mkdir(parents=True, exist_ok=True)
    gap = VOICE / "gap.mp3"
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "0.07", "-q:a", "4", str(gap)])
    gap_d = duration(gap)
    parts: list[Path] = []
    timings: list[tuple[float, float, str]] = []
    cursor = 0.0
    for i, phrase in enumerate(PHRASES):
        part = VOICE / f"part_{i:02d}.mp3"
        await edge_tts.Communicate(
            phrase,
            voice="zh-CN-YunyangNeural",
            rate="+24%",
            pitch="+3Hz",
            volume="+8%",
        ).save(str(part))
        d = duration(part)
        timings.append((cursor, cursor + d, phrase))
        cursor += d
        parts.append(part)
        if i < len(PHRASES) - 1:
            parts.append(gap)
            cursor += gap_d
    listing = VOICE / "concat.txt"
    listing.write_text("\n".join(f"file '{p.resolve()}'" for p in parts), encoding="utf-8")
    narration = VOICE / "narration.m4a"
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-af", "acompressor=threshold=-21dB:ratio=3.8:attack=3:release=65,"
               "equalizer=f=135:t=q:w=1.1:g=3.2,"
               "equalizer=f=3000:t=q:w=1.0:g=2.4,"
               "loudnorm=I=-14:LRA=4:TP=-1.1",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(narration),
    ])
    return narration, timings


def ass_time(sec: float) -> str:
    cs = max(0, int(round(sec * 100)))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def wrap(text: str, limit: int = 16) -> str:
    if len(text) <= limit:
        return text
    candidates = [i + 1 for i, ch in enumerate(text) if ch in "，。！？；：" and 8 <= i + 1 <= limit + 5]
    cut = candidates[-1] if candidates else limit
    return text[:cut] + r"\N" + text[cut:]


def subtitles(timings: list[tuple[float, float, str]], total: float) -> Path:
    path = WORK / "subtitles.ass"
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Sub,Noto Sans CJK SC,59,&H00FFFFFF,&H00FFFFFF,&H000A0A0A,&H76000000,-1,0,0,0,100,100,0,0,3,2,0,2,55,55,125,1
Style: Title,Noto Sans CJK SC,83,&H00FFFFFF,&H00FFFFFF,&H00101010,&H55000000,-1,0,0,0,100,100,0,0,1,5,2,8,55,55,135,1
Style: End,Noto Sans CJK SC,73,&H00FFFFFF,&H00FFFFFF,&H00101010,&H68000000,-1,0,0,0,100,100,1,0,1,5,2,5,55,55,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events = [
        f"Dialogue: 5,{ass_time(0)},{ass_time(min(3.0,total))},Title,,0,0,0,,"
        r"{\c&H2C32D9&}项羽打赢七十多场仗{\c&HFFFFFF&}\N为什么最后输给刘邦？"
    ]
    for start, end, phrase in timings:
        events.append(f"Dialogue: 6,{ass_time(start)},{ass_time(end)},Sub,,0,0,0,,{wrap(phrase)}")
    events.append(
        f"Dialogue: 7,{ass_time(max(0,total-2.1))},{ass_time(total)},End,,0,0,0,,"
        r"{\c&H2C32D9&}项羽输的不是勇武{\c&HFFFFFF&}\N而是组织"
    )
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return path


def make_segment(src: Path, dest: Path, start: float, length: float, idx: int) -> None:
    d = duration(src)
    start = 0.0 if d <= length + 0.1 else max(0.0, min(start, d - length - 0.05))
    bias = [0.50, 0.44, 0.56, 0.47, 0.53][idx % 5]
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920:(iw-ow)*{bias}:(ih-oh)/2,"
        "fps=30,setsar=1,eq=contrast=1.08:saturation=0.96:brightness=-0.012,"
        "unsharp=5:5:0.32:3:3:0.12,vignette=PI/10,format=yuv420p"
    )
    run([
        "ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{length:.3f}",
        "-an", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(dest),
    ], timeout=180)


def render(clips: list[Path], narration: Path, timings: list[tuple[float, float, str]], credits: list[str]) -> tuple[Path, Path]:
    total = duration(narration)
    ass = subtitles(timings, total)
    seg_len = 1.95
    count = math.ceil(total / seg_len) + 1
    durations = [duration(c) for c in clips]
    # 0巨鹿 1彭城 2范增 3垓下 4霸王别姬
    source_order = [0,0,1,1,1,3,2,2,2,4,1,1,2,3,3,4,3,4,3,4,0,1,3]
    parts: list[Path] = []
    for i in range(count):
        source_i = source_order[i % len(source_order)] % len(clips)
        usable = max(0.0, durations[source_i] - seg_len - 0.1)
        # Skip title cards when possible, then move through each short highlight.
        base_start = 2.2 + (i // max(1, len(clips))) * 5.1 + source_i * 2.7
        start = base_start % usable if usable > 2.2 else 0.0
        part = WORK / f"segment_{i:02d}.mp4"
        make_segment(clips[source_i], part, start, seg_len, i)
        parts.append(part)
    listing = WORK / "segments.txt"
    listing.write_text("\n".join(f"file '{p.resolve()}'" for p in parts), encoding="utf-8")
    base = WORK / "base.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-t", f"{total:.3f}", "-c:v", "copy", str(base)])
    OUT.mkdir(parents=True, exist_ok=True)
    final = OUT / "项羽为什么输给刘邦_项羽专题片段快节奏版.mp4"
    fc = (
        f"[0:v]subtitles={ass.as_posix()}:fontsdir={FONT_DIR}[v];"
        f"sine=frequency=60:duration={total:.3f}:sample_rate=48000,tremolo=f=2.15:d=0.84,volume=0.021[beat];"
        f"anoisesrc=color=brown:amplitude=0.0035:duration={total:.3f},lowpass=f=220[air];"
        "[1:a][beat][air]amix=inputs=3:duration=first:dropout_transition=0,alimiter=limit=0.95[a]"
    )
    run([
        "ffmpeg", "-y", "-i", str(base), "-i", str(narration), "-filter_complex", fc,
        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", "-shortest", str(final),
    ], timeout=300)
    sheet = OUT / "项羽专题片段快节奏版_画面检查.jpg"
    interval = max(1.0, total / 12)
    run([
        "ffmpeg", "-y", "-i", str(final),
        "-vf", f"fps=1/{interval:.4f},scale=270:480,tile=4x3:padding=4:margin=4",
        "-frames:v", "1", "-q:v", "2", str(sheet),
    ])
    (OUT / "素材来源.txt").write_text("\n".join(credits) + "\n", encoding="utf-8")
    return final, sheet


async def main() -> int:
    for p in (WORK, DOWNLOADS, VOICE, OUT):
        p.mkdir(parents=True, exist_ok=True)
    clips, credits = collect()
    narration, timings = await voice()
    final, sheet = render(clips, narration, timings, credits)
    print(f"FINAL={final}")
    print(f"SHEET={sheet}")
    print(f"DURATION={duration(final):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
