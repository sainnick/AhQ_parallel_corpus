#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import math
import subprocess
from pathlib import Path

import edge_tts

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "xiangyu_hq_v6_work"
DOWNLOADS = WORK / "downloads"
VOICE = WORK / "voice"
SEGMENTS = WORK / "segments"
OUT = ROOT / "out"
FONT_DIR = "/usr/share/fonts/opentype/noto"

# High-resolution Xiang Yu footage candidates. The renderer only accepts >=720p files.
SOURCES = [
    ("hongmen1080", "https://www.bilibili.com/video/BV1vK4y1H7Zo/", "《鸿门宴》1080P项羽战争与人物镜头"),
    ("charge28", "https://www.bilibili.com/video/BV1viw2eQEiG/", "《楚汉传奇》项羽二十八骑突围"),
    ("attackcity", "https://www.bilibili.com/video/BV1szPUeLEQ3/", "《楚汉传奇》项羽攻城人物镜头"),
    ("gaixia", "https://www.bilibili.com/video/BV11B6cB2Eqg/", "《楚汉传奇》垓下决战与乌江"),
    ("promo", "https://www.bilibili.com/video/BV1DoRzYzELK/", "《楚汉传奇》项羽官方宣传片"),
]

PHRASES = [
    "项羽输给刘邦，常被概括成一句：不会用人。可这只说对了一半。",
    "他真正的问题，是能击败敌人，却无法建立一个让胜利长期运转的秩序。",
    "巨鹿和彭城证明，项羽是顶级战场指挥官。",
    "但灭秦以后，他重新分封十八王，地盘和奖惩很快激起新的反叛。",
    "齐地起兵，诸侯摇摆，刘邦还定三秦。项羽每赢一次，都要赶往下一个失火点。",
    "刘邦却把关中粮仓、萧何的后方、韩信的军队和张良的联盟，连成一台能持续补充的战争机器。",
    "所以彭城大胜只是战术奇迹，并没有改变楚汉战争的战略结构。",
    "项羽越能打，整个体系就越依赖他本人；他一离开，局面就开始松动。",
    "刘邦个人未必比项羽强，但他的集团能在主帅失败以后继续运转。",
    "垓下不是项羽突然打输了，而是政治秩序先崩，军事失败最后来结账。",
    "这才是他的悲剧：赢了无数战场，却没建成一个不靠霸王本人也能存在的天下。",
]


def run(cmd: list[str], *, check: bool = True, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    try:
        result = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        print(output[-4000:], flush=True)
        if check:
            raise RuntimeError(f"command timed out: {' '.join(cmd)}") from exc
        return subprocess.CompletedProcess(cmd, 124, output)
    if result.stdout:
        print(result.stdout[-5000:], flush=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(cmd)}")
    return result


def probe(path: Path) -> tuple[int, int, float, int]:
    result = run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,bit_rate:format=duration",
        "-of", "default=noprint_wrappers=1", str(path),
    ])
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return (
        int(values.get("width", "0") or 0),
        int(values.get("height", "0") or 0),
        float(values.get("duration", "0") or 0),
        int(values.get("bit_rate", "0") or 0),
    )


def duration(path: Path) -> float:
    return probe(path)[2]


def valid_hq(path: Path) -> bool:
    try:
        width, height, seconds, _ = probe(path)
        return path.exists() and path.stat().st_size > 1_000_000 and height >= 720 and width >= 1000 and seconds >= 8
    except Exception:
        return False


def download(name: str, url: str) -> Path | None:
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    template = str(DOWNLOADS / f"{name}.%(ext)s")
    cmd = [
        "yt-dlp", "--no-playlist", "--no-warnings",
        "--retries", "5", "--fragment-retries", "5", "--socket-timeout", "30",
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
        "--referer", "https://www.bilibili.com/",
        "--merge-output-format", "mp4",
        "--format-sort", "res:1080,fps,br",
        "-f", "bv*[height>=720][height<=1080]+ba/b[height>=720][height<=1080]/best[height>=720]/best",
        "-o", template, url,
    ]
    run(cmd, check=False, timeout=420)
    candidates = sorted(DOWNLOADS.glob(f"{name}.*"), key=lambda p: p.stat().st_size, reverse=True)
    for candidate in candidates:
        if valid_hq(candidate):
            if candidate.suffix.lower() == ".mp4":
                return candidate
            converted = DOWNLOADS / f"{name}.mp4"
            run([
                "ffmpeg", "-y", "-i", str(candidate),
                "-c:v", "libx264", "-preset", "medium", "-crf", "17",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(converted),
            ], timeout=600)
            return converted if valid_hq(converted) else None
    return None


