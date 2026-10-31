import logging
from urllib.parse import urlsplit
import requests
from .errors import PermanentError, ServiceUnavailable, TemporaryError
log = logging.getLogger('linkedin.ollama')
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