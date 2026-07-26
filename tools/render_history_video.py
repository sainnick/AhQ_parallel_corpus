#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import html as html_lib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
import edge_tts

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "history_render_work"
CLIPS = WORK / "clips"
VOICE = WORK / "voice"
OUT = ROOT / "out"
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"

PHRASES = [
    "项羽打赢那么多仗，为什么最后还是输掉了天下？",
    "巨鹿一战，他破釜沉舟，打出了诸侯都不敢正视的威名。",
    "可最后坐上天下之主位置的，却是经常被他打退的刘邦。",
    "项羽输的，不是勇武，也不只是某一场战役。",
    "他真正的问题，是没能把一场场胜利，变成稳定的组织。",
    "进入关中以后，他分封十八路诸侯，看似重新安排了天下。",
    "但分封很快引发新的混战，很多盟友也不再愿意追随他。",
    "项羽能在战场上决定一切，却不擅长让不同利益长期合作。",
    "对人才，他也常常不能真正放权。",
    "韩信在楚营得不到重用，后来转投刘邦。",
    "陈平也离开项羽，成了刘邦的重要谋士。",
    "反过来看刘邦，他自己未必最能打。",
    "却能让萧何管后方，张良定谋略，韩信领兵。",
    "项羽依靠个人威望，刘邦依靠一群人建立体系。",
    "所以垓下之败，只是最后呈现出来的结果。",
    "真正的胜负，早在用人和组织上就已经分出来了。",
    "项羽把天下当成了战场，却没把人心当成根基。",
    "这才是他打赢许多仗，却输掉天下的真正原因。",
]

PEXELS = [
    ("cavalry", "9466314", "https://www.pexels.com/video/a-group-of-men-riding-a-horse-9466314/"),
    ("horse_commander", "9466524", "https://www.pexels.com/video/a-man-riding-a-horse-9466524/"),
    ("terracotta", "36926090", "https://www.pexels.com/video/terracotta-warriors-in-xi-an-china-36926090/"),
    ("great_wall", "1193306", "https://www.pexels.com/video/the-great-wall-of-china-1193306/"),
    ("fire", "11574595", "https://www.pexels.com/video/top-view-of-fire-11574595/"),
]

PIXABAY = [
    ("xian", "https://pixabay.com/videos/china-xian-terracotta-xian-80606/"),
    ("chinese_gate", "https://pixabay.com/videos/archway-sculptures-lions-tree-73743/"),
    ("sage_statue", "https://pixabay.com/videos/wise-man-ancient-chinese-sage-183843/"),
]

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def ffprobe_duration(path: Path) -> float:
    p = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path)
    ])
    return float(p.stdout.strip())


