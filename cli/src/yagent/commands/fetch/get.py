"""`y fetch get <url>` — fetch content from a URL and save as markdown.

Routes to per-source handlers based on URL host:
- mp.weixin.qq.com → Oxylabs + WeChat HTML parser
- bilibili.com    → Oxylabs + Bilibili API (Chrome cookies)
- youtube.com / youtu.be → yt-dlp local subprocess
- x.com / twitter.com → Jina AI reader
- everything else → Oxylabs + generic HTML extractor

Output is written to `~/luohy15/assets/web/<YYYYMMDD>/https/<host>/<path>.md`.
"""

import asyncio
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import click
import httpx
from dotenv import load_dotenv

from ._bilibili import bv2av
from ._oxylabs import fetch_json, fetch_raw, load_cookies_from_chrome
from ._youtube import extract_video_id


OUTPUT_BASE = Path.home() / "luohy15"


def _dated_output_base() -> Path:
    return OUTPUT_BASE / 'assets' / 'web' / datetime.now().strftime('%Y%m%d')


def _detect_source(url: str) -> str:
    if 'mp.weixin.qq.com' in url:
        return 'weixin'
    if 'bilibili.com' in url:
        return 'bilibili'
    if 'youtube.com' in url or 'youtu.be' in url:
        return 'youtube'
    if 'x.com' in url or 'twitter.com' in url:
        return 'twitter'
    if 'zhihu.com' in url:
        return 'zhihu'
    return 'page'


def _extract_weixin_id(url: str) -> str:
    path = urlparse(url).path
    if path.startswith('/s/'):
        return path[3:]
    if path.startswith('/s'):
        return path[2:]
    return path.split('/')[-1] or 'article'


def _extract_bvid(url: str) -> str:
    match = re.search(r'/video/(BV[a-zA-Z0-9]+)', urlparse(url).path)
    if not match:
        raise ValueError(f"Could not extract BVID from URL: {url}")
    return match.group(1)


def _extract_twitter_info(url: str) -> tuple[str, str]:
    match = re.search(r'/([^/]+)/status/(\d+)', urlparse(url).path)
    if not match:
        raise ValueError(f"Could not extract Twitter info from URL: {url}")
    return match.group(1), match.group(2)


# --- Twitter / X ---

async def _fetch_twitter(client: httpx.AsyncClient, url: str) -> Path:
    username, status_id = _extract_twitter_info(url)
    normalized = f"https://x.com/{username}/status/{status_id}"

    resp = await client.get(f"https://r.jina.ai/{normalized}")
    if resp.status_code != 200:
        raise Exception(f"Jina fetch failed with status {resp.status_code}")
    content = resp.text

    md = '\n'.join([
        f"# Tweet by @{username}",
        "",
        f"- **User**: @{username}",
        f"- **Link**: {normalized}",
        "",
        "---",
        "",
        content,
    ])

    out_dir = _dated_output_base() / 'https/x.com' / username / 'status'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{status_id}.md"
    out_path.write_text(md, encoding='utf-8')
    return out_path


# --- WeChat ---

def _parse_weixin(html: str, url: str) -> dict:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, 'html.parser')

    title_elem = soup.find('h1', class_='rich_media_title') or soup.find('h1')
    title = title_elem.get_text(strip=True) if title_elem else ''

    author_elem = soup.find('a', id='js_name') or soup.find('span', class_='rich_media_meta_nickname')
    author = author_elem.get_text(strip=True) if author_elem else ''

    time_elem = soup.find('em', id='publish_time')
    publish_time = time_elem.get_text(strip=True) if time_elem else ''

    content_elem = soup.find('div', id='js_content') or soup.find('div', class_='rich_media_content')
    if content_elem:
        for elem in content_elem(['script', 'style']):
            elem.decompose()
        content = content_elem.get_text(separator='\n', strip=True)
    else:
        for elem in soup(['script', 'style', 'noscript']):
            elem.decompose()
        content = soup.get_text(separator='\n', strip=True)

    return {'title': title, 'author': author, 'publish_time': publish_time, 'content': content, 'url': url}


async def _fetch_weixin(client: httpx.AsyncClient, url: str) -> Path:
    html = await fetch_raw(client, url)
    data = _parse_weixin(html, url)

    lines = [f"# {data['title']}", ""]
    if data['author']:
        lines.append(f"- **Author**: {data['author']}")
    if data['publish_time']:
        lines.append(f"- **Time**: {data['publish_time']}")
    lines.extend([f"- **Link**: {data['url']}", "", "---", "", data['content']])

    out_dir = _dated_output_base() / 'https/mp.weixin.qq.com/s'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_extract_weixin_id(url)}.md"
    out_path.write_text('\n'.join(lines), encoding='utf-8')
    return out_path


# --- Bilibili ---

