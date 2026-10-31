class AppError(Exception):
    pass
class TemporaryError(AppError):
    pass
class ServiceUnavailable(TemporaryError):
    def __init__(self, msg='', retry_after=0):
        super().__init__(msg)
        self.retry_after = retry_after
class BrowserUnavailable(TemporaryError):
    pass
class PermanentError(AppError):
    pass
class AuthRequired(AppError):
    pass
class ActionUncertain(AppError):
    pass
class Deferred(AppError):
    def __init__(self, seconds, reason=''):
        super().__init__(reason)
        self.seconds = max(1, int(seconds))
        self.reason = reason