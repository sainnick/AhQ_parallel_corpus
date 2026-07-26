#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import edge_tts

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "xiangyu_real_clips_work"
DOWNLOADS = WORK / "downloads"
VOICE = WORK / "voice"
OUT = ROOT / "out"
FONT_DIR = "/usr/share/fonts/opentype/noto"

PRIMARY_SOURCES = [
    (
        "promo",
        "https://www.bilibili.com/video/BV1DoRzYzELK/",
        "楚汉传奇官方宣传片：项羽原声与人物镜头",
    ),
    (
        "battle",
        "https://www.bilibili.com/video/BV1viw2eQEiG/",
        "项羽二十八骑突围战斗镜头",
    ),
    (
        "ending",
        "https://www.bilibili.com/video/BV1AVP1eiEWh/",
        "项羽乌江自刎前后镜头",
    ),
    (
        "fanzeng",
        "https://www.bilibili.com/video/BV1xNT7zbEHM/",
        "陈平反间计与范增离营镜头",
    ),
]

FALLBACK_SOURCES = [
    (
        "hongmen",
        "https://tv.cctv.com/2019/10/27/VIDEBVriZOYCAQ6wdb96jraN191027.shtml",
        "央视纪录片《楚汉》第一集鸿门之宴",
    ),
    (
        "pengcheng",
        "https://tv.cctv.com/2019/10/27/VIDE3yMEAqVhaOgODLGqLQ81191027.shtml",
        "央视纪录片《楚汉》第二集暗度陈仓与彭城之战",
    ),
    (
        "chuhe",
        "https://tv.cctv.com/2019/10/29/VIDE07GUmCVgRexjPZjM1tuT191029.shtml",
        "央视纪录片《楚汉》第三集楚河汉界",
    ),
    (
        "gaixia",
        "https://tv.cctv.com/2019/10/29/VIDEMH6B7FZSjpaJFQtoHaEi191029.shtml",
        "央视纪录片《楚汉》第四集霸王别姬",
    ),
]

PHRASES = [
    "项羽一生打了七十多场仗，几乎从没输过。",
    "巨鹿之战，他破釜沉舟，打垮秦军主力。",
    "彭城之战，他又用三万精兵，击溃刘邦数十万联军。",
    "可这样一个人，为什么最后还是输掉了天下？",
    "因为项羽能赢一场仗，却没能把胜利变成组织。",
    "韩信得不到重用，陈平转投刘邦，范增也被气走。",
    "刘邦自己不如项羽能打，却敢把兵交给韩信，把后方交给萧何，把谋略交给张良。",
    "项羽靠一个人的威望压住天下，刘邦靠一群人把天下接住。",
    "所以垓下之败，不是突然失败，而是此前所有用人选择的总账。",
    "项羽输的不是勇武，是组织。",
]


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    p = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if p.stdout:
        print(p.stdout[-5000:], flush=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(cmd)}")
    return p


def probe_duration(path: Path) -> float:
    p = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    return float(p.stdout.strip())


def valid_video(path: Path) -> bool:
    try:
        return path.exists() and path.stat().st_size > 300_000 and probe_duration(path) > 3
    except Exception:
        return False


def download_source(name: str, url: str) -> Path | None:
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    template = str(DOWNLOADS / f"{name}.%(ext)s")
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--no-warnings",
        "--retries",
        "6",
        "--fragment-retries",
        "6",
        "--socket-timeout",
        "30",
        "--merge-output-format",
        "mp4",
        "-f",
        "bv*[height<=720]+ba/b[height<=720]/best[height<=720]/best",
        "-o",
        template,
        url,
    ]
    result = run(cmd, check=False)
    candidates = sorted(DOWNLOADS.glob(f"{name}.*"), key=lambda p: p.stat().st_size, reverse=True)
    for candidate in candidates:
        if valid_video(candidate):
            if candidate.suffix.lower() != ".mp4":
                converted = DOWNLOADS / f"{name}.mp4"
                run([
                    "ffmpeg", "-y", "-i", str(candidate),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
                    str(converted),
                ])
                return converted
            return candidate
    print(f"download failed for {name}: {url}\n{result.stdout}", flush=True)
    return None