async def _fetch_bilibili(client: httpx.AsyncClient, bvid: str, page: int = 1) -> Path:
    cookies = load_cookies_from_chrome('.bilibili.com')
    aid = bv2av(bvid)

    info = await fetch_json(client, f"https://api.bilibili.com/x/web-interface/view?aid={aid}", cookies)
    if info.get('code') != 0:
        raise Exception(f"Bilibili API error: {info.get('message')}")

    pages = info['data']['pages']
    target = next((p for p in pages if p['page'] == page), None)
    if not target:
        raise Exception(f"Page {page} not found. Available: {', '.join(str(p['page']) for p in pages)}")

    cid = target['cid']
    title = info['data']['title']
    owner = info['data']['owner']['name']
    desc = info['data']['desc']
    part_title = target['part']

    sub_info = await fetch_json(client, f"https://api.bilibili.com/x/player/wbi/v2?aid={aid}&cid={cid}", cookies)
    if sub_info.get('code') != 0:
        raise Exception(f"Subtitle API error: {sub_info.get('message')}")
    subtitles = sub_info.get('data', {}).get('subtitle', {}).get('subtitles', [])

    lines = [
        f"# {title}", "",
        f"- **BV**: {bvid}",
        f"- **UP**: {owner}",
        f"- **Link**: https://www.bilibili.com/video/{bvid}",
    ]
    if len(pages) > 1:
        lines.append(f"- **Page**: {page} - {part_title}")
    lines.append("")

    if desc and desc.strip():
        lines.extend(["## Description", "", desc, ""])

    if not subtitles:
        lines.extend(["## Subtitles", "", "*No subtitles available for this video*"])
    else:
        sub_url = f"https:{subtitles[0]['subtitle_url']}"
        sub_lang = subtitles[0]['lan_doc']
        sub_data = await fetch_json(client, sub_url)
        lines.extend([f"## Subtitles ({sub_lang})", ""])
        for item in sub_data.get('body') or []:
            lines.append(item['content'])

    out_dir = _dated_output_base() / 'https/www.bilibili.com/video'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{bvid}.md"
    out_path.write_text('\n'.join(lines), encoding='utf-8')
    return out_path


# --- YouTube ---

def _parse_vtt(vtt: str) -> list[str]:
    lines: list[str] = []
    prev = None
    for line in vtt.split('\n'):
        line = line.strip()
        if not line or line.startswith('WEBVTT') or '-->' in line or line.isdigit():
            continue
        if line.startswith('NOTE'):
            continue
        line = re.sub(r'<[^>]+>', '', line)
        if line and line != prev:
            lines.append(line)
            prev = line
    return lines


def _fetch_youtube(url: str, lang: str = 'en') -> Path:
    video_id = extract_video_id(url)
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    cmd = [
        'yt-dlp',
        '--cookies-from-browser', 'chrome',
        '--skip-download',
        '--write-subs',
        '--write-auto-subs',
        f'--sub-langs={lang},-orig',
        '--sub-format=vtt',
        '--print-json',
        '-o', f'/tmp/yt_{video_id}',
        video_url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"yt-dlp error: {result.stderr}")

    info = json.loads(result.stdout)
    title = info.get('title', video_id)
    author = info.get('uploader', '')
    description = info.get('description', '')

    subtitle_file = None
    subtitle_lang = None
    for ext_lang in [lang, f'{lang}-orig', 'en', 'en-orig']:
        path = f'/tmp/yt_{video_id}.{ext_lang}.vtt'
        if os.path.exists(path):
            subtitle_file = path
            subtitle_lang = ext_lang.replace('-orig', ' (auto)')
            break

    lines = [f"# {title}", "", f"- **Video ID**: {video_id}"]
    if author:
        lines.append(f"- **Channel**: {author}")
    lines.append(f"- **Link**: {video_url}")
    lines.append("")

    if description and description.strip():
        lines.extend(["## Description", "", description, ""])

    if subtitle_file:
        with open(subtitle_file, 'r', encoding='utf-8') as f:
            vtt = f.read()
        lines.extend([f"## Subtitles ({subtitle_lang})", ""])
        lines.extend(_parse_vtt(vtt))
        os.remove(subtitle_file)
    else:
        lines.extend(["## Subtitles", "", "*No subtitles available for this video*"])

    out_dir = _dated_output_base() / 'https/www.youtube.com'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{video_id}.md"
    out_path.write_text('\n'.join(lines), encoding='utf-8')
    return out_path


# --- Generic page ---

def _extract_text_with_structure(elem) -> str:
    lines: list[str] = []
    for child in elem.descendants:
        if child.name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            text = child.get_text(strip=True)
            if text:
                lines.extend(['', '#' * int(child.name[1]) + ' ' + text, ''])
        elif child.name == 'p':
            text = child.get_text(strip=True)
            if text:
                lines.extend([text, ''])
        elif child.name == 'li':
            text = child.get_text(strip=True)
            if text:
                lines.append('- ' + text)
        elif child.name == 'br':
            lines.append('')

    if not any(line.strip() for line in lines):
        return elem.get_text(separator='\n', strip=True)

    result: list[str] = []
    prev_empty = False
    for line in lines:
        is_empty = not line.strip()
        if is_empty and prev_empty:
            continue
        result.append(line)
        prev_empty = is_empty
    return '\n'.join(result).strip()


