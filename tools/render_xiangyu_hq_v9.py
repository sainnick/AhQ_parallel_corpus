#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import math
from pathlib import Path

import edge_tts

import render_xiangyu_hq_v6 as base
import render_xiangyu_hq_v8  # installs the CCTV high-bitrate collector into base

base.PHRASES = [
    "项羽为什么输？如果只说他不会用人，还是太浅了。",
    "巨鹿、彭城证明，他几乎是那个时代最强的战场指挥官。",
    "但军事胜利解决的是敌人，争天下还要解决秩序。",
    "灭秦后，项羽分封十八王，却没让功劳、地盘和利益形成稳定规则。",
    "齐地反叛，诸侯摇摆，刘邦还定三秦。项羽像最强的救火队长，却永远在赶往下一场火。",
    "刘邦做的恰好相反：萧何守关中和粮道，韩信扩大战线，张良重组联盟。",
    "彭城之战，项羽三万破数十万，是战术巅峰，却无法逆转对方不断补充的体系。",
    "项羽的集团越依赖霸王本人，就越经不起他离开；刘邦本人可以败，他的机器仍然运转。",
    "所以垓下不是突然失手，而是政治秩序先输，军事失败最后结账。",
    "项羽赢了很多战场，却没建成一个不靠项羽也能存在的天下。",
]


async def synthesize_voice() -> tuple[Path, list[tuple[float, float, str]]]:
    base.VOICE.mkdir(parents=True, exist_ok=True)
    gap = base.VOICE / "gap_v9.mp3"
    base.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
        "-t", "0.06", "-q:a", "4", str(gap),
    ])
    gap_duration = base.duration(gap)
    pieces: list[Path] = []
    timings: list[tuple[float, float, str]] = []
    cursor = 0.0
    for index, phrase in enumerate(base.PHRASES):
        piece = base.VOICE / f"v9_part_{index:02d}.mp3"
        await edge_tts.Communicate(
            phrase,
            voice="zh-CN-YunjianNeural",
            rate="+22%",
            pitch="-5Hz",
            volume="+10%",
        ).save(str(piece))
        seconds = base.duration(piece)
        timings.append((cursor, cursor + seconds, phrase))
        cursor += seconds
        pieces.append(piece)
        if index < len(base.PHRASES) - 1:
            pieces.append(gap)
            cursor += gap_duration
    concat = base.VOICE / "v9_voice_concat.txt"
    concat.write_text("\n".join(f"file '{p.resolve()}'" for p in pieces), encoding="utf-8")
    narration = base.VOICE / "narration_v9.m4a"
    base.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
        "-af",
        "highpass=f=65,acompressor=threshold=-24dB:ratio=4.5:attack=2:release=55,"
        "equalizer=f=120:t=q:w=1.0:g=4.6,equalizer=f=2100:t=q:w=1.0:g=2.8,"
        "equalizer=f=6500:t=q:w=1.3:g=1.4,loudnorm=I=-13:LRA=3.5:TP=-0.9",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(narration),
    ])
    return narration, timings


def write_subtitles(timings: list[tuple[float, float, str]], total: float) -> Path:
    path = base.WORK / "subtitles_v9.ass"
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Title,Noto Sans CJK SC,78,&H00FFFFFF,&H00FFFFFF,&H00101010,&H45000000,-1,0,0,0,100,100,0,0,1,5,2,8,55,55,92,1
Style: Sub,Noto Sans CJK SC,58,&H00FFFFFF,&H00FFFFFF,&H00080808,&H72000000,-1,0,0,0,100,100,0,0,3,2,0,2,62,62,178,1
Style: End,Noto Sans CJK SC,69,&H00FFFFFF,&H00FFFFFF,&H00101010,&H65000000,-1,0,0,0,100,100,1,0,1,5,2,5,60,60,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events = [
        f"Dialogue: 5,{base.ass_time(0)},{base.ass_time(min(3.1,total))},Title,,0,0,0,,"
        r"{\c&H2C32D9&}项羽真正输掉的\N{\c&HFFFFFF&}是战场之外的秩序"
    ]
    for start, end, phrase in timings:
        events.append(
            f"Dialogue: 6,{base.ass_time(start)},{base.ass_time(end)},Sub,,0,0,0,,{base.wrap_cn(phrase,17)}"
        )
    events.append(
        f"Dialogue: 7,{base.ass_time(max(0,total-2.5))},{base.ass_time(total)},End,,0,0,0,,"
        r"{\c&H2C32D9&}政治秩序先输\N{\c&HFFFFFF&}军事失败最后结账"
    )
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return path


