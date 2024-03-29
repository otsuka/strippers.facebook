# vim:fileencoding=utf-8
import logging
import types
import urllib2
from strippers.facebook.error import FacebookGraphAPIError
from strippers.facebook.util import memoized
from strippers.facebook.permission import PUBLISH_CHECKINS
from strippers.facebook.error import InsufficientScopeError

try:
    import json
except ImportError:
    try:
        from django.utils import simplejson as json
    except ImportError:
        import simplejson as json

__author__ = 'otsuka'

log = logging.getLogger(__name__)

class FbGraphObject(dict):

    def __init__(self, api, data=None, by_fql=False):
        """
        @param api: FacebookGraphAPI インスタンス
        @type api: FacebookGraphAPI
        @param data: オブジェクトのフィールドデータ
        @type data: dict
        @param by_fql: FQL クエリによった取得されたデータか否か
        @type by_fql: bool
        """
        super(FbGraphObject, self).__init__(self)

        self.api = api
        self.loaded = False
        self._by_fql = bool(by_fql)
        if data:
            if isinstance(data, types.DictType):
                self.update(data)
            else:
                raise TypeError

    @property
    def id(self):
        """
        オブジェクトの ID を返します。
        ID がセットされていない場合は None を返します。

        @return: オブジェクト ID
        @rtype: unicode
        """
        return unicode(self.get('id'))

    @property
    def uri(self):
        """
        このオブジェクトの URI を返します。

        @return: このオブジェクトの URI
        @rtype: unicode
        """
        return self.api.BASE_URL + self.id

    def load(self):
        """
        API にアクセスして、このオブジェクトの属性データを読み込みます。
        オブジェクトの id キーに適切な値がセットされている必要があります。
        """
        if not self.loaded:
            log.debug(u'%sオブジェクトのデータをロードします。[%s]', self.__class__.__name__, self.uri)
            res = self.api.get(self.uri)
            data = json.loads(res)
            try:
                self.update(data)
            except Exception, e:
                log.exception(u"Error at load(). [uri='%s', res='%s']", self.uri, res)
                raise
            self._by_fql = False
            self.loaded = True

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError, e:
            raise AttributeError, e.args[0]

    def __getitem__(self, key):
        if self._by_fql and hasattr(self, '_GRAPH_TO_FQL_FIELD_MAPPINGS'):
            mappings = getattr(self, '_GRAPH_TO_FQL_FIELD_MAPPINGS')
            key = mappings.get(key, key)

        if key in self:
            return super(FbGraphObject, self).__getitem__(key)
        else:
            if self.id:
                self.load()
                if key in self:
                    return super(FbGraphObject, self).__getitem__(key)
        raise KeyError(u"This object does not have '%s' field." % key)

    def get_aggressively(self, key, val=None):
        try:
            return self[key]
        except KeyError:
            return val


