import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import _resolve, _env, _env_bool
def main():
    from playwright.sync_api import sync_playwright
    profile = _resolve(_env('BROWSER_PROFILE_DIR', 'data/browser_profile'))
    profile.mkdir(parents=True, exist_ok=True)
    args = ['--disable-dev-shm-usage', '--disable-blink-features=AutomationControlled']
    if sys.platform.startswith('linux'):
        args.append('--password-store=basic')
    if _env_bool('BROWSER_NO_SANDBOX', False):
        args.append('--no-sandbox')
    kw = {'user_data_dir': str(profile), 'headless': False, 'args': args, 'viewport': {'width': 1280, 'height': 900}, 'ignore_default_args': ['--enable-automation']}
    if _env('CHROMIUM_EXECUTABLE'):
        kw['executable_path'] = _env('CHROMIUM_EXECUTABLE')
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(**kw)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto('https://www.linkedin.com/login')
        input('Log in to LinkedIn in the opened window, then press Enter here to save the session... ')
        ctx.close()
    print('Session saved to', profile)
if __name__ == '__main__':
    main()