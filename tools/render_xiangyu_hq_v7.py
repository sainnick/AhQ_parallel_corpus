#!/usr/bin/env python3
from __future__ import annotations

import asyncio
from pathlib import Path

import render_xiangyu_hq_v6 as base

SEARCHES = [
    ("white_vengeance", "White Vengeance Xiang Yu battle 1080p", "《鸿门宴传奇》项羽战争镜头"),
    ("kings_war", "King's War Xiang Yu battle", "《楚汉传奇》项羽战争镜头"),
    ("julu", "项羽 巨鹿之战 高清", "项羽巨鹿之战高清镜头"),
    ("pengcheng", "项羽 彭城之战 高清", "项羽彭城之战高清镜头"),
    ("gaixia", "项羽 垓下 乌江自刎 高清", "项羽垓下与乌江高清镜头"),
]

TITLE_TOKENS = (
    "项羽", "xiang yu", "white vengeance", "king's war", "kings war",
    "楚汉", "西楚霸王", "hongmen", "hồng môn",
)


def search_results(query: str) -> list[tuple[str, str]]:
    result = base.run([
        "yt-dlp", "--flat-playlist", "--playlist-end", "10", "--no-warnings",
        "--print", "%(id)s\t%(title)s", f"ytsearch10:{query}",
    ], check=False, timeout=180)
    rows: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if "\t" not in line:
            continue
        video_id, title = line.split("\t", 1)
        if video_id and title:
            rows.append((video_id.strip(), title.strip()))
    return rows


def download_youtube_candidate(name: str, video_id: str) -> Path | None:
    base.DOWNLOADS.mkdir(parents=True, exist_ok=True)
    template = str(base.DOWNLOADS / f"{name}.%(ext)s")
    url = f"https://www.youtube.com/watch?v={video_id}"
    base.run([
        "yt-dlp", "--no-playlist", "--no-warnings",
        "--retries", "5", "--fragment-retries", "5", "--socket-timeout", "30",
        "--merge-output-format", "mp4", "--format-sort", "res:1080,fps,br",
        "-f", "bv*[height>=720][height<=1080]+ba/b[height>=720][height<=1080]/best[height>=720]/best",
        "-o", template, url,
    ], check=False, timeout=480)
    candidates = sorted(base.DOWNLOADS.glob(f"{name}.*"), key=lambda p: p.stat().st_size, reverse=True)
    for candidate in candidates:
        if base.valid_hq(candidate):
            if candidate.suffix.lower() == ".mp4":
                return candidate
            converted = base.DOWNLOADS / f"{name}.mp4"
            base.run([
                "ffmpeg", "-y", "-i", str(candidate),
                "-c:v", "libx264", "-preset", "medium", "-crf", "17",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(converted),
            ], timeout=600)
            return converted if base.valid_hq(converted) else None
    return None


def collect_sources() -> tuple[list[Path], list[str]]:
    clips: list[Path] = []
    report: list[str] = []
    used_ids: set[str] = set()
    for name, query, label in SEARCHES:
        chosen: Path | None = None
        chosen_title = ""
        chosen_id = ""
        for rank, (video_id, title) in enumerate(search_results(query)):
            if video_id in used_ids:
                continue
            title_lower = title.lower()
            if not any(token in title_lower for token in TITLE_TOKENS):
                continue
            path = download_youtube_candidate(f"{name}_{rank}", video_id)
            if path:
                chosen = path
                chosen_title = title
                chosen_id = video_id
                break
        if not chosen:
            report.append(f"FAILED | {label} | search={query}")
            continue
        used_ids.add(chosen_id)
        width, height, seconds, bitrate = base.probe(chosen)
        report.append(
            f"OK | {label} | {chosen_title} | {width}x{height} | {seconds:.2f}s | "
            f"{bitrate/1_000_000:.2f}Mbps | https://www.youtube.com/watch?v={chosen_id}"
        )
        clips.append(chosen)
    if len(clips) < 3:
        raise RuntimeError(f"Only {len(clips)} high-resolution Xiang Yu sources were downloaded")
    return clips, report


base.collect_sources = collect_sources

if __name__ == "__main__":
    raise SystemExit(asyncio.run(base.main()))
