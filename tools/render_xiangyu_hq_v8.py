#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

import requests

import render_xiangyu_hq_v6 as base

CCTV_SOURCES = [
    ("julu", "https://tv.cctv.com/2019/10/29/VIDEnBn42nbaDBGMehnHfXL5191029.shtml", "《楚汉》巨鹿之战：项羽破釜沉舟"),
    ("pengcheng", "https://tv.cctv.com/2019/10/29/VIDEeiXDYhSlhFm9pNFQfePn191029.shtml", "《楚汉》彭城之战：项羽大获全胜"),
    ("fanzeng", "https://tv.cctv.com/2019/10/29/VIDEzqvuyrCbvW5GYntjRt9V191029.shtml", "《楚汉》反间计：范增离开项羽"),
    ("gaixia", "https://tv.cctv.com/2019/10/29/VIDEfkkiTQoriYBwYSE8Gp0I191029.shtml", "《楚汉》垓下决战：项羽最后一战"),
    ("farewell", "https://tv.cctv.com/2019/10/29/VIDEUZh04nKQePv7Gvj5oU9M191029.shtml", "《楚汉》霸王别姬"),
]

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
    "Referer": "https://tv.cctv.com/",
})


def extract_guid(page_url: str) -> str:
    response = SESSION.get(page_url, timeout=40)
    response.raise_for_status()
    text = response.text
    patterns = [
        r'var\s+guid\s*=\s*["\']([0-9a-zA-Z]{16,64})["\']',
        r'guid_Ad_VideoCode\s*=\s*["\']([0-9a-zA-Z]{16,64})["\']',
        r'videoCenterId\s*[:=]\s*["\']([0-9a-zA-Z]{16,64})["\']',
        r'<!--repaste\.video\.code\.begin-->([0-9a-zA-Z]{16,64})<!--repaste\.video\.code\.end-->',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1)
    # Last resort: the page's VIDE token often embeds a usable program id.
    match = re.search(r'/VIDE([0-9a-zA-Z]+)\.shtml', page_url)
    if match:
        return match.group(1)
    raise RuntimeError(f"Could not extract CCTV guid from {page_url}")


def api_info(guid: str) -> dict:
    urls = [
        f"https://vdn.apps.cntv.cn/api/getHttpVideoInfo.do?pid={guid}&client=html5&tai=ipad",
        f"https://vdn.apps.cntv.cn/api/getHttpVideoInfo.do?pid={guid}",
    ]
    last_error: Exception | None = None
    for url in urls:
        try:
            response = SESSION.get(url, timeout=45)
            response.raise_for_status()
            data = response.json()
            if data.get("video"):
                return data
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"CCTV API failed for {guid}: {last_error}")


def download_url(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with SESSION.get(url, stream=True, timeout=(30, 300), allow_redirects=True) as response:
        response.raise_for_status()
        temp = destination.with_suffix(destination.suffix + ".part")
        with temp.open("wb") as handle:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    handle.write(chunk)
        temp.replace(destination)


def candidate_groups(data: dict) -> list[tuple[str, list[str]]]:
    video = data.get("video", {})
    groups: list[tuple[str, list[str]]] = []
    for key, value in video.items():
        if not isinstance(value, list) or not value:
            continue
        urls: list[str] = []
        for item in value:
            if isinstance(item, dict) and item.get("url"):
                urls.append(item["url"])
        if urls:
            groups.append((key, urls))
    # hls_url can expose a higher bitrate stream than the MP4 chapter lists.
    for key in ("hls_url", "hls_url2", "hls_url3", "hls_url4"):
        value = data.get(key) or video.get(key)
        if isinstance(value, str) and value.startswith("http"):
            groups.append((key, [value]))
    return groups


def fetch_group(name: str, group_name: str, urls: list[str]) -> Path | None:
    parts: list[Path] = []
    for index, url in enumerate(urls):
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix not in (".mp4", ".m3u8"):
            suffix = ".mp4"
        destination = base.DOWNLOADS / f"{name}_{group_name}_{index}{suffix}"
        try:
            if suffix == ".m3u8":
                base.run([
                    "ffmpeg", "-y", "-i", url, "-c", "copy", "-bsf:a", "aac_adtstoasc", str(destination.with_suffix('.mp4')),
                ], timeout=900)
                destination = destination.with_suffix(".mp4")
            else:
                download_url(url, destination)
            if destination.exists() and destination.stat().st_size > 200_000:
                parts.append(destination)
        except Exception as exc:
            print(f"group download failed {group_name} {url}: {exc}", flush=True)
            return None
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    listing = base.DOWNLOADS / f"{name}_{group_name}_concat.txt"
    listing.write_text("\n".join(f"file '{p.resolve()}'" for p in parts), encoding="utf-8")
    combined = base.DOWNLOADS / f"{name}_{group_name}.mp4"
    base.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-c", "copy", str(combined),
    ], timeout=900)
    return combined


def download_cctv(name: str, page_url: str) -> tuple[Path | None, list[str]]:
    base.DOWNLOADS.mkdir(parents=True, exist_ok=True)
    guid = extract_guid(page_url)
    data = api_info(guid)
    (base.DOWNLOADS / f"{name}_api.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    candidates: list[tuple[int, int, int, str, Path]] = []
    diagnostics: list[str] = []
    for group_name, urls in candidate_groups(data):
        path = fetch_group(name, re.sub(r'[^0-9a-zA-Z_-]', '_', group_name), urls)
        if not path:
            continue
        try:
            width, height, seconds, bitrate = base.probe(path)
            diagnostics.append(f"{group_name}: {width}x{height}, {seconds:.2f}s, {bitrate/1_000_000:.2f}Mbps")
            if seconds >= 8:
                candidates.append((width * height, bitrate, path.stat().st_size, group_name, path))
        except Exception as exc:
            diagnostics.append(f"{group_name}: probe failed {exc}")
    if not candidates:
        return None, diagnostics
    candidates.sort(reverse=True)
    chosen = candidates[0][4]
    final = base.DOWNLOADS / f"{name}.mp4"
    if chosen != final:
        shutil.copy2(chosen, final)
    return final, diagnostics


def collect_sources() -> tuple[list[Path], list[str]]:
    clips: list[Path] = []
    report: list[str] = []
    for name, page_url, label in CCTV_SOURCES:
        try:
            path, diagnostics = download_cctv(name, page_url)
        except Exception as exc:
            report.append(f"FAILED | {label} | {exc} | {page_url}")
            continue
        report.extend(f"CHECK | {label} | {line}" for line in diagnostics)
        if not path:
            report.append(f"FAILED | {label} | no downloadable stream | {page_url}")
            continue
        width, height, seconds, bitrate = base.probe(path)
        report.append(f"SELECTED | {label} | {width}x{height} | {seconds:.2f}s | {bitrate/1_000_000:.2f}Mbps | {page_url}")
        clips.append(path)
    if len(clips) < 3:
        raise RuntimeError(f"Only {len(clips)} CCTV Xiang Yu sources were downloaded")
    return clips, report


base.collect_sources = collect_sources

if __name__ == "__main__":
    raise SystemExit(asyncio.run(base.main()))
