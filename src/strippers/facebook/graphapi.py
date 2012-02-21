# vim:fileencoding=utf-8
import base64
import hashlib
import hmac
from urllib import urlencode
import types
import urllib2
import re
import logging
import gzip
from datetime import datetime, timedelta
import MultipartPostHandler
from strippers.facebook.error import InvalidAuthCodeError, InvalidTokenError, FacebookGraphAPIError, ExpiredTokenError, InsufficientScopeError, InvalidRequestError
from strippers.facebook.graphobject import FbUser, FbPost
from strippers.facebook.rest import RestAPI
from strippers.facebook.util import memoized

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO
try:
    from urlparse import parse_qs
except ImportError:
    from cgi import parse_qs
try:
    import json
except ImportError:
    try:
        from django.utils import simplejson as json
    except ImportError:
        import simplejson as json

log = logging.getLogger(__name__)
#log_handler = logging.StreamHandler()
#log_handler.setLevel(logging.DEBUG)
#log.addHandler(log_handler)

__version__ = '0.7b'

AUTHORIZATION_URI = u'https://www.facebook.com/dialog/oauth'
TOKEN_URI         = u'https://graph.facebook.com/oauth/access_token'

class FacebookGraphAPI(object):

    CONTENT_TYPE_MULTIPART = u'multipart/form-data'
    CONTENT_TYPE_JSON      = u'application/json; charset=utf-8'

    BASE_URL = u'https://graph.facebook.com/'

    def __init__(self, access_token, app_id=None, app_secret=None, enable_gzip=False):
        """

        @param access_token: 取得済みのアクセストークン
        @type access_token: str
        @param app_id: Facebook アプリの App ID。特定の API メソッドを使用する場合に必要になります
        @type app_id: str
        @param app_secret: Facebook アプリの App Secret。特定の API メソッドを使用する場合に必要になります
        @type app_secret: str
        @param enable_gzip: 通信時に Gzip 圧縮を有効にするか否か
        @type enable_gzip: bool
        """
        self._app_id = app_id
        self._app_secret = app_secret
        self._access_token = access_token # アクセストークンを変更されたくないため _access_token にセット
        self.enable_gzip = enable_gzip
        self.expired_at = None

    @property
    def access_token(self):
        """
        アクセストークンを返します。
        @return: アクセストークン
        @rtype: str
        """
        return self._access_token

    def _create_request(self, uri, http_method):
        """
        指定された HTTP メソッドの urllib2.Request インスタンスを返します。
        DELETE、PUT メソッドの Request インスタンスを作成する目的を想定しています。

        @param uri: URI
        @type uri: str, unicode
        @param http_method: HTTP メソッド。'GET', 'POST', 'DELETE', 'PUT' のいずれか
        @type http_method: str, unicode
        @return: Request インスタンス
        @rtype: urllib2.Request
        """
        if http_method not in ('GET', 'POST', 'DELETE', 'PUT'):
            raise TypeError('Invalid HTTP method.')

        class MethodCustomRequest(urllib2.Request):
            def get_method(self):
                return http_method

        return MethodCustomRequest(uri)

    def _build_request(self, uri, http_method=None):
        if http_method in (None, 'GET', 'POST'):
            req = urllib2.Request(uri)
        else:
            req = self._create_request(uri, http_method)
        return req

    def _parse_error(self, e):
        """
        API アクセスのエラーレスポンスから WWW-Authenticate ヘッダにセットされた情報を名前と値の dict 形式で返します。

        @rtype: dict
        """
        headers = e.info()
        value = headers.getheader('WWW-Authenticate')
        if value:
            value = value[len('OAuth '):]
            value = re.sub(r' "', '\t', value)
            value = re.sub(r'"', '', value)
            value = value.split('\t')
            if len(value) > 2:
                return {
                  'error': value[1],
                  'message': value[2],
                }
        return {}

    @staticmethod
    def to_utf8(val):
        if isinstance(val, types.UnicodeType):
            return val.encode('utf-8')
        return val

    @staticmethod
    def encode_params(params):
        """params に含まれるユニコード文字列を utf-8 に変換します。

        @param params: 対象の dict
        @type params: dict
        @rtype: dict
        """
        results = {}
        for key, val in params.items():
            results[FacebookGraphAPI.to_utf8(key)] = FacebookGraphAPI.to_utf8(val)
        return results

    def send_post_request(self, uri, params=None, content_type=None):
        return self._send_api_request(uri, params, 'POST', content_type)

    def send_post_request_for_app(self, uri, params=None, content_type=None):
        return self._send_api_request(uri, params, 'POST', content_type, use_app_token=True)

    def send_get_request(self, uri, params=None):
        return self.get(uri, params)

    def get(self, uri, params=None):
        return self._send_api_request(uri, params)

    def send_put_request(self, uri, params=None, content_type=None):
        return self._send_api_request(uri, params, 'PUT', content_type)

    def send_delete_request(self, uri, params=None):
        return self._send_api_request(uri, params, 'DELETE')

    def _send_api_request(self, uri, params=None, http_method='GET', content_type=None,
                          access_token=None, use_app_token=False, try_count=1):
        """
        @param uri: リクエスト URI
        @type uri: str, unicode
        @param params: リクエストパラメータ。
        @type params: dict または str
        @param http_method: リクエストの HTTP メソッドを示す文字列。'GET'、'POST'、'DELETE'。デフォルトは 'GET'
        @type http_method: str
        @param content_type: Content-Type
        @type content_type: str
        """
        if params is None:
            data = ''
        elif isinstance(params, types.DictType):
            # MultipartPostHandler は urlencode() を勝手にやってくれるので、
            # multipart 引数が指定されている場合は urlencode() しない。
            params = self.encode_params(params)
            data = params if content_type == self.CONTENT_TYPE_MULTIPART else urlencode(params)
        else:
            data = str(self.to_utf8(params))

        http_method = http_method.upper()

        if not access_token:
            uri += '?access_token=' + self.access_token
        else:
            uri += '?access_token=' + access_token

        if use_app_token:
            uri += '&app_access_token=' + self.app_token

        if http_method in ('POST', 'PUT'):
            req = self._build_request(uri, http_method)
            req.add_data(data)
        else: # GET or DELETE
            if data:
                uri += '&' + str(data)
            req = self._build_request(uri, http_method)
        return self.send_request(req, content_type)

    def send_request(self, req, content_type=None):
        if self.enable_gzip:
            req.add_header('Accept-Encoding', 'gzip,deflate')

        if content_type is not None:
            if content_type == self.CONTENT_TYPE_MULTIPART:
                opener = urllib2.build_opener(MultipartPostHandler.MultipartPostHandler)
            else:
                opener = urllib2.build_opener()
                req.add_header('Content-Type', content_type)
        else:
            opener = urllib2.build_opener()

        try:
            f = opener.open(req)
            if f.info().get('Content-Encoding', '') == 'gzip':
                return gzip.GzipFile('', 'r', 0, StringIO(f.read())).read()
            else:
                return f.read()
        except urllib2.HTTPError, e:
            if 400 <= e.code < 500:
                error_info = self._parse_error(e)
                error_code = error_info.get('error')
                if error_code == 'expired_token': # アクセストークンの有効期限切れ
                    raise ExpiredTokenError(error_info.get('message'))
                elif error_code == 'insufficient_scope': # アクセスに必要なスコープが認可されていない
                    raise InsufficientScopeError(error_info.get('scope'))
                elif error_code == 'invalid_request': # 不正なリクエスト内容
                    raise InvalidRequestError(error_info.get('message'))
                elif error_code == 'invalid_token': # 不正なアクセストークン
                    raise InvalidTokenError(error_info.get('message'))
                else: # その他
                    raise
            else:
                raise

    def fql_query(self, query):
        uri = self.BASE_URL + 'fql'
        res = self.get(uri, {'format': 'json', 'q': query})
        result = json.loads(res)
        if 'error_code' in result and 'error_msg' in result:
            error_code = result['error_code']
            if error_code == 190:
                raise InvalidTokenError(result['error_msg'])
            else:
                raise FacebookGraphAPIError(unicode(error_code) + u': ' + result['error_msg'])
        return result['data']

    AVAILABLE_SEARCH_TYPES = (u'post', u'user', u'page', u'event', u'group', u'place', u'checkin')

    def search(self, type, q=None, **kwargs):
        """
        Graph オブジェクトを検索します。

        @todo: 結果のページング

        @param type: Graph オブジェクトの種類。'post','user','page','event','group','place','checkin'のいずれか。
        @type type: str, unicode
        @param q: 検索キーワード
        @type q: str, unicode
        @param kwargs:
        @return: 検索結果の dict リスト
        @rtype: list
        """
        if type not in self.AVAILABLE_SEARCH_TYPES:
            raise TypeError

        uri = self.BASE_URL + u'/search'
        params = {'type': type}
        if q:
            params['q'] = q
        params.update(kwargs)
        res = self.get(uri, params)
        data = json.loads(res)
        return data['data']

    def search_place(self, q, latitude=None, longitude=None, distance=None):
        """
        場所を検索します。

        結果は次のような dict のリストです。
        {u'category': u'Train station',
         u'id': u'204173452939599',
         u'location': {u'city': u'Setagaya-ku',
                       u'country': u'Japan',
                       u'latitude': 35.633316264221001,
                       u'longitude': 139.66127502838},
         u'name': u'Komazawa-daigaku Station'}

        @todo: 結果のページング

        @param q: 検索キーワード
        @type q: str, unicode
        @param latitude: 中心地の緯度
        @param longitude: 中心地の経度
        @param distance: 中心地からの距離。単位はメートル
        @return: 検索結果の dict リスト
        @rtype: list
        """
        if (latitude is None and longitude is not None) or (latitude is not None and longitude is None):
            raise TypeError
        if distance and (latitude is None or longitude is None):
            raise TypeError

        params = {}
        if latitude and longitude:
            params['center'] = unicode(latitude) + u',' + unicode(longitude)
        if distance:
            params['distance'] = distance
        return self.search('place', q, **params)

    @property
    @memoized
    def app_token(self):
        """
        アプリケーションアクセストークン(app access token)を取得します。
        http://developers.facebook.com/docs/authentication/#applogin

        @return: アプリケーションアクセストークン
        @rtype: str
        """
        return get_app_token(self._app_id, self._app_secret)

    @property
    def rest_api(self):
        """
        @return: RestAPI オブジェクト
        @rtype: RestAPI
        """
        return RestAPI(self)

    def user(self, uid='me'):
        """
        @rtype: strippers.facebook.graphobject.FbUser
        """
        return FbUser(self, {'id': uid})

    @property
    def me(self):
        return self.user()

    def post(self, uid=u'me', message=None, link=None, picture=None, name=None, caption=None, description=None, actions=(), privacy=None, object_attachment=None):
        """
        指定されたユーザーのウォールに書き込みます。
        message、link のどらちかは必須です。

        @param uid: ユーザー ID
        @param message: メッセージ
        @param link: リンク URL
        @param picture:
        @param name:
        @param caption:
        @param description:
        @param actions:
        @param privacy:
        @param object_attachment:
        @return: 行った投稿の FbPost オブジェクト。id のみセットされます
        @rtype: FbPost
        """
        url = self.BASE_URL + '%s/feed' % uid

        params = {}
        if message:
            params['message'] = message
        if link:
            params['link'] = link
        if name:
            params['name'] = name
        if picture:
            params['picture'] = picture
        if caption:
            params['caption'] = caption
        if description:
            params['description'] = description
        if privacy:
            params['privacy'] = privacy
        if object_attachment:
            params['object_attachment'] = object_attachment

        res = self.send_post_request(url, params)
        data = json.loads(res)
        return FbPost(self, data)

    @memoized
    def permissions(self):
        """
        ユーザーがアプリケーションに認可しているパーミッション(スコープ)のリストを返します。

        @return: 認可スコープのリスト
        @rtype: tuple
        """
        uri = self.BASE_URL + u'me/permissions'
        res = self.get(uri)
        data = json.loads(res)
        results = [ permission for permission, val in data['data'][0].items() if val == 1 ]
        return tuple(results)

    def has_permission(self, permission):
        """
        指定されたパーミッション(スコープ)がユーザーに認可されているか判定します。

        @param permission: チェックするパーミッション。リストで指定した場合、すべてのパーミッションが認可されているかを確認します。
        @return: パーミッションが認可されていれば True
        @rtype: bool
        """
        if isinstance(permission, types.StringTypes):
            return permission in self.permissions()
        elif isinstance(permission, (types.ListType, types.TupleType)):
            permissions = self.permissions()
            for p in permission:
                if p not in permissions:
                    return False
            return True
        else:
            raise TypeError

    def extend_access_token_expiration(self):
        """
        Client-side OAuth や署名リクエストから取得したアクセストークンの有効期限を延長します。

        @return: 新しいアクセストークン
        @rtype: str
        """
        params = {
            'client_id'    : self._app_id,
            'client_secret': self._app_secret,
            'grant_type'   : 'fb_exchange_token',
            'fb_exchange_token': self.access_token,
            }
        params = self.encode_params(params)
        url = TOKEN_URI + '?' + urlencode(params)
        res = urllib2.urlopen(url)
        res = res.read()
        data = parse_qs(res)
        self._access_token = data['access_token'][0]
        return self._access_token


