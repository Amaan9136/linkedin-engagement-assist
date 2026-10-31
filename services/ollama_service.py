import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
import requests
from .errors import PermanentError, ServiceUnavailable, TemporaryError
log = logging.getLogger('linkedin.ollama')
_usage = {'t': 0.0, 'v': None}
def _base(endpoint):
    p = urlsplit(endpoint)
    return f'{p.scheme}://{p.netloc}'
def generate(prompt, system, s):
    payload = {'model': s['ai_model'], 'prompt': prompt, 'system': system, 'stream': False, 'options': {'temperature': 0.7, 'num_predict': 1024}}
    try:
        r = requests.post(s['ollama_endpoint'], json=payload, timeout=(5, s['ai_timeout']))
    except requests.ConnectionError as e:
        raise ServiceUnavailable(f"Ollama is not reachable at {s['ollama_endpoint']}. Start it with 'ollama serve'.") from e
    except requests.Timeout as e:
        raise TemporaryError(f'Ollama did not answer within {s["ai_timeout"]}s') from e
    except requests.RequestException as e:
        raise TemporaryError(f'Ollama request failed: {e}') from e
    if r.status_code == 404:
        raise PermanentError(f"Model '{s['ai_model']}' not found. Run 'ollama pull {s['ai_model']}' (cloud models need 'ollama signin').")
    if r.status_code in (401, 403):
        raise PermanentError("Ollama rejected the request (not signed in?). Run 'ollama signin'.")
    if r.status_code == 429 or r.status_code >= 500:
        ra = r.headers.get('Retry-After', '')
        raise ServiceUnavailable(f'Ollama returned HTTP {r.status_code}', max(int(ra) if ra.isdigit() else 0, 60 if r.status_code == 429 else 0))
    if r.status_code != 200:
        raise PermanentError(f'Ollama returned HTTP {r.status_code}')
    try:
        data = r.json()
    except ValueError as e:
        raise TemporaryError('Ollama returned invalid JSON') from e
    text = (data.get('response') or '').strip()
    if not text:
        raise TemporaryError('Ollama returned an empty response')
    return text
def check(s):
    try:
        r = requests.get(_base(s['ollama_endpoint']) + '/api/tags', timeout=3)
        if r.status_code != 200:
            return {'status': 'down', 'message': f'HTTP {r.status_code}'}
        names = [m.get('name') for m in r.json().get('models', [])]
        if s['ai_model'] not in names:
            return {'status': 'model_missing', 'message': f"Model '{s['ai_model']}' is not listed by Ollama"}
        return {'status': 'up', 'message': 'OK'}
    except Exception as e:
        return {'status': 'down', 'message': str(e)[:200]}
def usage(s):
    if _usage['v'] and time.time() - _usage['t'] < 60:
        return _usage['v']
    try:
        rs = [requests.get(f'{_base(s["ollama_endpoint"])}/api/{p}', params=q, timeout=8) for p, q in (('usage', {'range': '24h'}), ('usage', {'range': '30d'}), ('balance', None))]
        bad = next((r for r in rs if r.status_code != 200), None)
        if bad is not None:
            v = {'status': 'error', 'message': f'Ollama cloud usage returned HTTP {bad.status_code}'}
        else:
            d, m, b = (r.json() for r in rs)
            inc = b.get('included') or {}
            ses, wk = (inc.get('session') or {}, inc.get('weekly') or {})
            tok = lambda x: (x.get('totals') or {}).get('input_tokens', 0) + (x.get('totals') or {}).get('output_tokens', 0)
            v = {'status': 'ok', 'tokens_24h': tok(d), 'tokens_30d': tok(m), 'requests_24h': (d.get('totals') or {}).get('request_count', 0), 'purchased_usd': (b.get('purchased') or {}).get('balance_usd'), 'session_left': ses.get('remaining_percent'), 'session_resets': ses.get('resets_at'), 'weekly_left': wk.get('remaining_percent'), 'weekly_resets': wk.get('resets_at'), 'left_usd': inc.get('balance_usd'), 'allowance_usd': inc.get('allowance_usd'), 'until': (inc.get('period') or {}).get('until')}
    except Exception as e:
        v = {'status': 'error', 'message': str(e)[:200]}
    _usage.update(t=time.time(), v=v)
    return v
def exhausted():
    v = _usage['v'] or {}
    hit = [v[k + '_resets'] for k in ('session', 'weekly') if v.get(k + '_left') is not None and v[k + '_left'] <= 5 and v.get(k + '_resets')]
    if v.get('allowance_usd') and v.get('left_usd') is not None and v['left_usd'] <= 0 and (not v.get('purchased_usd')) and v.get('until'):
        hit.append(v['until'])
    return min(3600, max(60, max((int((datetime.fromisoformat(t.replace('Z', '+00:00')) - datetime.now(timezone.utc)).total_seconds()) for t in hit)))) if hit else 0