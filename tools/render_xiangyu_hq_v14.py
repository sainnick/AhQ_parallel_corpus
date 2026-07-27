#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import render_xiangyu_hq_v13 as v13

base = v13.base

# Avoid the ambiguous TTS pronunciation of “齐地” by using a plain-language equivalent.
base.PHRASES[4] = (
    "结果齐国一带反了，诸侯摇摆，刘邦又从关中杀出来。"
    "项羽就像最强的救火队长，一处刚扑灭，另一处又着了。"
)

SUBTITLE_GROUPS = [list(group) for group in v13.SUBTITLE_GROUPS]
SUBTITLE_GROUPS[4] = [
    "结果齐国一带反了，",
    "诸侯开始摇摆，",
    "刘邦又从关中杀出来。",
    "项羽就像",
    "最强的救火队长：",
    "一处刚扑灭，",
    "另一处又着了。",
]

PUNCTUATION_RE = re.compile(r"[，。！？；：、,.!?;:]")


def caption_text(text: str) -> str:
    return PUNCTUATION_RE.sub("", text).strip()


def write_subtitles(
    timings: list[tuple[float, float, str]],
    total: float,
) -> tuple[Path, list[str]]:
    path = base.WORK / "v14_synced_no_punctuation.ass"
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: One,Noto Sans CJK SC,122,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,90,100,0,0,1,2.4,0,5,20,20,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events: list[str] = []
    report: list[str] = []
    for phrase_index, ((phrase_start, phrase_end, phrase), chunks) in enumerate(
        zip(timings, SUBTITLE_GROUPS),
        start=1,
    ):
        start = phrase_start + 0.055
        end = max(start + 0.1, phrase_end - 0.055)
        available = end - start
        weights = [v13.chunk_weight(chunk) for chunk in chunks]
        total_weight = sum(weights)
        cursor = start
        report.append(f"句{phrase_index:02d} {phrase_start:.3f}-{phrase_end:.3f}s | {phrase}")
        for chunk_index, (chunk, weight) in enumerate(zip(chunks, weights), start=1):
            duration = available * weight / total_weight
            chunk_start = cursor
            chunk_end = end if chunk_index == len(chunks) else cursor + duration
            clean = caption_text(chunk)
            events.append(
                f"Dialogue: 0,{v13.ass_time(chunk_start)},{v13.ass_time(chunk_end)},One,,0,0,0,,"
                f"{{\\an5\\pos(540,1410)}}{clean}"
            )
            report.append(
                f"  {chunk_index:02d} {chunk_start:.3f}-{chunk_end:.3f}s | {clean}"
            )
            cursor = chunk_end
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return path, report


def render(
    clips: list[Path],
    narration: Path,
    timings: list[tuple[float, float, str]],
    report: list[str],
) -> tuple[Path, Path]:
    original_writer = v13.write_subtitles
    v13.write_subtitles = write_subtitles
    try:
        final, sheet = v13.render(clips, narration, timings, report)
    finally:
        v13.write_subtitles = original_writer

    renamed_final = base.OUT / "项羽为什么输给刘邦_无标点读音修正版.mp4"
    renamed_sheet = base.OUT / "项羽无标点读音修正版_视觉检查.jpg"
    if renamed_final.exists():
        renamed_final.unlink()
    if renamed_sheet.exists():
        renamed_sheet.unlink()
    final.replace(renamed_final)
    sheet.replace(renamed_sheet)

    clean_voice = base.OUT / "项羽解说_齐国一带修正版.m4a"
    source_voice = base.OUT / "项羽解说_纯净旁白.m4a"
    if clean_voice.exists():
        clean_voice.unlink()
    if source_voice.exists():
        source_voice.replace(clean_voice)

    for sec in (23, 24, 25):
        base.run([
            "ffmpeg", "-y", "-ss", str(sec), "-i", str(renamed_final),
            "-frames:v", "1", "-q:v", "2", str(base.OUT / f"齐国读音段字幕检查_{sec}秒.jpg"),
        ])

    return renamed_final, renamed_sheet


base.render = render

if __name__ == "__main__":
    raise SystemExit(asyncio.run(base.main()))