def get_app_token(app_id, app_secret):
    """
    アプリケーションアクセストークン(app access token)を取得します。
    http://developers.facebook.com/docs/authentication/#applogin

    @return: アプリケーションアクセストークン
    @rtype: str
    """
    params = {
        'client_id'    : app_id,
        'client_secret': app_secret,
        'grant_type'   : 'client_credentials',
        }

    params = FacebookGraphAPI.encode_params(params)
    url = TOKEN_URI + '?' + urlencode(params)
    res = urllib2.urlopen(url)
    res = res.read()
    data = parse_qs(res)
    return data['access_token'][0]

def get_auth_url(app_id, scopes, redirect_uri, state=None, display=None):
    """
    OAuth 認可ページ の URL を返します。

    @param app_id: Facebook アプリの App ID
    @type app_id: str, unicode
    @param scopes: 認可を求めるパーミッションのリスト
    @type scopes: list, tuple
    @param redirect_uri: 認可後のリダイレクト先 URL
    @type redirect_uri: str, unicode
    @param state:
    @param display: 認可ダイアログの表示方法。'page', 'popup', 'iframe', 'touch', 'wap' のいずれか。デフォルトは 'page'
    @type display: str, unicode
    @return: OAuth 認可ページの URL
    @rtype: str
    """
    params = {
        'client_id'     : app_id,
        'response_type' : 'code',
        'redirect_uri'  : redirect_uri,
        }
    if state:
        params['state'] = state
    if display:
        if display in ('page', 'popup', 'iframe', 'touch', 'wap'):
            params['display'] = display
        else:
            raise ValueError, "'%s' is invalid for display." % display
    params['scope'] = ','.join(scopes)
    return AUTHORIZATION_URI + '?' + urlencode(params)

