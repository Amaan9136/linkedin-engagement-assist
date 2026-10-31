from flask import Blueprint
from config import SETTING_SPECS, validate_settings
from database import models
from . import api, body, fail, ok
bp = Blueprint('settings_api', __name__)
def _public_specs():
    out = {}
    for k, v in SETTING_SPECS.items():
        out[k] = {'type': v['type'], 'label': v['label'], 'choices': v.get('choices'), 'min': v.get('min'), 'max': v.get('max')}
    return out
@bp.get('/api/settings')
@api
def get_settings():
    return ok(settings=models.all_settings(), specs=_public_specs())
@bp.put('/api/settings')
@api
def put_settings():
    data = body()
    if not data:
        return fail('No settings supplied')
    clean, errors = validate_settings(data)
    merged = {**models.all_settings(), **clean}
    if 'backoff_max' not in errors and merged['backoff_max'] < merged['backoff_base']:
        errors['backoff_max'] = 'must be >= backoff base'
    if errors:
        return fail('Some settings are invalid', 400, errors=errors)
    models.set_settings(clean)
    return ok(settings=models.all_settings(), message='Settings saved')
