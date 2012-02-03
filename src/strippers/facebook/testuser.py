# vim:fileencoding=utf-8
import logging
try:
    import json
except ImportError:
    try:
        from django.utils import simplejson as json
    except ImportError:
        import simplejson as json
from strippers.facebook.graphapi import FacebookGraphAPI, get_app_token

__author__ = 'otsuka'

log = logging.getLogger(__name__)


class TestUserAPI(object):

    def __init__(self, app_id, app_secret):
        self._app_id = app_id
        self._app_secret = app_secret
        self._api = FacebookGraphAPI('', app_id, app_secret)

    def create_test_user(self, name, installed=True, permissions=()):
        """
        テストユーザーを作成します。
        http://developers.facebook.com/docs/test_users/

        テストユーザーは 100 アカウント程度作れるらしい。
        http://forum.developers.facebook.net/viewtopic.php?id=94693

        @param name: テストユーザーの名前。姓と名の間は半角スペースで区切ります。
        @type name: str, unicode
        @param installed: 作成するテストユーザーに、アプリがインストールされた状態(OAuth 認可済み)にするか否か。デフォルトは True
        @type installed: bool
        @param permissions: アプリがインストールされた状態にする場合、認可されていることにするパーミッションのリスト
        @type permissions: list, tuple
        @rtype: dict
        """
        uri = u"%s%s/accounts/test-users" % (self._api.BASE_URL, self._app_id)
        scopes = ','.join(permissions)
        params = {
            'name'        : name,
            'permissions' : scopes,
            'method'      : 'post',
            'installed'   : installed,
        }
        res = self._api._send_api_request(uri, params, access_token=self._api.app_token)
        data = json.loads(res)
        return data

    def test_users(self):
        """
        このアプリに作成されているテストユーザーの一覧を返します。

        @return: 作成済みのテストユーザーのリスト
        @rtype: list
        """
        uri = u"%s%s/accounts/test-users" % (self._api.BASE_URL, self._app_id)
        params = { 'access_token': self._api.app_token }
        res = self._api._send_api_request(uri, params, access_token=self._api.app_token)
        data = json.loads(res)
        return data['data']

    def become_friends(self, test_user_id, test_user_token, test_user2_id, test_user2_token):
        """
        指定されたテストユーザーを友達にします。

        @param test_user_id: テストユーザー 1 の ID
        @type test_user_id: str, unicode
        @param test_user_token: テストユーザー 1 のアクセストークン
        @type test_user_token: str, unicode
        @param test_user2_id: テストユーザー 2 の ID
        @type test_user2_id: str, unicode
        @param test_user2_token: テストユーザー 2 のアクセストークン
        @type test_user2_token: str, unicode
        @return: 成功した場合 True
        @rtype: bool
        """
        uri = u"%s%s/friends/%s" % (self._api.BASE_URL, test_user_id, test_user2_id)
        params = { 'method': 'post', }
        res = self._api._send_api_request(uri, params, access_token=test_user_token)
        if res == 'true':
            uri = u"%s%s/friends/%s" % (self._api.BASE_URL, test_user2_id, test_user_id)
            res = self._api._send_api_request(uri, params, access_token=test_user2_token)
            return res == 'true'
        return False


