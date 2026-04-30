"""YouTube subtitle utilities."""

import re
from urllib.parse import urlparse, parse_qs


def extract_video_id(url: str) -> str:
    """Extract video ID from YouTube URL formats (watch, youtu.be, embed, /v/)."""
    parsed = urlparse(url)

    if parsed.netloc in ('youtu.be', 'www.youtu.be'):
        return parsed.path.lstrip('/')

    if parsed.netloc in ('youtube.com', 'www.youtube.com', 'm.youtube.com'):
        if parsed.path == '/watch':
            qs = parse_qs(parsed.query)
            if 'v' in qs:
                return qs['v'][0]

        match = re.match(r'^/(embed|v)/([^/?]+)', parsed.path)
        if match:
            return match.group(2)

    raise ValueError(f"Could not extract video ID from URL: {url}")
