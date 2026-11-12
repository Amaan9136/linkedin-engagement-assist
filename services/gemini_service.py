import logging
import requests
from config import api_keys
from .errors import AppError, PermanentError, ServiceUnavailable, TemporaryError
log = logging.getLogger('linkedin.gemini')
URL = 'https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent'
def keys():
    return api_keys('GEMINI_API_KEY')
def _generate(prompt, system, s, key):
    payload = {'systemInstruction': {'parts': [{'text': system}]}, 'contents': [{'role': 'user', 'parts': [{'text': prompt}]}], 'generationConfig': {'temperature': 0.7, 'maxOutputTokens': 2048}}
    try:
        r = requests.post(URL.format(s['gemini_model']), json=payload, headers={'x-goog-api-key': key}, timeout=(5, s['ai_timeout']))
    except requests.Timeout as e:
        raise TemporaryError(f'Gemini did not answer within {s["ai_timeout"]}s') from e
    except requests.RequestException as e:
        raise TemporaryError(f'Gemini request failed: {e}') from e
    if r.status_code in (400, 401, 403, 404):
        raise PermanentError(f'Gemini rejected the request (HTTP {r.status_code})')
    if r.status_code == 429 or r.status_code >= 500:
        raise ServiceUnavailable(f'Gemini returned HTTP {r.status_code}')
    if r.status_code != 200:
        raise PermanentError(f'Gemini returned HTTP {r.status_code}')
    try:
        text = ''.join(p.get('text', '') for p in r.json()['candidates'][0]['content']['parts']).strip()
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise TemporaryError('Gemini returned an unusable response') from e
    if not text:
        raise TemporaryError('Gemini returned an empty response')
    return text
def generate(prompt, system, s):
    err = None
    ks = keys()
    for i, key in enumerate(ks, 1):
        try:
            return _generate(prompt, system, s, key)
        except AppError as e:
            err = e
            log.warning('Gemini key %d/%d failed: %s', i, len(ks), e)
    raise err