def initialze_by_auth_code(app_id, app_secret, auth_code, redirect_uri):
    """

    @param app_id: Facebook アプリの App ID
    @type app_id: str, unicode
    @param app_secret: アプリケーションシークレット
    @type app_secret: str, unicode
    @param auth_code: Auth コード
    @type auth_code: str
    @param redirect_uri: リダイレクト URI
    @type redirect_uri: str
    @return: FacebookGraphAPI インスタンス
    @rtype: FacebookGraphAPI
    """
    params = {
        'grant_type'    : 'authorization_code',
        'client_id'     : app_id,
        'client_secret' : app_secret,
        'code'          : auth_code,
        'redirect_uri'  : redirect_uri
    }
    try:
        res = urllib2.urlopen(TOKEN_URI, urlencode(params)).read()
    except urllib2.HTTPError, e:
        if e.code == 401:
            msg = u'Auth code "%s" is invalid. (It maybe expired.)' % auth_code
            log.warning(msg)
            raise InvalidAuthCodeError(msg)
        else:
            raise

    tokens = parse_qs(res)
    access_token = tokens['access_token'][0]
    if 'expires' in tokens:
        expires = int(tokens['expires'][0])
        log.debug(u"expires: %s", expires)
        expired_at = datetime.now() + timedelta(seconds=expires)
        log.debug(u"Access token expires at %s.", expired_at)
    else:
        expired_at = None

    api = FacebookGraphAPI(access_token, app_id, app_secret)
    api.expired_at = expired_at
    return api

