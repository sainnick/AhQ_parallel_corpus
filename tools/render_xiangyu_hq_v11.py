#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import math
from pathlib import Path

import edge_tts

import render_xiangyu_hq_v6 as base
import render_xiangyu_hq_v8  # installs CCTV collector into base

base.PHRASES = [
    "项羽为什么输？如果只说他不会用人，还是太简单了。",
    "巨鹿、彭城两战说明，他打仗几乎没人能比。",
    "可打赢一仗，只能赶走眼前的敌人；想坐稳天下，还得让各路人愿意长期跟着你。",
    "灭秦以后，项羽重新分地盘，可谁多拿、谁少拿，没有形成一套让大家服气的规矩。",
    "结果齐地反了，诸侯摇摆，刘邦又从关中杀出来。项羽就像最强的救火队长，一处刚扑灭，另一处又着了。",
    "刘邦本人没项羽能打，可他会把事情拆开：萧何管粮，韩信带兵，张良拉盟友。",
    "彭城之战，项羽三万打退几十万，赢得漂亮，却没切断刘邦继续补兵、补粮的能力。",
    "所以项羽一走，局面就容易散；刘邦就算打败仗，他的人和后方仍然能运转。",
    "垓下并不是项羽突然变弱，而是前面的地盘、人才和后勤问题，一起找上门。",
    "项羽输的不是勇气，而是没把个人的强，变成一套不靠他也能运转的办法。",
]

PLANS = [
    [("gaixia", 4.0), ("gaixia", 17.0)],
    [("julu", 5.0), ("julu", 27.0), ("pengcheng", 44.0)],
    [("julu", 38.0), ("pengcheng", 29.0), ("pengcheng", 66.0)],
    [("fanzeng", 0.0), ("fanzeng", 9.0), ("pengcheng", 34.0)],
    [("julu", 72.0), ("julu", 82.0), ("pengcheng", 83.0)],
    [("pengcheng", 20.0), ("pengcheng", 46.0), ("fanzeng", 49.0)],
    [("julu", 88.0), ("pengcheng", 78.0), ("pengcheng", 91.0)],
    [("fanzeng", 45.0), ("fanzeng", 55.0), ("gaixia", 72.0)],
    [("gaixia", 0.0), ("gaixia", 20.0), ("gaixia", 82.0)],
    [("farewell", 0.0), ("farewell", 16.0), ("farewell", 48.0), ("farewell", 82.0)],
]


async def synthesize_voice() -> tuple[Path, list[tuple[float, float, str]]]:
    base.VOICE.mkdir(parents=True, exist_ok=True)
    gap = base.VOICE / "v11_gap.mp3"
    base.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "0.07", "-q:a", "4", str(gap)])
    gap_d = base.duration(gap)
    pieces: list[Path] = []
    timings: list[tuple[float, float, str]] = []
    cursor = 0.0
    for i, phrase in enumerate(base.PHRASES):
        part = base.VOICE / f"v11_{i:02d}.mp3"
        await edge_tts.Communicate(
            phrase,
            voice="zh-CN-YunjianNeural",
            rate="+20%",
            pitch="-4Hz",
            volume="+10%",
        ).save(str(part))
        d = base.duration(part)
        timings.append((cursor, cursor + d, phrase))
        cursor += d
        pieces.append(part)
        if i < len(base.PHRASES) - 1:
            pieces.append(gap)
            cursor += gap_d
    listing = base.VOICE / "v11_voice.txt"
    listing.write_text("\n".join(f"file '{p.resolve()}'" for p in pieces), encoding="utf-8")
    narration = base.VOICE / "v11_narration.m4a"
    base.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-af", "highpass=f=65,acompressor=threshold=-24dB:ratio=4.3:attack=2:release=55,"
               "equalizer=f=125:t=q:w=1.0:g=4.2,equalizer=f=2300:t=q:w=1.0:g=2.6,"
               "loudnorm=I=-13:LRA=3.5:TP=-0.9",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(narration),
    ])
    return narration, timings


def write_subtitles(timings: list[tuple[float, float, str]], total: float) -> Path:
    path = base.WORK / "v11_subtitles.ass"
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Title,Noto Sans CJK SC,84,&H00FFFFFF,&H00FFFFFF,&H00101010,&H48000000,-1,0,0,0,100,100,0,0,1,6,2,8,45,45,82,1
Style: Sub,Noto Sans CJK SC,68,&H00FFFFFF,&H00FFFFFF,&H00060606,&H78000000,-1,0,0,0,100,100,0,0,3,2,0,2,48,48,130,1
Style: End,Noto Sans CJK SC,76,&H00FFFFFF,&H00FFFFFF,&H00101010,&H68000000,-1,0,0,0,100,100,1,0,1,6,2,5,50,50,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events = [
        f"Dialogue: 5,{base.ass_time(0)},{base.ass_time(min(3.2,total))},Title,,0,0,0,,"
        r"{\c&H2C32D9&}项羽真正输掉的\N{\c&HFFFFFF&}不只是一场垓下之战"
    ]
    for start, end, phrase in timings:
        events.append(f"Dialogue: 6,{base.ass_time(start)},{base.ass_time(end)},Sub,,0,0,0,,{base.wrap_cn(phrase,15)}")
    events.append(
        f"Dialogue: 7,{base.ass_time(max(0,total-2.6))},{base.ass_time(total)},End,,0,0,0,,"
        r"{\c&H2C32D9&}个人再强\N{\c&HFFFFFF&}也替代不了一套能运转的办法"
    )
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return path