def download(url: str, dest: Path, *, referer: str | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 100_000:
        print(f"reuse {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")
        return
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with SESSION.get(url, headers=headers, stream=True, timeout=(20, 180), allow_redirects=True) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                with tmp.open("wb") as f:
                    for chunk in r.iter_content(1024 * 1024):
                        if chunk:
                            f.write(chunk)
                if tmp.stat().st_size < 100_000:
                    raise RuntimeError(f"download too small: {tmp.stat().st_size}")
                tmp.replace(dest)
                print(f"downloaded {dest.name}: {dest.stat().st_size / 1e6:.1f} MB")
                return
        except Exception as exc:
            last_error = exc
            print(f"download retry {attempt + 1}: {url}: {exc}")
            time.sleep(2 + attempt * 2)
    raise RuntimeError(f"failed to download {url}: {last_error}")


def normalize_embedded_urls(text: str) -> str:
    text = html_lib.unescape(text)
    text = text.replace("\\u002F", "/").replace("\\/", "/")
    text = text.replace("\\u0026", "&")
    return text


def url_dims(url: str) -> tuple[int, int]:
    name = Path(urlparse(url).path).name
    matches = re.findall(r"(?:uhd|hd|sd)_([0-9]{3,4})_([0-9]{3,4})", name)
    if matches:
        return int(matches[-1][0]), int(matches[-1][1])
    return (0, 0)


def head_size(url: str, referer: str) -> int:
    try:
        r = SESSION.head(url, headers={"User-Agent": UA, "Referer": referer}, timeout=20, allow_redirects=True)
        if r.status_code == 200:
            return int(r.headers.get("content-length", "0") or 0)
    except Exception:
        pass
    return 0


def derive_pexels_variants(url: str) -> list[str]:
    parsed = urlparse(url)
    name = Path(parsed.path).name
    m = re.match(r"(\d+)-(?:uhd|hd|sd)_([0-9]{3,4})_([0-9]{3,4})_([0-9]+fps)\.mp4", name)
    if not m:
        return [url]
    vid, w, h, fps = m.groups()
    w_i, h_i = int(w), int(h)
    vertical = h_i > w_i
    dims = [(1080, 1920), (720, 1280), (1920, 1080), (1280, 720)] if vertical else [(1920, 1080), (1280, 720), (1080, 1920), (720, 1280)]
    base = str(Path(parsed.path).parent)
    result: list[str] = []
    for dw, dh in dims:
        quality = "hd" if max(dw, dh) >= 1080 else "sd"
        result.append(f"{parsed.scheme}://{parsed.netloc}{base}/{vid}-{quality}_{dw}_{dh}_{fps}.mp4")
    result.append(url)
    return list(dict.fromkeys(result))


def choose_video_url(candidates: list[str], referer: str) -> str:
    candidates = list(dict.fromkeys(candidates))
    inspected: list[tuple[int, int, int, str]] = []
    for u in candidates:
        w, h = url_dims(u)
        size = head_size(u, referer)
        if size > 0:
            inspected.append((w, h, size, u))
    if not inspected:
        return candidates[0]
    acceptable = [x for x in inspected if max(x[0], x[1]) >= 1280 and x[2] <= 160_000_000]
    if acceptable:
        # Prefer 1080-class sources, then the smaller transfer.
        acceptable.sort(key=lambda x: (abs(max(x[0], x[1]) - 1920), x[2]))
        return acceptable[0][3]
    inspected.sort(key=lambda x: x[2])
    return inspected[0][3]


def fetch_pexels(name: str, video_id: str, page_url: str) -> Path:
    page = SESSION.get(page_url, timeout=40)
    page.raise_for_status()
    text = normalize_embedded_urls(page.text)
    found = re.findall(rf"https://videos\.pexels\.com/video-files/{video_id}/[^\s\"'<>]+?\.mp4", text)
    candidates = [u.rstrip("\\") for u in found]

    # The public download endpoint reliably exposes the original file URL.
    try:
        r = SESSION.get(
            f"https://www.pexels.com/download/video/{video_id}/",
            headers={"User-Agent": UA, "Referer": page_url},
            timeout=45,
            allow_redirects=False,
        )
        loc = r.headers.get("location")
        if loc and "videos.pexels.com" in loc:
            candidates = derive_pexels_variants(loc) + candidates
    except Exception as exc:
        print("pexels redirect lookup failed", name, exc)

    if not candidates:
        # Final fallback: let requests follow the official download endpoint.
        endpoint = f"https://www.pexels.com/download/video/{video_id}/"
        dest = CLIPS / f"{name}.mp4"
        download(endpoint, dest, referer=page_url)
        return dest

    chosen = choose_video_url(candidates, page_url)
    suffix = Path(urlparse(chosen).path).suffix or ".mp4"
    dest = CLIPS / f"{name}{suffix}"
    print(f"pexels {name}: {chosen}")
    download(chosen, dest, referer=page_url)
    return dest


def fetch_pixabay(name: str, page_url: str) -> Path:
    page = SESSION.get(page_url, timeout=40)
    page.raise_for_status()
    text = normalize_embedded_urls(page.text)
    candidates = re.findall(r"https://cdn\.pixabay\.com/video/[^\s\"'<>]+?\.mp4", text)
    candidates = list(dict.fromkeys(u.rstrip("\\") for u in candidates))
    if not candidates:
        raise RuntimeError(f"No Pixabay MP4 found on {page_url}")
    preferred = [u for u in candidates if "_large.mp4" in u]
    if not preferred:
        preferred = [u for u in candidates if "_medium.mp4" in u]
    chosen = preferred[0] if preferred else candidates[0]
    dest = CLIPS / f"{name}.mp4"
    print(f"pixabay {name}: {chosen}")
    download(chosen, dest, referer=page_url)
    return dest


async def synthesize_voice() -> tuple[Path, list[tuple[float, float, str]]]:
    VOICE.mkdir(parents=True, exist_ok=True)
    silence = VOICE / "silence.mp3"
    if not silence.exists():
        run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
            "-t", "0.18", "-q:a", "4", str(silence)
        ])
    silence_dur = ffprobe_duration(silence)

    parts: list[Path] = []
    timings: list[tuple[float, float, str]] = []
    cursor = 0.0
    for i, phrase in enumerate(PHRASES):
        part = VOICE / f"voice_{i:02d}.mp3"
        if not part.exists() or part.stat().st_size < 1000:
            communicate = edge_tts.Communicate(
                phrase,
                voice="zh-CN-YunxiNeural",
                rate="-8%",
                volume="+2%",
                pitch="-2Hz",
            )
            await communicate.save(str(part))
        dur = ffprobe_duration(part)
        timings.append((cursor, cursor + dur, phrase))
        cursor += dur
        parts.append(part)
        if i < len(PHRASES) - 1:
            parts.append(silence)
            cursor += silence_dur

    concat = VOICE / "voice_concat.txt"
    concat.write_text("\n".join(f"file '{p.resolve()}'" for p in parts), encoding="utf-8")
    voice_out = VOICE / "narration.m4a"
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
        "-c:a", "aac", "-b:a", "192k", str(voice_out)
    ])
    return voice_out, timings