def initialize_by_cookie(app_id, app_secret, cookies):
    """
    Facebook JavaScript SDK で OAuth 認可した後に、サーバに送信された
    リクエストに含まれるクッキーから認可ユーザーのアクセストークンを取得し、
    FacebookGraphAPI オブジェクトを生成します。

    @param app_id: Facebook アプリの App ID
    @type app_id: str, unicode
    @param app_secret: アプリケーションシークレット
    @type app_secret: str, unicode
    @param cookies: クッキー
    @type cookies: dict
    @return: FacebookGraphAPI インスタンス
    @rtype: FacebookGraphAPI
    """
    signed_data = cookies.get("fbsr_%s" % app_id)
    if not signed_data:
        log.error(u"指定されたクッキーに Facebook ユーザーデータがありませんでした。")
        return None
    parsed_request = parse_signed_request(signed_data, app_secret)
    auth_code = parsed_request['code']
    redirect_uri = ''
    return initialze_by_auth_code(app_id, app_secret, auth_code, redirect_uri)

def initialze(app_id, app_secret, auth_code_or_cookies, redirect_uri=''):
    if isinstance(auth_code_or_cookies, types.DictType):
        return initialize_by_cookie(app_id, app_secret, auth_code_or_cookies)
    elif isinstance(auth_code_or_cookies, types.StringTypes):
        return initialze_by_auth_code(app_id, app_secret, str(auth_code_or_cookies), redirect_uri)
    else:
        raise TypeError

