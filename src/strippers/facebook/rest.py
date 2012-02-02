# vim:fileencoding=utf-8
import logging
import types
from xml.etree import ElementTree as ET

__author__ = 'otsuka'

log = logging.getLogger(__name__)

class RestAPI(object):

    BASE_URI = 'https://api.facebook.com/method/'

    def __init__(self, api):
        self.api = api

    def notifications_send_email(self, recipient_id, subject, text):
        if isinstance(recipient_id, types.ListType):
            if 1 <= len(recipient_id) <= 100:
                recipient_id = ','.join(recipient_id)
            else:
                raise TypeError

        params = {
            'recipients' : str(recipient_id),
            'subject'    : subject,
            'text'       : text,
            }
        uri = self.BASE_URI + 'notifications.sendEmail'
        res = self.api.get(uri, params)
        return self._extract_notification_id(res)

    def _extract_notification_id(self, res):
        """
        以下のようなメール送信後のXMLレスポンスから、IDを抽出して返します。

        <?xml version="1.0" encoding="UTF-8"?>
        <notifications_sendEmail_response xmlns="http://api.facebook.com/1.0/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://api.facebook.com/1.0/ http://api.facebook.com/1.0/facebook.xsd">1234567890</notifications_sendEmail_response>

        @return: Notification ID
        @rtype: str
        """
        tree = ET.fromstring(res)
        return tree.text

