#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import render_xiangyu_hq_v11 as v11

base = v11.base


def subtitle_chunks(text: str, max_chars: int = 22) -> list[str]:
    clauses = re.findall(r"[^，。！？；：]+[，。！？；：]?", text)
    chunks: list[str] = []
    current = ""
    for clause in clauses:
        if len(current) + len(clause) <= max_chars:
            current += clause
        else:
            if current:
                chunks.append(current)
            current = clause
        while len(current) > max_chars:
            chunks.append(current[:max_chars])
            current = current[max_chars:]
    if current:
        chunks.append(current)
    return chunks or [text]


def wrap_two_lines(text: str, line_chars: int = 12) -> str:
    if len(text) <= line_chars:
        return text
    cut = line_chars
    for i in range(min(line_chars + 2, len(text) - 1), max(6, line_chars - 4), -1):
        if text[i - 1] in "，。！？；：":
            cut = i
            break
    return text[:cut] + r"\N" + text[cut:]


def write_subtitles(timings: list[tuple[float, float, str]], total: float) -> Path:
    path = base.WORK / "v12_subtitles.ass"
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Title,Noto Sans CJK SC,84,&H00FFFFFF,&H00FFFFFF,&H00101010,&H48000000,-1,0,0,0,100,100,0,0,1,6,2,8,45,45,82,1
Style: Sub,Noto Sans CJK SC,66,&H00FFFFFF,&H00FFFFFF,&H00060606,&H78000000,-1,0,0,0,100,100,0,0,3,2,0,2,50,50,128,1
Style: End,Noto Sans CJK SC,74,&H00FFFFFF,&H00FFFFFF,&H00101010,&H68000000,-1,0,0,0,100,100,1,0,1,6,2,5,50,50,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events = [
        f"Dialogue: 5,{base.ass_time(0)},{base.ass_time(min(3.2,total))},Title,,0,0,0,,"
        r"{\c&H2C32D9&}项羽真正输掉的\N{\c&HFFFFFF&}不只是一场垓下之战"
    ]
    for start, end, phrase in timings:
        chunks = subtitle_chunks(phrase)
        weights = [max(1, len(chunk)) for chunk in chunks]
        total_weight = sum(weights)
        cursor = start
        for index, (chunk, weight) in enumerate(zip(chunks, weights)):
            chunk_end = end if index == len(chunks) - 1 else cursor + (end - start) * weight / total_weight
            events.append(
                f"Dialogue: 6,{base.ass_time(cursor)},{base.ass_time(chunk_end)},Sub,,0,0,0,,{wrap_two_lines(chunk)}"
            )
            cursor = chunk_end
    events.append(
        f"Dialogue: 7,{base.ass_time(max(0,total-2.6))},{base.ass_time(total)},End,,0,0,0,,"
        r"{\c&H2C32D9&}个人再强\N{\c&HFFFFFF&}也替代不了一套能运转的办法"
    )
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return path


def make_segment(src: Path, dest: Path, start: float, length: float, index: int) -> None:
    duration = base.duration(src)
    start = max(0.0, min(start, max(0.0, duration - length - 0.1)))
    biases = [0.50, 0.44, 0.56, 0.47, 0.53]
    bias = biases[index % len(biases)]
    # Remove the source programme's bottom captions before creating the large central crop.
    filter_complex = (
        "[0:v]crop=iw:ih-42:0:0,split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "gblur=sigma=31,eq=brightness=-0.19:saturation=0.72[bg2];"
        "[fg]hqdn3d=0.9:0.9:2.2:2.2,scale=-2:1180:flags=lanczos,"
        f"crop=1080:1180:(iw-ow)*{bias}:(ih-oh)/2,"
        "unsharp=5:5:0.46:3:3:0.14,eq=contrast=1.045:saturation=1.00[fg2];"
        "[bg2][fg2]overlay=0:180,format=yuv420p[v]"
    )
    base.run([
        "ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{length:.3f}",
        "-filter_complex", filter_complex, "-map", "[v]", "-map", "0:a?", "-r", "30",
        "-c:v", "libx264", "-preset", "medium", "-crf", "16",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-pix_fmt", "yuv420p", str(dest),
    ], timeout=600)


v11.write_subtitles = write_subtitles
v11.make_segment = make_segment

if __name__ == "__main__":
    raise SystemExit(asyncio.run(base.main()))