def make_segment(src: Path, dest: Path, start: float, length: float, index: int) -> None:
    source_duration = base.duration(src)
    start = max(0.0, min(start, max(0.0, source_duration - length - 0.1)))
    # Keep the clear panel close to its native detail level instead of stretching 480p across the whole phone screen.
    filter_complex = (
        "[0:v]split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "gblur=sigma=34,eq=brightness=-0.22:saturation=0.70[bg2];"
        "[fg]hqdn3d=1.2:1.2:3:3,scale=960:540:flags=lanczos,"
        "unsharp=5:5:0.42:3:3:0.14,eq=contrast=1.045:saturation=1.00[fg2];"
        "[bg2][fg2]overlay=60:405,format=yuv420p[v]"
    )
    base.run([
        "ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{length:.3f}",
        "-filter_complex", filter_complex, "-map", "[v]", "-map", "0:a?", "-r", "30",
        "-c:v", "libx264", "-preset", "medium", "-crf", "16",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-pix_fmt", "yuv420p", str(dest),
    ], timeout=600)


def render(clips: list[Path], narration: Path, timings: list[tuple[float, float, str]], report: list[str]) -> tuple[Path, Path]:
    base.SEGMENTS.mkdir(parents=True, exist_ok=True)
    base.OUT.mkdir(parents=True, exist_ok=True)
    total = base.duration(narration)
    subtitles = write_subtitles(timings, total)
    segment_length = 2.05
    count = math.ceil(total / segment_length) + 1
    clip_durations = [base.duration(c) for c in clips]
    source_order = [0,1,0,1,2,0,3,1,2,4,0,1,3,2,4,1,3,0,4,2,3,1,4,0,2,3]
    parts: list[Path] = []
    for index in range(count):
        source_index = source_order[index % len(source_order)] % len(clips)
        usable = max(0.0, clip_durations[source_index] - segment_length - 0.2)
        # Skip the documentary introductions and interview sections; favor later dramatized sequences.
        lower = min(42.0, max(0.0, usable * 0.35))
        span = max(1.0, usable - lower)
        start = lower + ((index * 5.7 + source_index * 11.3) % span)
        segment = base.SEGMENTS / f"v9_segment_{index:02d}.mp4"
        make_segment(clips[source_index], segment, start, segment_length, index)
        parts.append(segment)
    listing = base.WORK / "v9_segments.txt"
    listing.write_text("\n".join(f"file '{p.resolve()}'" for p in parts), encoding="utf-8")
    base_video = base.WORK / "v9_base.mp4"
    base.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-t", f"{total:.3f}", "-c", "copy", str(base_video),
    ])
    final = base.OUT / "项羽为什么输给刘邦_清晰深度强节奏版.mp4"
    mix = (
        f"[0:v]subtitles={subtitles.as_posix()}:fontsdir={base.FONT_DIR}[v];"
        "[0:a]volume=0.14,highpass=f=100[orig];[1:a]volume=1.0[voice];"
        "[voice][orig]amix=inputs=2:duration=first:dropout_transition=0,alimiter=limit=0.96[a]"
    )
    base.run([
        "ffmpeg", "-y", "-i", str(base_video), "-i", str(narration),
        "-filter_complex", mix, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "16",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
        "-shortest", str(final),
    ], timeout=1200)
    sheet = base.OUT / "项羽清晰深度强节奏版_画面检查.jpg"
    interval = max(1.0, total / 12)
    base.run([
        "ffmpeg", "-y", "-i", str(final),
        "-vf", f"fps=1/{interval:.4f},scale=270:480,tile=4x3:padding=4:margin=4",
        "-frames:v", "1", "-q:v", "2", str(sheet),
    ])
    (base.OUT / "高清素材检测报告.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    (base.OUT / "深度解说文案.txt").write_text("\n".join(base.PHRASES) + "\n", encoding="utf-8")
    return final, sheet


base.synthesize_voice = synthesize_voice
base.render = render

if __name__ == "__main__":
    raise SystemExit(asyncio.run(base.main()))