def parse_signed_request(signed_request, app_secret):
    """

    https://github.com/pythonforfacebook/facebook-sdk から

    Return dictionary with signed request data.

    We return a dictionary containing the information in the signed_request. This will
    include a user_id if the user has authorised your application, as well as any
    information requested in the scope.

    If the signed_request is malformed or corrupted, False is returned.

    @param signed_request:
    @type signed_request: str
    @param app_secret:
    @type app_secret: str
    @rtype: dict
    """
    try:
        l = signed_request.split('.', 2)
        encoded_sig = str(l[0])
        payload = str(l[1])
        sig = base64.urlsafe_b64decode(encoded_sig + "=" * ((4 - len(encoded_sig) % 4) % 4))
        data = base64.urlsafe_b64decode(payload + "=" * ((4 - len(payload) % 4) % 4))
    except IndexError:
        return False # raise ValueError('signed_request malformed')
    except TypeError:
        return False # raise ValueError('signed_request had corrupted payload')

    data = json.loads(data)
    if data.get('algorithm', '').upper() != 'HMAC-SHA256':
        return False # raise ValueError('signed_request used unknown algorithm')

    expected_sig = hmac.new(str(app_secret), msg=payload, digestmod=hashlib.sha256).digest()
    if sig != expected_sig:
        return False # raise ValueError('signed_request had signature mismatch')

    return data