class FbUser(FbGraphObject):
    """
    ユーザーオブジェクト
    """

    _GRAPH_TO_FQL_FIELD_MAPPINGS = {
        'id'      : 'uid',
        'gender'  : 'sex',
        'birthday': 'birthday_date',
    }

    def __init__(self, api, data, load=False, by_fql=False):
        """
        @param api: FacebookGraphAPI インスタンス
        @type api: FacebookGraphAPI
        @param data: ユーザーの属性
        @type data: dict
        @param load: ユーザー属性を API から読み込む場合に True。
                     data パラメータに data['id'] としてユーザー ID が指定されている必要があります。
        @type load: bool
        @param by_fql: FQL クエリによった取得されたデータか否か
        @type by_fql: bool
        """
        FbGraphObject.__init__(self, api, data, by_fql=by_fql)
        if load:
            self.load()

    def picture(self, size='normal'):
        """
        プロフィール画像の URL を返します。

        @param size: 画像サイズ。'square', 'small', 'normal', 'large' のいずれかを指定します。
                     デフォルトは 'normal'
        @type size: str, unicode
        @return: 指定されたサイズのプロフィール画像の URL
        @rtype: unicode
        """
        if size not in ('square', 'small', 'normal', 'large'):
            raise TypeError
        return self.uri + '/picture?type=%s' % size

    def friends_fql(self, fields=None):
        """
        ユーザーの友達リストを返します。

        指定できるフィールドは次の URL を参照してください。
        http://developers.facebook.com/docs/reference/fql/user/

        デフォルトでは次のフィールドを取得します。これは取得に特別なパーミッションが必要のない
        フィールドです。
        'uid', 'name', 'first_name', 'middle_name','last_name', 'sex', 'locale',
        'pic_small_with_logo', 'pic_big_with_logo', 'pic_square_with_logo',
        'pic_with_logo', 'username'

        @todo: "friend_xxxx" のパーミッションによって、自動的に取得フィールドを増やしたい。
        と思ったけど、パーミッションのないフィールドをFQLで取得しようとすると null になるだけなのでいいや。

        @return: ユーザーの友達の FbUser オブジェクトリスト
        @rtype: list
        """
        if not fields:
            fields = ['uid', 'name', 'first_name', 'middle_name','last_name', 'sex', 'locale',
                      'pic_small_with_logo', 'pic_big_with_logo', 'pic_square_with_logo',
                      'pic_with_logo', 'username']
        else:
            fields = list(fields)
        if 'uid' not in fields:
            fields.append('uid')
        q = u"SELECT %s FROM user WHERE uid in (SELECT uid2 FROM friend WHERE uid1 = me()) ORDER BY name"
        select_fields = ', '.join(fields)
        q %= select_fields
        users = self.api.fql_query(q)
        results = []
        for user in users:
            # id フィールドをセット
            user['id'] = user['uid']
            results.append(FbUser(self.api, user, by_fql=True))
        return results

    def friends(self):
        """
        ユーザーの友達リストを返します。

        @return: ユーザーの友達の FbUser オブジェクトリスト
        @rtype: list
        """
        url = self.uri + '/friends'
        res = self.api.get(url)
        data = json.loads(res)
        return [ FbUser(self.api, user) for user in data['data'] ]

    def friends_with_local_name(self):
        """
        @note: まだよく分からん。

        @return: ユーザーの友達の FbUser オブジェクトリスト
        @rtype: list
        """
        fields = ['id', 'name', 'can_post', 'pic', 'pic_square', 'pic_small', 'pic_big', 'pic_crop', 'username']
        select_fields = ', '.join(fields)
        q = u"SELECT %s FROM profile WHERE id IN (SELECT uid2 FROM friend WHERE uid1 = me()) ORDER BY name" % select_fields
        users = self.api.fql_query(q)
        return [ FbUser(self.api, user, by_fql=True) for user in users['data'] ]

    @property
    def friend_count(self):
        """
        ユーザーの友達の数を返します。

        @return: 友達数
        @rtype: int
        """
        q = 'SELECT friend_count FROM user WHERE uid = %s' % self.id
        res = self.api.fql_query(q)
        return res[0]['friend_count']

    def mutual_friends(self, friend):
        """
        指定された友達との共通の友達リストを返します。

        @param friend: 共通の友達を調べる友達
        @return: ユーザーの共通の友達の FbUser オブジェクトリスト
        @rtype: list
        """
        if isinstance(friend, FbUser):
            friend = friend.id
        url = self.uri + '/mutualfriends/%s' % friend
        res = self.api.get(url)
        data = json.loads(res)
        return [ FbUser(self.api, user) for user in data['data'] ]

    def albums(self):
        """
        @todo: ページング
        """
        uri = self.uri + '/albums'
        params = { 'limit': 100 }
        res = self.api.get(uri, params)
        data = json.loads(res)
        results = [ FbAlbum(self.api, d) for d in data['data'] ]
        return results

    def create_album(self, name, message=None, privacy=None):
        """
        ユーザーのアルバムを作成します。

        プライバシー設定については以下のページを参照してください。
        http://developers.facebook.com/docs/reference/api/user/#albums

        @param name: アルバム名
        @type name: str
        @param message: アルバムの説明文
        @type message: str
        @param privacy: プライバシー設定
        @type privacy: dict
        @return: 作成したアルバムの FbAlbum オブジェクト。id のみセットされています。
        @rtype: FbAlbum
        """
        params = { 'name': name }
        if message:
            params['message'] = message
        if privacy:
            if not isinstance(privacy, types.DictType):
                raise TypeError
            params['privacy'] = json.dumps(privacy)
        uri = self.uri + '/albums'
        res = self.api.send_post_request(uri, params)
        data = json.loads(res)
        return FbAlbum(self.api, data)

    def upload_photo(self, source, message=None):
        """
        写真をアップロードします。
        このメソッドでは、アプリ用のアルバムが自動的に作成され、そのアルバムに写真がアップされます。
        特定のアルバムにアップロードする場合は、FbAlbum.upload_photo() メソッドを使ってください。

        @param source: 画像ファイルの file オブジェクト
        @type source: file
        @param message: メッセージ
        @type message: str
        @return: アップロードした写真の FbPhoto オブジェクト。id のみセットされています。
        @rtype: FbPhoto
        """
        uri = self.uri + '/photos'
        params = { 'source': source }
        if message:
            params['message'] = message
        res = self.api.send_post_request(uri, params, self.api.CONTENT_TYPE_MULTIPART)
        data = json.loads(res)
        return FbPhoto(self.api, data)

    def posts(self, limit=-1, fetch=25, offset=0, since=None, until=None):
        """
        ユーザーのフィードへの投稿リストを返します。

        @param limit: 取得する投稿の件数。デフォルトの -1 の場合は、上限なしとなります
        @type limit: int
        @param fetch: 一度に取得する投稿件数。API には limit パラメータとして渡される値
        @type fetch: int
        @param offset: 取得開始位置
        @type offset: int
        @param since: 取得開始日時。Unix タイム
        @type since: int
        @param until: 取得終了日時。Unix タイム
        @type until: int
        @return: FbPost オブジェクトのジェネレーター
        @rtype: generator
        """
        uri = self.uri + '/posts'
        params = { 'limit': fetch, 'offset': offset, }
        if since: params['since'] = int(since)
        if until: params['until'] = int(until)

        res = self.api.get(uri, params)
        data = json.loads(res)
        posts = data['data']
        count = 0

        while len(posts) > 0:
            next_uri = data['paging']['next']
            for p in posts:
                if count >= int(limit) > -1:
                    return
                yield FbPost(self.api, p)
                count += 1

            req = urllib2.Request(next_uri)
            res = self.api.send_request(req)
            data = json.loads(res)
            posts = data['data']

    def post(self, message=None, link=None, picture=None, name=None, caption=None, description=None, actions=(), privacy=None, object_attachment=None):
        """
        ウォールに書き込みます。
        message、link のどらちかは必須です。

        @param message:
        @param link:
        @param picture:
        @param name:
        @param caption:
        @param description:
        @param actions:
        @param privacy:
        @param object_attachment:
        @return: post ID
        @rtype: unicode
        """
        uid = 'me'
        return self.api.post(uid, message, link, picture, name, caption, description, actions, privacy, object_attachment)

    @memoized
    def permissions(self):
        """
        ユーザーがアプリケーションに認可しているパーミッション(スコープ)のリストを返します。

        @return: 認可スコープのリスト
        @rtype: tuple
        """
        return self.api.permissions()

    def has_permission(self, permission):
        """
        指定されたパーミッション(スコープ)がユーザーに認可されているか判定します。

        @param permission: チェックするパーミッション。リストで指定した場合、すべてのパーミッションが認可されているかを確認します。
        @return: パーミッションが認可されていれば True
        @rtype: bool
        """
        return self.api.has_permission(permission)

    def checkin(self, place, latitude, longitude, tags=(), message=None, link=None, picture=None, privacy=None):
        """
        指定された場所にチェックインします。

        http://developers.facebook.com/docs/reference/api/user/#checkins

        @param place: Place ID
        @param latitude: 緯度
        @param longitude: 経度
        @param tags: 一緒にいる友達の ID リスト
        @param message: メッセージ
        @param link: リンク
        @param picture: picture?
        @param privacy:
        @return: チェックインオブジェクト
        @rtype: FbCheckin
        """
        if place is None or latitude is None or longitude is None:
            raise TypeError
        if not self.has_permission(PUBLISH_CHECKINS):
            raise InsufficientScopeError(PUBLISH_CHECKINS)

        uri = self.uri + '/checkins'
        coordinates = { 'latitude': str(latitude), 'longitude': str(longitude) }
        params = {
            'place': str(place),
            'coordinates': json.dumps(coordinates),
        }
        if len(tags) > 0:
            params['tags'] = u','.join(tags)
        if message:
            params['message'] = message
        if link:
            params['link'] = link
        if picture:
            params['picture'] = picture
        if privacy:
            params['privacy'] = json.dumps(privacy)

        res = self.api.send_post_request(uri, params)
        data = json.loads(res) # {u'id': u'10150583583804571'}
        return FbCheckin(self.api, data)

    def apprequest(self, message, data=None):
        """
        @todo: 戻り値どうする？
        """
        url = self.uri + '/apprequests'
        params = { 'message': message }
        if data:
            params['data'] = data

        res = self.api.send_post_request_for_app(url, params)
        #print res # {"request":"204684836294250","to":["566419570"]}
        return res