def ass_time(seconds: float) -> str:
    cs = max(0, int(round(seconds * 100)))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def wrap_cn(text: str, width: int = 15) -> str:
    if len(text) <= width:
        return text
    split_chars = "，。！？；："
    near = [i + 1 for i, ch in enumerate(text) if ch in split_chars and 7 <= i + 1 <= width + 4]
    cut = near[-1] if near else width
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
Style: Sub,Noto Sans CJK SC,54,&H00FFFFFF,&H00FFFFFF,&H00101010,&H55000000,-1,0,0,0,100,100,0,0,1,4,1,2,70,70,170,1
Style: Title,Noto Sans CJK SC,78,&H00FFFFFF,&H00FFFFFF,&H00202020,&H33000000,-1,0,0,0,100,100,1,0,1,5,2,5,70,70,0,1
Style: End,Noto Sans CJK SC,62,&H00FFFFFF,&H00FFFFFF,&H00202020,&H33000000,-1,0,0,0,100,100,1,0,1,4,1,8,70,70,210,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events: list[str] = []
    title_end = min(timings[0][1] + 0.20, 4.5)
    title = r"项羽打赢那么多仗\N为什么还是输了天下？"
    events.append(f"Dialogue: 1,{ass_time(0)},{ass_time(title_end)},Title,,0,0,0,,{title}")
    for i, (start, end, text) in enumerate(timings):
        if i == 0:
            continue
        events.append(f"Dialogue: 2,{ass_time(start)},{ass_time(end)},Sub,,0,0,0,,{wrap_cn(text)}")
    prompt_start = max(0, total - 2.8)
    events.append(f"Dialogue: 3,{ass_time(prompt_start)},{ass_time(total)},End,,0,0,0,,你觉得，项羽真正输在哪里？")
    ass.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return ass


def process_clip(src: Path, dest: Path, duration: float, index: int) -> None:
    source_dur = ffprobe_duration(src)
    usable = max(0.0, source_dur - duration - 0.15)
    start = (index * 1.37) % usable if usable > 0.2 else 0.0
    # Full-screen vertical crop, slight cinematic grade, no archive-card layout.
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920:(iw-ow)/2:(ih-oh)/2,"
        "fps=30,setsar=1,"
        "eq=contrast=1.10:saturation=0.78:brightness=-0.025,"
        "vignette=PI/5,format=yuv420p"
    )
    args = ["ffmpeg", "-y"]
    if source_dur < duration + 0.1:
        args += ["-stream_loop", "-1"]
    args += [
        "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{duration:.3f}",
        "-an", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "20", "-pix_fmt", "yuv420p", str(dest)
    ]
    run(args)


def make_video(clips: list[Path], voice: Path, timings: list[tuple[float, float, str]]) -> Path:
    total = ffprobe_duration(voice)
    ass = write_ass(timings, total)
    segment_duration = 4.2
    count = int(total // segment_duration) + 2
    sequence_order = [3, 0, 2, 1, 4, 5, 0, 6, 2, 3, 1, 4, 0, 7, 2, 3, 6, 4]
    processed: list[Path] = []
    for i in range(count):
        src = clips[sequence_order[i % len(sequence_order)] % len(clips)]
        dest = WORK / f"segment_{i:02d}.mp4"
        process_clip(src, dest, segment_duration, i)
        processed.append(dest)

    concat = WORK / "video_concat.txt"
    concat.write_text("\n".join(f"file '{p.resolve()}'" for p in processed), encoding="utf-8")
    base = WORK / "base_video.mp4"
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
        "-t", f"{total:.3f}", "-c:v", "copy", str(base)
    ])

    OUT.mkdir(parents=True, exist_ok=True)
    final = OUT / "项羽为什么打赢那么多仗却输掉天下_竖屏成片.mp4"
    filter_expr = f"subtitles={ass.as_posix()}:fontsdir=/usr/share/fonts/opentype/noto"
    run([
        "ffmpeg", "-y", "-i", str(base), "-i", str(voice),
        "-filter_complex", f"[0:v]{filter_expr}[v]",
        "-map", "[v]", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-shortest", "-movflags", "+faststart", str(final)
    ])

    # Visual QA sheet: 12 evenly distributed frames.
    sheet = OUT / "项羽竖屏成片_画面检查.jpg"
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
    failures: list[str] = []
    for name, video_id, page in PEXELS:
        try:
            clips.append(fetch_pexels(name, video_id, page))
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            print("WARNING", failures[-1])
    for name, page in PIXABAY:
        try:
            clips.append(fetch_pixabay(name, page))
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            print("WARNING", failures[-1])

    if len(clips) < 5:
        raise RuntimeError("Not enough downloadable clips. " + " | ".join(failures))

    voice, timings = asyncio.run(synthesize_voice())
    final = make_video(clips, voice, timings)
    print("FINAL", final)
    print(run(["ffprobe", "-v", "error", "-show_entries", "format=duration,size", "-of", "json", str(final)]).stdout)


if __name__ == "__main__":
    main()