def collect_sources() -> tuple[list[Path], list[str]]:
    clips: list[Path] = []
    report: list[str] = []
    for name, url, label in SOURCES:
        path = download(name, url)
        if not path:
            report.append(f"FAILED | {label} | {url}")
            continue
        width, height, seconds, bitrate = probe(path)
        report.append(
            f"OK | {label} | {width}x{height} | {seconds:.2f}s | {bitrate/1_000_000:.2f}Mbps | {url}"
        )
        clips.append(path)
    if len(clips) < 3:
        raise RuntimeError("Fewer than three >=720p Xiang Yu video sources were available")
    return clips, report


async def synthesize_voice() -> tuple[Path, list[tuple[float, float, str]]]:
    VOICE.mkdir(parents=True, exist_ok=True)
    gap = VOICE / "gap.mp3"
    run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
        "-t", "0.08", "-q:a", "4", str(gap),
    ])
    gap_duration = duration(gap)

    pieces: list[Path] = []
    timings: list[tuple[float, float, str]] = []
    cursor = 0.0
    for index, phrase in enumerate(PHRASES):
        piece = VOICE / f"part_{index:02d}.mp3"
        await edge_tts.Communicate(
            phrase,
            voice="zh-CN-YunjianNeural",
            rate="+16%",
            pitch="-3Hz",
            volume="+8%",
        ).save(str(piece))
        seconds = duration(piece)
        timings.append((cursor, cursor + seconds, phrase))
        cursor += seconds
        pieces.append(piece)
        if index < len(PHRASES) - 1:
            pieces.append(gap)
            cursor += gap_duration

    concat = VOICE / "voice_concat.txt"
    concat.write_text("\n".join(f"file '{p.resolve()}'" for p in pieces), encoding="utf-8")
    narration = VOICE / "narration.m4a"
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
        "-af",
        "highpass=f=70,acompressor=threshold=-23dB:ratio=4.2:attack=3:release=65,"
        "equalizer=f=135:t=q:w=1.0:g=3.8,equalizer=f=2500:t=q:w=1.0:g=2.6,"
        "loudnorm=I=-13.5:LRA=4:TP=-1.0",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(narration),
    ])
    return narration, timings


def ass_time(seconds: float) -> str:
    centiseconds = max(0, int(round(seconds * 100)))
    hours, rem = divmod(centiseconds, 360000)
    minutes, rem = divmod(rem, 6000)
    secs, cents = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cents:02d}"


def wrap_cn(text: str, limit: int = 17) -> str:
    if len(text) <= limit:
        return text
    choices = [i + 1 for i, ch in enumerate(text) if ch in "，。！？；：" and 8 <= i + 1 <= limit + 5]
    cut = choices[-1] if choices else limit
    return text[:cut] + r"\N" + text[cut:]


def write_subtitles(timings: list[tuple[float, float, str]], total: float) -> Path:
    path = WORK / "subtitles.ass"
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Title,Noto Sans CJK SC,76,&H00FFFFFF,&H00FFFFFF,&H00101010,&H40000000,-1,0,0,0,100,100,0,0,1,5,2,8,55,55,90,1
Style: Sub,Noto Sans CJK SC,57,&H00FFFFFF,&H00FFFFFF,&H000A0A0A,&H6E000000,-1,0,0,0,100,100,0,0,3,2,0,2,65,65,170,1
Style: End,Noto Sans CJK SC,68,&H00FFFFFF,&H00FFFFFF,&H00101010,&H62000000,-1,0,0,0,100,100,1,0,1,5,2,5,60,60,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events: list[str] = [
        f"Dialogue: 5,{ass_time(0)},{ass_time(min(3.4,total))},Title,,0,0,0,,"
        r"{\c&H2C32D9&}项羽真正输掉的\N{\c&HFFFFFF&}不只是一场垓下之战"
    ]
    for start, end, phrase in timings:
        events.append(
            f"Dialogue: 6,{ass_time(start)},{ass_time(end)},Sub,,0,0,0,,{wrap_cn(phrase)}"
        )
    events.append(
        f"Dialogue: 7,{ass_time(max(0,total-2.7))},{ass_time(total)},End,,0,0,0,,"
        r"{\c&H2C32D9&}政治秩序先输\N{\c&HFFFFFF&}军事失败最后结账"
    )
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return path


