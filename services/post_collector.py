import logging
from datetime import datetime, timedelta, timezone
from . import text_extractor as tx
log = logging.getLogger('linkedin.collector')
EXTRACT_JS = '() => {\n  const pick = (el, sels) => { for (const s of sels) { const n = el.querySelector(s); if (n) return n; } return null; };\n  const txt = n => n ? (n.innerText || n.textContent || \'\').trim() : \'\';\n  const out = [];\n  const seen = new Set();\n  document.querySelectorAll(\'[data-urn],[data-id]\').forEach(el => {\n    const raw = el.getAttribute(\'data-urn\') || el.getAttribute(\'data-id\') || \'\';\n    const m = raw.match(/urn:li:(activity|share|ugcPost):\\d+/);\n    if (!m || seen.has(m[0])) return;\n    if (!el.querySelector(\'.update-components-actor\') && !el.matches(\'.feed-shared-update-v2\')) return;\n    seen.add(m[0]);\n    const author = pick(el, [\'.update-components-actor__title span[aria-hidden="true"]\', \'.update-components-actor__name\', \'.update-components-actor__title\']);\n    const link = pick(el, [\'a.update-components-actor__meta-link\', \'a.update-components-actor__container-link\']);\n    const sub = pick(el, [\'.update-components-actor__sub-description\', \'.update-components-actor__description\']);\n    const body = pick(el, [\'.update-components-text\', \'.feed-shared-update-v2__description\', \'.feed-shared-text\', \'.break-words\']);\n    const title = pick(el, [\'.update-components-article__title\', \'.update-components-entity__title\', \'.feed-shared-article__title\', \'.update-components-document__title\']);\n    const desc = pick(el, [\'.update-components-article__description\', \'.update-components-entity__description\', \'.update-components-article__subtitle\']);\n    const alts = [];\n    el.querySelectorAll(\'img[alt]\').forEach(i => {\n      if (i.closest(\'.update-components-actor\')) return;\n      const a = (i.getAttribute(\'alt\') || \'\').trim();\n      if (a && a.length > 3 && !alts.includes(a)) alts.push(a);\n    });\n    out.push({urn: m[0], author: txt(author), author_url: link ? link.href : \'\', sub: txt(sub), body: txt(body),\n              title: txt(title), extra: txt(desc), alt: alts.slice(0, 6).join(\' | \')});\n  });\n  return out;\n}'
def _to_post(item, cutoff):
    sub = item.get('sub') or ''
    if 'promoted' in sub.lower():
        return None
    published = tx.parse_relative_time(sub)
    if published and datetime.strptime(published, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc) < cutoff:
        return None
    urn = item['urn']
    author_url = (item.get('author_url') or '').split('?')[0] or None
    return {'external_id': urn, 'url': tx.normalize_url(f'https://www.linkedin.com/feed/update/{urn}/'), 'author_name': tx.clean_text(item.get('author')).split('\n')[0] or None, 'author_url': author_url, 'title': tx.clean_text(item.get('title')) or None, 'body': tx.clean_text(item.get('body')) or None, 'alt_text': tx.clean_text(item.get('alt')) or None, 'extra_text': tx.clean_text(item.get('extra')) or None, 'published_at': published}
def collect(browser, deep=False, lookback_days=7):
    page = browser.goto_feed()
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    max_scrolls = 30 if deep else 4
    seen = {}
    stagnant = 0
    for _ in range(max_scrolls):
        items = page.evaluate(EXTRACT_JS)
        before = len(seen)
        for it in items:
            seen.setdefault(it['urn'], it)
        stagnant = stagnant + 1 if len(seen) == before else 0
        if stagnant >= 3:
            break
        browser.scroll(page)
    posts = []
    for it in seen.values():
        try:
            p = _to_post(it, cutoff)
            if p:
                posts.append(p)
        except Exception:
            log.exception('Could not parse a feed item')
    log.debug('Collected %d posts from %d feed items', len(posts), len(seen))
    return posts
