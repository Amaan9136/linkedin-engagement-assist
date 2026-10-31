import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit
URL_ONLY = re.compile('^\\s*(https?://\\S+\\s*)+$', re.I)
REL = re.compile('(\\d+)\\s*(mo|yr|m|h|d|w|s)\\b', re.I)
UNITS = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800, 'mo': 2592000, 'yr': 31536000}
def clean_text(s):
    if not s:
        return ''
    s = s.replace('\xa0', ' ')
    s = re.sub('[ \\t]+', ' ', s)
    s = re.sub('\\s*\\n\\s*', '\n', s)
    return s.strip()
def normalize_url(url):
    p = urlsplit(url.strip())
    path = p.path if p.path.endswith('/') else p.path + '/'
    return urlunsplit(('https', p.netloc.lower() or 'www.linkedin.com', path, '', ''))
def parse_relative_time(text):
    if not text:
        return None
    t = text.strip().lower()
    now = datetime.now(timezone.utc)
    if t.startswith('now') or 'just now' in t:
        return now.strftime('%Y-%m-%dT%H:%M:%SZ')
    m = REL.search(t)
    if not m:
        return None
    seconds = int(m.group(1)) * UNITS[m.group(2).lower()]
    return (now - timedelta(seconds=seconds)).strftime('%Y-%m-%dT%H:%M:%SZ')
def meaningful_body(body):
    b = clean_text(body)
    if not b or URL_ONLY.match(b):
        return ''
    stripped = re.sub('#\\w+|https?://\\S+', '', b).strip()
    if len(stripped) < 25 or len(stripped.split()) < 4:
        return ''
    return b
def build_context(post):
    author = clean_text(post.get('author_name'))
    title = clean_text(post.get('title'))
    alt = clean_text(post.get('alt_text'))
    extra = clean_text(post.get('extra_text'))
    body = meaningful_body(post.get('body'))
    lines = []
    if author:
        lines.append(f'Author: {author}')
    if body:
        if title:
            lines.append(f'Title: {title}')
        lines.append('Post text:\n' + body[:3000])
        if alt:
            lines.append('Image descriptions (alt text): ' + alt[:600])
        if extra:
            lines.append('Other text: ' + extra[:800])
        return '\n'.join(lines)
    if len(title) >= 8:
        lines.append(f'Title: {title}')
        if extra:
            lines.append('Link description: ' + extra[:800])
        return '\n'.join(lines)
    if len(extra) >= 40:
        lines.append('Other text: ' + extra[:800])
        return '\n'.join(lines)
    return None