def make_segment(src: Path, dest: Path, start: float, length: float, index: int) -> None:
    src_duration = duration(src)
    start = max(0.0, min(start, max(0.0, src_duration - length - 0.1)))

    # Preserve source sharpness: a clear 3:2 panel sits over a softly blurred full-frame background.
    fc = (
        "[0:v]split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,gblur=sigma=30,eq=brightness=-0.18:saturation=0.72[bg2];"
        "[fg]scale=1280:720:force_original_aspect_ratio=increase,"
        "crop=1080:720:(iw-ow)/2:(ih-oh)/2,"
        "eq=contrast=1.035:saturation=1.00:brightness=-0.005,"
        "unsharp=5:5:0.24:3:3:0.08[fg2];"
        "[bg2][fg2]overlay=0:330,format=yuv420p[v]"
    )
    run([
        "ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{length:.3f}",
        "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
        "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "17",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-pix_fmt", "yuv420p", str(dest),
    ], timeout=600)


def render(clips: list[Path], narration: Path, timings: list[tuple[float, float, str]], report: list[str]) -> tuple[Path, Path]:
    SEGMENTS.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    total = duration(narration)
    subtitles = write_subtitles(timings, total)

    segment_length = 2.35
    count = math.ceil(total / segment_length) + 1
    clip_durations = [duration(c) for c in clips]
    source_order = [0,1,0,2,1,3,0,4,2,1,3,4,0,2,3,1,4,0,3,2,1,4,3,0,2]
    segments: list[Path] = []
    for index in range(count):
        source_index = source_order[index % len(source_order)] % len(clips)
        usable = max(0.0, clip_durations[source_index] - segment_length - 0.2)
        # Avoid intros and move through the clip rather than reusing one shot.
        start = (3.0 + index * 4.9 + source_index * 7.7) % usable if usable > 4 else 0.0
        segment = SEGMENTS / f"segment_{index:02d}.mp4"
        make_segment(clips[source_index], segment, start, segment_length, index)
        segments.append(segment)

    concat = WORK / "segments.txt"
    concat.write_text("\n".join(f"file '{p.resolve()}'" for p in segments), encoding="utf-8")
    base = WORK / "base.mp4"
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
        "-t", f"{total:.3f}", "-c", "copy", str(base),
    ])

    final = OUT / "项羽为什么输给刘邦_高清深度解说版.mp4"
    # Original dialogue/ambience remains faintly audible under the new narration.
    fc = (
        f"[0:v]subtitles={subtitles.as_posix()}:fontsdir={FONT_DIR}[v];"
        "[0:a]volume=0.10,highpass=f=90[orig];"
        "[1:a]volume=1.0[voice];"
        "[voice][orig]amix=inputs=2:duration=first:dropout_transition=0,alimiter=limit=0.96[a]"
    )
    run([
        "ffmpeg", "-y", "-i", str(base), "-i", str(narration),
        "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "17",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", "-shortest", str(final),
    ], timeout=1200)

    sheet = OUT / "项羽高清深度解说版_画面检查.jpg"
    interval = max(1.0, total / 12)
    run([
        "ffmpeg", "-y", "-i", str(final),
        "-vf", f"fps=1/{interval:.4f},scale=270:480,tile=4x3:padding=4:margin=4",
        "-frames:v", "1", "-q:v", "2", str(sheet),
    ])
    (OUT / "高清素材检测报告.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    (OUT / "解说文案.txt").write_text("\n".join(PHRASES) + "\n", encoding="utf-8")
    return final, sheet


async def main() -> int:
    for path in (WORK, DOWNLOADS, VOICE, SEGMENTS, OUT):
        path.mkdir(parents=True, exist_ok=True)
    clips, report = collect_sources()
    narration, timings = await synthesize_voice()
    final, sheet = render(clips, narration, timings, report)
    print(f"FINAL={final}")
    print(f"SHEET={sheet}")
    print(f"DURATION={duration(final):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
