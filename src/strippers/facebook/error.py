# vim:fileencoding=utf-8
import logging

__author__ = 'otsuka'

log = logging.getLogger(__name__)

class FacebookGraphAPIError(Exception):
    pass


class InvalidAuthCodeError(FacebookGraphAPIError):
    pass


class InvalidRequestError(FacebookGraphAPIError):
    pass


class InsufficientScopeError(FacebookGraphAPIError):

    def __init__(self, scope):
        super(InsufficientScopeError, self).__init__()
        self.scope = scope

    def __str__(self):
        return self.scope


class InvalidTokenError(FacebookGraphAPIError):

    def __init__(self, message):
        super(InvalidTokenError, self).__init__(message)


class ExpiredTokenError(InvalidTokenError):

    def __init__(self, message, auth_url=None):
        super(ExpiredTokenError, self).__init__(message)
        self.auth_url = auth_url