def collect_sources() -> tuple[list[Path], list[str]]:
    clips: list[Path] = []
    credits: list[str] = []
    for name, url, description in PRIMARY_SOURCES:
        path = download_source(name, url)
        if path:
            clips.append(path)
            credits.append(f"{description} | {url}")
    if len(clips) < 3:
        for name, url, description in FALLBACK_SOURCES:
            path = download_source(name, url)
            if path:
                clips.append(path)
                credits.append(f"{description} | {url}")
            if len(clips) >= 5:
                break
    if len(clips) < 2:
        raise RuntimeError("Could not download enough Xiang Yu-specific source videos")
    return clips, credits


async def synthesize_voice() -> tuple[Path, list[tuple[float, float, str]]]:
    VOICE.mkdir(parents=True, exist_ok=True)
    silence = VOICE / "gap.mp3"
    run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
        "-t", "0.10", "-q:a", "4", str(silence),
    ])
    gap_duration = probe_duration(silence)

    files: list[Path] = []
    timings: list[tuple[float, float, str]] = []
    cursor = 0.0
    for index, phrase in enumerate(PHRASES):
        part = VOICE / f"part_{index:02d}.mp3"
        communication = edge_tts.Communicate(
            phrase,
            voice="zh-CN-YunyangNeural",
            rate="+18%",
            pitch="+2Hz",
            volume="+5%",
        )
        await communication.save(str(part))
        part_duration = probe_duration(part)
        timings.append((cursor, cursor + part_duration, phrase))
        cursor += part_duration
        files.append(part)
        if index < len(PHRASES) - 1:
            files.append(silence)
            cursor += gap_duration

    concat = VOICE / "voice_concat.txt"
    concat.write_text("\n".join(f"file '{p.resolve()}'" for p in files), encoding="utf-8")
    narration = VOICE / "narration.m4a"
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
        "-af", "acompressor=threshold=-18dB:ratio=3:attack=5:release=80,"
               "equalizer=f=160:t=q:w=1.2:g=2.5,"
               "equalizer=f=3200:t=q:w=1.1:g=1.8,"
               "loudnorm=I=-15:LRA=5:TP=-1.5",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(narration),
    ])
    return narration, timings


def ass_time(seconds: float) -> str:
    cs = max(0, int(round(seconds * 100)))
    hours, rem = divmod(cs, 360000)
    minutes, rem = divmod(rem, 6000)
    secs, centis = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def wrap_cn(text: str, limit: int = 16) -> str:
    if len(text) <= limit:
        return text
    options = [
        i + 1 for i, char in enumerate(text)
        if char in "，。！？；：" and 8 <= i + 1 <= limit + 5
    ]
    cut = options[-1] if options else limit
    return text[:cut] + r"\N" + text[cut:]


def write_ass(timings: list[tuple[float, float, str]], total: float) -> Path:
    ass = WORK / "subtitles.ass"
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Sub,Noto Sans CJK SC,58,&H00FFFFFF,&H00FFFFFF,&H000A0A0A,&H68000000,-1,0,0,0,100,100,0,0,3,2,0,2,55,55,130,1
Style: Title,Noto Sans CJK SC,82,&H00FFFFFF,&H00FFFFFF,&H00101010,&H50000000,-1,0,0,0,100,100,0,0,1,5,2,8,55,55,135,1
Style: End,Noto Sans CJK SC,72,&H00FFFFFF,&H00FFFFFF,&H00101010,&H65000000,-1,0,0,0,100,100,1,0,1,5,2,5,55,55,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events: list[str] = []
    title_end = min(3.2, total)
    events.append(
        f"Dialogue: 4,{ass_time(0)},{ass_time(title_end)},Title,,0,0,0,,"
        r"{\c&H2C32D9&}项羽打赢七十多场仗{\c&HFFFFFF&}\N为什么最后输给刘邦？"
    )
    for start, end, phrase in timings:
        events.append(
            f"Dialogue: 5,{ass_time(start)},{ass_time(end)},Sub,,0,0,0,,{wrap_cn(phrase)}"
        )
    events.append(
        f"Dialogue: 6,{ass_time(max(0, total - 2.4))},{ass_time(total)},End,,0,0,0,,"
        r"{\c&H2C32D9&}项羽输的不是勇武{\c&HFFFFFF&}\N而是组织"
    )
    ass.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return ass


