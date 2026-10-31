import logging
from datetime import datetime, timedelta, timezone
from . import text_extractor as tx
log = logging.getLogger('linkedin.collector')
EXTRACT_JS = r'''() => {
  const raw = n => (n.innerText || n.textContent || '').trim();
  const txt = n => { if (!n) return ''; const t = raw(n); const b = n.querySelector && n.querySelector("[data-testid='expandable-text-button']"); const k = b ? raw(b) : ''; return k && t.endsWith(k) ? t.slice(0, -k.length).trim() : t; };
  const pick = (el, sels) => { for (const s of sels) { const n = el.querySelector(s); if (n && txt(n)) return n; } return null; };
  const ID = /(activity|share|ugcPost)[-:](\d{10,})/;
  const LEG = /^urn:li:(activity|share|ugcPost):\d+/;
  const actors = "a[href*='/in/'], a[href*='/company/'], a[href*='/school/']";
  const isLike = b => { const l = (b.getAttribute('aria-label') || '').toLowerCase(); return /^((react )?(like|unlike)\b|reaction button state)/.test(l) && !/comment/.test(l); };
  const dec = s => { try { return decodeURIComponent(s); } catch (e) { return s; } };
  const cardOf = el => { const k = (el.getAttribute('componentkey') || '').match(/^update-card-focus(.+?)(?:FeedType_\w+)?$/); return k ? k[1] : ''; };
  const urnIn = el => {
    for (const n of [el, ...el.querySelectorAll('[data-urn],[data-id],[componentkey],[data-sdui-anchor-id],a[href]')]) {
      for (const a of ['data-urn', 'data-id', 'componentkey', 'data-sdui-anchor-id', 'href']) {
        const m = dec(n.getAttribute(a) || '').match(ID);
        if (m) return 'urn:li:' + m[1] + ':' + m[2];
      }
    }
    return cardOf(el) ? 'card:' + cardOf(el) : null;
  };
  const cards = new Set();
  document.querySelectorAll('[data-urn],[data-id]').forEach(el => {
    if (LEG.test(el.getAttribute('data-urn') || el.getAttribute('data-id') || '') && (el.querySelector('.update-components-actor') || el.matches('.feed-shared-update-v2'))) cards.add(el);
  });
  document.querySelectorAll("[data-view-name='feed-full-update'],[componentkey^='update-card']").forEach(el => cards.add(el));
  const likes = [...document.querySelectorAll("button[aria-label],[role='button'][aria-label]")].filter(isLike);
  likes.forEach(b => {
    if ([...cards].some(c => c.contains(b))) return;
    let el = b;
    for (let i = 0; i < 14 && el.parentElement && !['MAIN', 'BODY'].includes(el.parentElement.tagName); i++) {
      if (likes.filter(x => el.parentElement.contains(x)).length > 1) break;
      el = el.parentElement;
    }
    cards.add(el);
  });
  const out = [];
  const seen = new Set();
  cards.forEach(el => {
    const urn = urnIn(el);
    if (!urn || seen.has(urn)) return;
    seen.add(urn);
    const link = pick(el, ['a.update-components-actor__meta-link', 'a.update-components-actor__container-link']) || [...el.querySelectorAll(actors)].find(a => txt(a));
    const by = ((el.querySelector("button[aria-label^='Open control menu for post by ']") || {getAttribute: () => ''}).getAttribute('aria-label') || '').replace(/^Open control menu for post by /, '');
    const author = pick(el, ['.update-components-actor__title span[aria-hidden="true"]', '.update-components-actor__name', '.update-components-actor__title']) || link;
    let sub = txt(pick(el, ['.update-components-actor__sub-description', '.update-components-actor__description']));
    let promoted = false;
    el.querySelectorAll('*').forEach(n => {
      if (n.children.length) return;
      const t = txt(n);
      if (t.length > 40) return;
      if (/^promoted\b/i.test(t)) promoted = true;
      else if (!sub && /^\d+\s*(s|m|h|d|w|mo|yr)\b/i.test(t)) sub = t;
    });
    let body = txt(pick(el, ['.update-components-text', '.feed-shared-update-v2__description', '.feed-shared-text', "[data-testid='expandable-text-box']", '.break-words']));
    if (!body) {
      for (const s of ["span[dir='ltr']", 'p', "div[dir='ltr']"]) {
        el.querySelectorAll(s).forEach(n => { const t = txt(n); if (t.length > body.length && !n.closest('button,' + actors)) body = t; });
        if (body) break;
      }
    }
    const title = pick(el, ['.update-components-article__title', '.update-components-entity__title', '.feed-shared-article__title', '.update-components-document__title']);
    const desc = pick(el, ['.update-components-article__description', '.update-components-entity__description', '.update-components-article__subtitle']);
    const alts = [];
    el.querySelectorAll('img[alt]').forEach(i => {
      if (i.closest('.update-components-actor') || i.closest(actors)) return;
      const a = (i.getAttribute('alt') || '').trim();
      if (a && a.length > 3 && !alts.includes(a)) alts.push(a);
    });
    out.push({urn, card: cardOf(el), author: by || txt(author), author_url: link ? link.href : '', sub: promoted ? 'promoted' : sub, body, title: txt(title), extra: txt(desc), alt: alts.slice(0, 6).join(' | ')});
  });
  return out;
}'''
EXPAND_JS = r'''() => { let n = 0; document.querySelectorAll("[data-testid='expandable-text-button']").forEach(b => { if (/more/i.test(b.innerText || b.textContent || '')) { b.click(); n++; } }); return n; }'''
def _to_post(item, cutoff):
    sub = item.get('sub') or ''
    if 'promoted' in sub.lower():
        return None
    published = tx.parse_relative_time(sub)
    if published and datetime.strptime(published, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc) < cutoff:
        return None
    urn = item['urn']
    author_url = (item.get('author_url') or '').split('?')[0] or None
    card = item.get('card')
    return {'external_id': urn, 'alias': f'card:{card}' if card and (not urn.startswith('card:')) else None, 'url': f'https://www.linkedin.com/feed/?card={urn[5:]}' if urn.startswith('card:') else tx.normalize_url(f'https://www.linkedin.com/feed/update/{urn}/'), 'author_name': tx.clean_text(item.get('author')).split('\n')[0] or None, 'author_url': author_url, 'title': tx.clean_text(item.get('title')) or None, 'body': tx.clean_text(item.get('body')) or None, 'alt_text': tx.clean_text(item.get('alt')) or None, 'extra_text': tx.clean_text(item.get('extra')) or None, 'published_at': published}
def read_items(page, browser=None):
    if page.evaluate(EXPAND_JS):
        page.wait_for_timeout(700)
    items = page.evaluate(EXTRACT_JS)
    return browser.resolve_links(page, items) if browser else items
def to_posts(items, lookback_days):
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    posts = []
    for it in items:
        try:
            p = _to_post(it, cutoff)
            if p:
                posts.append(p)
        except Exception:
            log.exception('Could not parse a feed item')
    return posts
def collect(browser, deep=False, lookback_days=7):
    page = browser.goto_feed()
    max_scrolls = 30 if deep else 4
    seen = {}
    stagnant = 0
    for _ in range(max_scrolls):
        items = read_items(page, browser)
        before = len(seen)
        for it in items:
            seen.setdefault(it['urn'], it)
        stagnant = stagnant + 1 if len(seen) == before else 0
        if stagnant >= 3:
            break
        browser.scroll(page)
    if not seen:
        browser.snapshot(page)
    posts = to_posts(seen.values(), lookback_days)
    log.debug('Collected %d posts from %d feed items', len(posts), len(seen))
    return posts