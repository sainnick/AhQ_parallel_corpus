#!/usr/bin/env python3
from __future__ import annotations

import asyncio
from pathlib import Path

import render_xiangyu_hq_v11 as v11

base = v11.base

# Each subtitle group is reset to the exact synthesized duration of its sentence.
# This prevents the cumulative drift caused by distributing all captions across the whole video.
SUBTITLE_GROUPS = [
    ["项羽为什么输？", "如果只说他不会用人，", "还是太简单了。"],
    ["巨鹿、彭城两战说明，", "他打仗几乎没人能比。"],
    ["可打赢一仗，", "只能赶走眼前的敌人；", "想坐稳天下，", "还得让各路人", "愿意长期跟着你。"],
    ["灭秦以后，", "项羽重新分地盘。", "可谁多拿、谁少拿，", "没有一套", "让大家服气的规矩。"],
    ["结果齐地反了，", "诸侯开始摇摆，", "刘邦又从关中杀出来。", "项羽就像", "最强的救火队长：", "一处刚扑灭，", "另一处又着了。"],
    ["刘邦本人没项羽能打，", "但他会把事情拆开：", "萧何管粮，", "韩信带兵，", "张良拉盟友。"],
    ["彭城之战，", "项羽三万打退几十万。", "赢得很漂亮，", "却没切断刘邦", "继续补兵、补粮", "的能力。"],
    ["所以项羽一走，", "局面就容易散；", "刘邦就算打败仗，", "他的人和后方", "仍然能够运转。"],
    ["垓下并不是", "项羽突然变弱，", "而是前面的地盘、", "人才和后勤问题，", "一起找上门。"],
    ["项羽输的不是勇气，", "而是没把个人的强，", "变成一套", "不靠他也能运转", "的办法。"],
]


def ass_time(seconds: float) -> str:
    return base.ass_time(max(0.0, seconds))


def chunk_weight(text: str) -> float:
    # Punctuation receives a little extra time so captions turn at natural speech pauses.
    punctuation = sum(text.count(mark) for mark in "，。！？；：")
    return max(3.0, len(text) + punctuation * 1.6)


def write_subtitles(timings: list[tuple[float, float, str]], total: float) -> tuple[Path, list[str]]:
    path = base.WORK / "v13_synced_subtitles.ass"
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
    for phrase_index, ((phrase_start, phrase_end, phrase), chunks) in enumerate(zip(timings, SUBTITLE_GROUPS), start=1):
        # Keep the first and last few milliseconds free for TTS encoder padding.
        start = phrase_start + 0.055
        end = max(start + 0.1, phrase_end - 0.055)
        available = end - start
        weights = [chunk_weight(chunk) for chunk in chunks]
        total_weight = sum(weights)
        cursor = start
        report.append(f"句{phrase_index:02d} {phrase_start:.3f}-{phrase_end:.3f}s | {phrase}")
        for chunk_index, (chunk, weight) in enumerate(zip(chunks, weights), start=1):
            duration = available * weight / total_weight
            chunk_start = cursor
            chunk_end = end if chunk_index == len(chunks) else cursor + duration
            events.append(
                f"Dialogue: 0,{ass_time(chunk_start)},{ass_time(chunk_end)},One,,0,0,0,,"
                f"{{\\an5\\pos(540,1410)}}{chunk}"
            )
            report.append(f"  {chunk_index:02d} {chunk_start:.3f}-{chunk_end:.3f}s | {chunk}")
            cursor = chunk_end
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return path, report


def render(clips: list[Path], narration: Path, timings: list[tuple[float, float, str]], report: list[str]) -> tuple[Path, Path]:
    base.SEGMENTS.mkdir(parents=True, exist_ok=True)
    base.OUT.mkdir(parents=True, exist_ok=True)
    total = base.duration(narration)
    subtitles, sync_report = write_subtitles(timings, total)
    named = {p.stem: p for p in clips}
    parts: list[Path] = []
    index = 0
    for phrase_i, ((start_t, end_t, _), shots) in enumerate(zip(timings, v11.PLANS)):
        phrase_length = end_t - start_t
        shot_length = phrase_length / len(shots)
        for shot_i, (name, shot_start) in enumerate(shots):
            src = named.get(name)
            if src is None:
                src = clips[["julu", "pengcheng", "fanzeng", "gaixia", "farewell"].index(name) % len(clips)]
            length = shot_length + (0.02 if shot_i == len(shots) - 1 else 0)
            out = base.SEGMENTS / f"v13_{index:02d}.mp4"
            v11.make_segment(src, out, shot_start, length, index)
            parts.append(out)
            index += 1
        if phrase_i < len(v11.PLANS) - 1:
            src = named.get(shots[-1][0], clips[0])
            out = base.SEGMENTS / f"v13_{index:02d}.mp4"
            v11.make_segment(src, out, shots[-1][1] + shot_length, 0.07, index)
            parts.append(out)
            index += 1

    listing = base.WORK / "v13_segments.txt"
    listing.write_text("\n".join(f"file '{p.resolve()}'" for p in parts), encoding="utf-8")
    base_video = base.WORK / "v13_base.mp4"
    base.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-t", f"{total:.3f}", "-c", "copy", str(base_video),
    ])

    final = base.OUT / "项羽为什么输给刘邦_字幕配音校准版.mp4"
    # Use the clean narration track only. The previous version mixed film dialogue under it,
    # which made the narrator sound weak and created apparent dubbing errors.
    video_filter = (
        "[0:v]"
        "drawbox=x=0:y=1268:w=iw:h=328:color=black@0.98:t=fill,"
        "drawbox=x=0:y=1666:w=iw:h=194:color=black@0.98:t=fill,"
        f"subtitles={subtitles.as_posix()}:fontsdir={base.FONT_DIR}[v]"
    )
    base.run([
        "ffmpeg", "-y", "-i", str(base_video), "-i", str(narration),
        "-filter_complex", video_filter,
        "-map", "[v]", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "slow", "-crf", "16",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-af", "alimiter=limit=0.96",
        "-movflags", "+faststart", "-shortest", str(final),
    ], timeout=1200)

    # Export the clean narration for direct audio inspection.
    clean_voice = base.OUT / "项羽解说_纯净旁白.m4a"
    base.run(["ffmpeg", "-y", "-i", str(narration), "-c:a", "copy", str(clean_voice)])

    sheet = base.OUT / "项羽字幕配音校准版_视觉检查.jpg"
    interval = max(1.0, total / 12)
    base.run([
        "ffmpeg", "-y", "-i", str(final),
        "-vf", f"fps=1/{interval:.4f},scale=270:480,tile=4x3:padding=4:margin=4",
        "-frames:v", "1", "-q:v", "2", str(sheet),
    ])
    for sec in (3, 8, 16, 23, 32, 40, 48, 56, 62):
        base.run([
            "ffmpeg", "-y", "-ss", str(sec), "-i", str(final),
            "-frames:v", "1", "-q:v", "2", str(base.OUT / f"同步检查_{sec}秒.jpg"),
        ])
    (base.OUT / "字幕配音校准表.txt").write_text("\n".join(sync_report) + "\n", encoding="utf-8")
    (base.OUT / "通俗深度解说文案.txt").write_text("\n".join(base.PHRASES) + "\n", encoding="utf-8")
    (base.OUT / "素材检测报告.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    return final, sheet


base.render = render

if __name__ == "__main__":
    raise SystemExit(asyncio.run(base.main()))