def _parse_page(html: str, url: str) -> dict:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, 'html.parser')

    title = ''
    title_elem = soup.find('title')
    if title_elem:
        title = title_elem.get_text(strip=True)
    if not title:
        h1 = soup.find('h1')
        if h1:
            title = h1.get_text(strip=True)

    for elem in soup(['script', 'style', 'noscript', 'nav', 'footer', 'header', 'aside']):
        elem.decompose()

    main = (
        soup.find('main')
        or soup.find('article')
        or soup.find('div', class_=re.compile(r'content|post|article|entry', re.I))
        or soup.find('body')
    )
    content = _extract_text_with_structure(main) if main else soup.get_text(separator='\n', strip=True)
    return {'title': title, 'content': content, 'url': url}


def _url_to_path(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    host = parsed.netloc.replace(':', '_')
    path = parsed.path.strip('/')
    if not path:
        return f"https/{host}", "index"
    if path.endswith('.html') or path.endswith('.htm'):
        path = path.rsplit('.', 1)[0]
    parts = path.rsplit('/', 1)
    if len(parts) == 1:
        return f"https/{host}", parts[0]
    return f"https/{host}/{parts[0]}", parts[1]


async def _fetch_page(client: httpx.AsyncClient, url: str) -> Path:
    html = await fetch_raw(client, url)
    data = _parse_page(html, url)

    md = '\n'.join([f"# {data['title']}", "", f"- **Link**: {data['url']}", "", "---", "", data['content']])

    dir_path, filename = _url_to_path(url)
    out_dir = _dated_output_base() / dir_path
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{filename}.md"
    out_path.write_text(md, encoding='utf-8')
    return out_path


# --- Dispatch ---

async def _run(url: str, page: int, lang: str) -> Path:
    source = _detect_source(url)

    if source == 'youtube':
        return _fetch_youtube(url, lang)
    if source == 'zhihu':
        raise Exception("Zhihu blocks scraping (403 Forbidden). Please copy-paste the content manually.")

    async with httpx.AsyncClient() as client:
        if source == 'weixin':
            return await _fetch_weixin(client, url)
        if source == 'bilibili':
            return await _fetch_bilibili(client, _extract_bvid(url), page)
        if source == 'twitter':
            return await _fetch_twitter(client, url)
        return await _fetch_page(client, url)


def _extract_title(md: str) -> str:
    for line in md.splitlines():
        line = line.strip()
        if line.startswith('# '):
            return line[2:].strip()
        if line:
            break
    return ''


@click.command('get')
@click.argument('url')
@click.option('--page', '-p', type=int, default=1,
              help='Page number (for Bilibili multi-part videos).')
@click.option('--lang', '-l', default='en',
              help='Preferred subtitle language for YouTube (default: en).')
@click.option('--json', 'json_output', is_flag=True,
              help='Emit one-line JSON {status,title,content,path,error} on stdout '
                   'instead of the human "Saved: ..." line. File is still written.')
def fetch_get(url: str, page: int, lang: str, json_output: bool):
    """Fetch URL content and save as markdown.

    Output: ~/luohy15/assets/web/<YYYYMMDD>/https/<host>/<path>.md

    Source dispatch:

    \b
    - mp.weixin.qq.com → Oxylabs + WeChat parser
    - bilibili.com    → Bilibili API (Chrome cookies)
    - youtube.com / youtu.be → yt-dlp
    - x.com / twitter.com → Jina AI reader
    - other           → Oxylabs + generic HTML extractor

    Requires OXYLABS_USERNAME / OXYLABS_PASSWORD in env (or ~/.y-agent/config.toml)
    for everything except YouTube and Twitter. yt-dlp must be installed for YouTube.
    """
    load_dotenv()

    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    if _detect_source(url) not in ('youtube', 'twitter'):
        if not os.environ.get('OXYLABS_USERNAME') or not os.environ.get('OXYLABS_PASSWORD'):
            if json_output:
                click.echo(json.dumps({
                    "status": "failed",
                    "title": None,
                    "content": None,
                    "path": None,
                    "error": "OXYLABS_USERNAME and OXYLABS_PASSWORD must be set",
                }))
                return
            raise click.ClickException("OXYLABS_USERNAME and OXYLABS_PASSWORD must be set")

    try:
        out_path = asyncio.run(_run(url, page, lang))
    except Exception as e:
        if json_output:
            click.echo(json.dumps({
                "status": "failed",
                "title": None,
                "content": None,
                "path": None,
                "error": str(e),
            }))
            return
        raise click.ClickException(str(e))

    if json_output:
        try:
            content = out_path.read_text(encoding='utf-8')
        except Exception as e:
            click.echo(json.dumps({
                "status": "failed",
                "title": None,
                "content": None,
                "path": str(out_path),
                "error": f"failed to read output file: {e}",
            }))
            return
        click.echo(json.dumps({
            "status": "done",
            "title": _extract_title(content) or None,
            "content": content,
            "path": str(out_path),
            "error": None,
        }))
        return

    click.echo(f"Saved: {out_path}")