def make_segment(src: Path, dest: Path, start: float, length: float, index: int) -> None:
    d = base.duration(src)
    start = max(0.0, min(start, max(0.0, d - length - 0.1)))
    biases = [0.50, 0.44, 0.56, 0.47, 0.53]
    bias = biases[index % len(biases)]
    fc = (
        "[0:v]split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "gblur=sigma=31,eq=brightness=-0.19:saturation=0.72[bg2];"
        "[fg]hqdn3d=0.9:0.9:2.2:2.2,scale=2100:1180:flags=lanczos,"
        f"crop=1080:1180:(iw-ow)*{bias}:(ih-oh)/2,"
        "unsharp=5:5:0.46:3:3:0.14,eq=contrast=1.045:saturation=1.00[fg2];"
        "[bg2][fg2]overlay=0:180,format=yuv420p[v]"
    )
    base.run([
        "ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{length:.3f}",
        "-filter_complex", fc, "-map", "[v]", "-map", "0:a?", "-r", "30",
        "-c:v", "libx264", "-preset", "medium", "-crf", "16",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-pix_fmt", "yuv420p", str(dest),
    ], timeout=600)


def render(clips: list[Path], narration: Path, timings: list[tuple[float, float, str]], report: list[str]) -> tuple[Path, Path]:
    base.SEGMENTS.mkdir(parents=True, exist_ok=True)
    base.OUT.mkdir(parents=True, exist_ok=True)
    total = base.duration(narration)
    subtitles = write_subtitles(timings, total)
    named = {p.stem: p for p in clips}
    parts: list[Path] = []
    index = 0
    for phrase_i, ((start_t, end_t, _), shots) in enumerate(zip(timings, PLANS)):
        phrase_length = end_t - start_t
        shot_length = phrase_length / len(shots)
        for shot_i, (name, start) in enumerate(shots):
            src = named.get(name)
            if src is None:
                src = clips[["julu", "pengcheng", "fanzeng", "gaixia", "farewell"].index(name) % len(clips)]
            length = shot_length + (0.02 if shot_i == len(shots) - 1 else 0)
            out = base.SEGMENTS / f"v11_{index:02d}.mp4"
            make_segment(src, out, start, length, index)
            parts.append(out)
            index += 1
        if phrase_i < len(PLANS) - 1:
            src = named.get(shots[-1][0], clips[0])
            out = base.SEGMENTS / f"v11_{index:02d}.mp4"
            make_segment(src, out, shots[-1][1] + shot_length, 0.07, index)
            parts.append(out)
            index += 1
    listing = base.WORK / "v11_segments.txt"
    listing.write_text("\n".join(f"file '{p.resolve()}'" for p in parts), encoding="utf-8")
    base_video = base.WORK / "v11_base.mp4"
    base.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-t", f"{total:.3f}", "-c", "copy", str(base_video)])
    final = base.OUT / "项羽为什么输给刘邦_大画面通俗深度版.mp4"
    mix = (
        f"[0:v]subtitles={subtitles.as_posix()}:fontsdir={base.FONT_DIR}[v];"
        "[0:a]volume=0.10,highpass=f=100[orig];[1:a]volume=1.0[voice];"
        "[voice][orig]amix=inputs=2:duration=first:dropout_transition=0,alimiter=limit=0.96[a]"
    )
    base.run([
        "ffmpeg", "-y", "-i", str(base_video), "-i", str(narration), "-filter_complex", mix,
        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "slow", "-crf", "16",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", "-shortest", str(final),
    ], timeout=1200)
    sheet = base.OUT / "项羽大画面通俗深度版_视觉检查.jpg"
    interval = max(1.0, total / 12)
    base.run([
        "ffmpeg", "-y", "-i", str(final),
        "-vf", f"fps=1/{interval:.4f},scale=270:480,tile=4x3:padding=4:margin=4",
        "-frames:v", "1", "-q:v", "2", str(sheet),
    ])
    for sec in (5, 22, 42):
        base.run(["ffmpeg", "-y", "-ss", str(sec), "-i", str(final), "-frames:v", "1", "-q:v", "2", str(base.OUT / f"视觉检查_{sec}秒.jpg")])
    (base.OUT / "通俗深度解说文案.txt").write_text("\n".join(base.PHRASES) + "\n", encoding="utf-8")
    (base.OUT / "素材检测报告.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    return final, sheet


base.synthesize_voice = synthesize_voice
base.render = render

if __name__ == "__main__":
    raise SystemExit(asyncio.run(base.main()))