def make_segment(src: Path, dest: Path, start: float, length: float, index: int) -> None:
    source_duration = probe_duration(src)
    if source_duration <= length + 0.2:
        start = 0.0
    else:
        start = max(0.0, min(start, source_duration - length - 0.1))
    # Center crop with a slightly alternating horizontal bias to keep faces in frame.
    bias = [0.50, 0.42, 0.58, 0.47, 0.54][index % 5]
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920:(iw-ow)*{bias}:(ih-oh)/2,"
        "fps=30,setsar=1,"
        "eq=contrast=1.08:saturation=0.93:brightness=-0.015,"
        "unsharp=5:5:0.35:3:3:0.15,"
        "vignette=PI/8,format=yuv420p"
    )
    run([
        "ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(src),
        "-t", f"{length:.3f}", "-an", "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", str(dest),
    ])


def render(clips: list[Path], narration: Path, timings: list[tuple[float, float, str]], credits: list[str]) -> tuple[Path, Path]:
    total = probe_duration(narration)
    ass = write_ass(timings, total)

    # Around two seconds per cut. Every source is Xiang Yu / Chu-Han-specific.
    segment_length = 2.25
    segment_count = math.ceil(total / segment_length) + 1
    segments: list[Path] = []
    clip_durations = [probe_duration(c) for c in clips]

    for index in range(segment_count):
        src_index = index % len(clips)
        # Rotate through different positions in each source instead of repeatedly using its opening.
        src_duration = clip_durations[src_index]
        usable = max(0.0, src_duration - segment_length - 0.1)
        start = ((index // len(clips)) * 7.3 + src_index * 3.7) % usable if usable > 0 else 0.0
        segment = WORK / f"segment_{index:02d}.mp4"
        make_segment(clips[src_index], segment, start, segment_length, index)
        segments.append(segment)

    concat = WORK / "segments.txt"
    concat.write_text("\n".join(f"file '{p.resolve()}'" for p in segments), encoding="utf-8")
    base = WORK / "base.mp4"
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
        "-t", f"{total:.3f}", "-c:v", "copy", str(base),
    ])

    OUT.mkdir(parents=True, exist_ok=True)
    final = OUT / "项羽为什么输给刘邦_项羽真实片段快节奏版.mp4"
    # Subtle low-frequency pulse under the stronger narration.
    filter_complex = (
        f"[0:v]subtitles={ass.as_posix()}:fontsdir={FONT_DIR}[v];"
        f"sine=frequency=58:duration={total:.3f}:sample_rate=48000,"
        "tremolo=f=1.9:d=0.82,volume=0.025[beat];"
        f"anoisesrc=color=brown:amplitude=0.006:duration={total:.3f},"
        "lowpass=f=240[air];"
        "[1:a]volume=1.0[voice];"
        "[voice][beat][air]amix=inputs=3:duration=first:dropout_transition=0,"
        "alimiter=limit=0.95[a]"
    )
    run([
        "ffmpeg", "-y", "-i", str(base), "-i", str(narration),
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", "-shortest", str(final),
    ])

    contact_sheet = OUT / "项羽真实片段快节奏版_画面检查.jpg"
    sample_interval = max(1.0, total / 12)
    run([
        "ffmpeg", "-y", "-i", str(final),
        "-vf", f"fps=1/{sample_interval:.4f},scale=270:480,tile=4x3:padding=4:margin=4",
        "-frames:v", "1", "-q:v", "2", str(contact_sheet),
    ])

    (OUT / "素材来源.txt").write_text("\n".join(credits) + "\n", encoding="utf-8")
    return final, contact_sheet


async def main() -> int:
    for directory in (WORK, DOWNLOADS, VOICE, OUT):
        directory.mkdir(parents=True, exist_ok=True)
    clips, credits = collect_sources()
    print("usable sources:", [str(p) for p in clips], flush=True)
    narration, timings = await synthesize_voice()
    final, contact_sheet = render(clips, narration, timings, credits)
    print(f"FINAL={final}")
    print(f"CONTACT_SHEET={contact_sheet}")
    print(f"DURATION={probe_duration(final):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