class FbPost(FbGraphObject):
    """
    投稿オブジェクト
    """
    def __init__(self, api, data):
        FbGraphObject.__init__(self, api, data)


class FbAlbum(FbGraphObject):
    """
    アルバムオブジェクト
    """
    def __init__(self, api, data):
        FbGraphObject.__init__(self, api, data)

    def photos(self, limit=25, offset=0):
        uri = self.uri + '/photos'
        params = { 'limit': limit, 'offset': offset }
        res = self.api.get(uri, params)
        data = json.loads(res)
        photo_dicts = data['data']

        while len(photo_dicts) > 0:
            if 'next' in data['paging']:
                next_url = data['paging']['next']
            else:
                next_url = None

            for p in photo_dicts:
                yield FbPhoto(self.api, p)

            if next_url:
                req = urllib2.Request(next_url)
                res = self.api.send_request(req)
                data = json.loads(res)
                photo_dicts = data['data']

    def upload_photo(self, source, message=None):
        """
        このアルバムに写真をアップロードします。

        @param source: 画像ファイルの file オブジェクト
        @type source: file
        @param message: メッセージ
        @type message: str
        @return: アップロードした写真の FbPhoto オブジェクト。id のみセットされています。
        @rtype: FbPhoto
        """
        uri = self.uri + '/photos'
        params = { 'source': source }
        if message:
            params['message'] = message
        res = self.api.send_post_request(uri, params, self.api.CONTENT_TYPE_MULTIPART)
        data = json.loads(res)
        return FbPhoto(self.api, data)


class FbPhoto(FbGraphObject):
    """
    写真オブジェクト
    """
    def __init__(self, api, data):
        FbGraphObject.__init__(self, api, data)

    def tag(self, to, x=None, y=None):
        """
        指定されたユーザーをこの写真にタグ付けます。

        @param to: タグ付けするユーザーの ID
        @param x: タグ付けする開始 X 座標。パーセンテージ
        @type x: float
        @param x: タグ付けする開始 Y 座標。パーセンテージ
        @type y: float
        @return: タグ付けに成功したら自身の FbPhoto オブジェクトを返します。メソッドチェーンでタグ付けできるようにするため
        @rtype: FbPhoto
        """
        uri = self.uri + '/tags'
        params = { 'to': to }
        if x:
            params['x'] = float(x)
        if y:
            params['y'] = float(y)
        res = self.api.send_post_request(uri, params)
        if res == 'true':
            return self
        else:
            raise FacebookGraphAPIError(u"写真へのタグ付けに失敗しました。[id='%s']" % self.id)

class FbCheckin(FbGraphObject):
    """
    チェックインオブジェクト
    """
    def __init__(self, api, data):
        FbGraphObject.__init__(self, api, data)

