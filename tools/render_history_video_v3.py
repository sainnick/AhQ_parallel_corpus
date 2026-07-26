#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from pathlib import Path

import edge_tts
import requests

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "history_render_work_v3"
CLIPS = WORK / "clips"
VOICE = WORK / "voice"
OUT = ROOT / "out"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"

# Every URL below was opened and visually verified before this render.
SOURCES = [
    ("cavalry", "https://videos.pexels.com/video-files/9466314/9466314-hd_1920_1080_25fps.mp4"),
    ("horse_commander", "https://videos.pexels.com/video-files/9466524/9466524-hd_1080_1920_25fps.mp4"),
    ("great_wall", "https://videos.pexels.com/video-files/1193306/1193306-hd_1920_1080_30fps.mp4"),
    ("fire", "https://videos.pexels.com/video-files/11574595/11574595-hd_1920_1080_30fps.mp4"),
    ("terracotta", "https://videos.pexels.com/video-files/36926085/15643133_3840_2160_25fps.mp4"),
    ("chinese_temple", "https://videos.pexels.com/video-files/36233168/15366055_3840_2160_25fps.mp4"),
]

PHRASES = [
    "项羽打赢那么多仗，为什么最后还是输掉了天下？",
    "巨鹿一战，他破釜沉舟，打出了诸侯都不敢正视的威名。",
    "可最后赢得天下的，却是屡次被他击退的刘邦。",
    "项羽输的不是勇武，而是没把胜利变成稳定的组织。",
    "入关以后，他分封十八路诸侯，却很快引发新的混战。",
    "他能在战场上决定一切，却不擅长让不同利益长期合作。",
    "对人才，他也常常不能真正放权。",
    "韩信得不到重用，转投刘邦；陈平也离开了楚营。",
    "刘邦自己未必最能打，却能让萧何管后方，张良定谋略，韩信领兵。",
    "项羽依靠个人威望，刘邦依靠一群人建立体系。",
    "所以垓下之败，只是最后呈现出来的结果。",
    "真正的胜负，早在用人和组织上就已经分出来了。",
    "项羽把天下当成战场，却没把人心当成根基。",
]

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept": "*/*"})


def run(cmd: list[str]) -> str:
    print("+", " ".join(cmd), flush=True)
    p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if p.returncode != 0:
        print(p.stdout, flush=True)
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(cmd)}")
    return p.stdout


def duration(path: Path) -> float:
    return float(run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path)
    ]).strip())


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    error: Exception | None = None
    for attempt in range(4):
        try:
            with SESSION.get(url, stream=True, timeout=(25, 300), allow_redirects=True) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                with tmp.open("wb") as f:
                    for chunk in r.iter_content(1024 * 1024):
                        if chunk:
                            f.write(chunk)
                if tmp.stat().st_size < 100_000:
                    raise RuntimeError(f"file too small: {tmp.stat().st_size}")
                tmp.replace(dest)
                print(f"downloaded {dest.name}: {dest.stat().st_size / 1e6:.1f} MB", flush=True)
                return
        except Exception as exc:
            error = exc
            print(f"retry {attempt + 1}: {dest.name}: {exc}", flush=True)
            time.sleep(2 + attempt * 2)
    raise RuntimeError(f"download failed: {url}: {error}")


async def make_voice() -> tuple[Path, list[tuple[float, float, str]]]:
    VOICE.mkdir(parents=True, exist_ok=True)
    silence = VOICE / "silence.mp3"
    run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
        "-t", "0.13", "-q:a", "4", str(silence)
    ])
    silence_duration = duration(silence)

    files: list[Path] = []
    timings: list[tuple[float, float, str]] = []
    cursor = 0.0
    for index, phrase in enumerate(PHRASES):
        part = VOICE / f"part_{index:02d}.mp3"
        await edge_tts.Communicate(
            phrase,
            voice="zh-CN-YunyangNeural",
            rate="-2%",
            pitch="-3Hz",
            volume="+2%",
        ).save(str(part))
        part_duration = duration(part)
        timings.append((cursor, cursor + part_duration, phrase))
        cursor += part_duration
        files.append(part)
        if index < len(PHRASES) - 1:
            files.append(silence)
            cursor += silence_duration

    listing = VOICE / "concat.txt"
    listing.write_text("\n".join(f"file '{p.resolve()}'" for p in files), encoding="utf-8")
    narration = VOICE / "narration.m4a"
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(narration)
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
    punctuation = "，。！？；："
    choices = [i + 1 for i, char in enumerate(text) if char in punctuation and 8 <= i + 1 <= limit + 4]
    cut = choices[-1] if choices else limit
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
Style: Sub,Noto Sans CJK SC,58,&H00FFFFFF,&H00FFFFFF,&H00111111,&H22000000,-1,0,0,0,100,100,0,0,1,4,1,2,60,60,155,1
Style: Title,Noto Sans CJK SC,76,&H00FFFFFF,&H00FFFFFF,&H00111111,&H22000000,-1,0,0,0,100,100,1,0,1,5,2,8,70,70,175,1
Style: End,Noto Sans CJK SC,60,&H00FFFFFF,&H00FFFFFF,&H00111111,&H22000000,-1,0,0,0,100,100,1,0,1,4,1,8,70,70,210,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events: list[str] = []
    title_end = min(timings[0][1] + 0.25, 4.8)
    events.append(
        f"Dialogue: 2,{ass_time(0)},{ass_time(title_end)},Title,,0,0,0,,"
        r"项羽打赢那么多仗\N为什么还是输了天下？"
    )
    for index, (start, end, phrase) in enumerate(timings):
        if index == 0:
            continue
        events.append(
            f"Dialogue: 3,{ass_time(start)},{ass_time(end)},Sub,,0,0,0,,{wrap_cn(phrase)}"
        )
    events.append(
        f"Dialogue: 4,{ass_time(max(0, total - 2.7))},{ass_time(total)},End,,0,0,0,,"
        "你觉得，项羽真正输在哪里？"
    )
    ass.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return ass


def prepare_segment(src: Path, dest: Path, length: float, index: int) -> None:
    src_duration = duration(src)
    room = max(0.0, src_duration - length - 0.1)
    start = (index * 1.47) % room if room > 0.2 else 0.0
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920:(iw-ow)/2:(ih-oh)/2,"
        "fps=30,setsar=1,"
        "eq=contrast=1.06:saturation=0.86:brightness=-0.015,"
        "vignette=PI/6,format=yuv420p"
    )
    cmd = ["ffmpeg", "-y"]
    if src_duration < length + 0.1:
        cmd += ["-stream_loop", "-1"]
    cmd += [
        "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{length:.3f}",
        "-an", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "20", "-pix_fmt", "yuv420p", str(dest)
    ]
    run(cmd)


def render(clips: list[Path], narration: Path, timings: list[tuple[float, float, str]]) -> Path:
    total = duration(narration)
    ass = write_ass(timings, total)
    segment_length = 3.6
    segment_count = int(total // segment_length) + 2
    # Great Wall -> cavalry -> commander -> terracotta -> temple -> fire.
    order = [2, 0, 1, 4, 5, 3, 0, 4, 2, 1, 5, 3, 4, 0, 2, 5, 1, 3]
    segments: list[Path] = []
    for index in range(segment_count):
        src = clips[order[index % len(order)] % len(clips)]
        dest = WORK / f"segment_{index:02d}.mp4"
        prepare_segment(src, dest, segment_length, index)
        segments.append(dest)

    concat = WORK / "video_concat.txt"
    concat.write_text("\n".join(f"file '{p.resolve()}'" for p in segments), encoding="utf-8")
    base = WORK / "base.mp4"
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
        "-t", f"{total:.3f}", "-c:v", "copy", str(base)
    ])

    OUT.mkdir(parents=True, exist_ok=True)
    final = OUT / "项羽为什么打赢那么多仗却输掉天下_竖屏成片_v3.mp4"
    filter_expr = f"subtitles={ass.as_posix()}:fontsdir=/usr/share/fonts/opentype/noto"
    run([
        "ffmpeg", "-y", "-i", str(base), "-i", str(narration),
        "-filter_complex", f"[0:v]{filter_expr}[v]",
        "-map", "[v]", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-shortest", "-movflags", "+faststart", str(final)
    ])

    sheet = OUT / "项羽竖屏成片_v3_画面检查.jpg"
    interval = max(1.0, total / 12.0)
    run([
        "ffmpeg", "-y", "-i", str(final),
        "-vf", f"fps=1/{interval:.4f},scale=270:480,tile=4x3:padding=4:margin=4",
        "-frames:v", "1", "-q:v", "2", str(sheet)
    ])
    return final


def main() -> None:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    CLIPS.mkdir(parents=True)
    OUT.mkdir(parents=True, exist_ok=True)

    clips: list[Path] = []
    for name, url in SOURCES:
        dest = CLIPS / f"{name}.mp4"
        download(url, dest)
        clips.append(dest)

    narration, timings = asyncio.run(make_voice())
    final = render(clips, narration, timings)
    print("FINAL", final, flush=True)
    print(run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration,size",
        "-of", "json", str(final)
    ]), flush=True)


if __name__ == "__main__":
    main()
