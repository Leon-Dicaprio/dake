"""官方聊天接口的 HTTP 客户端，只负责日期粒度取数，不依赖业务事件。"""

from datetime import date, datetime
from http.client import HTTPException
import json
import re
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


OFFICIAL_URL = "https://ts.qiniu.io/api/mars_alert/qq/chatRecords"


class ChatRecordsError(RuntimeError):
    """对外只提供脱敏的网络或响应错误，避免异常携带聊天正文。"""


class TransientChatRecordsError(ChatRecordsError):
    """临时取数错误可由调度层有界重试，不包含协议或鉴权失败。"""


def validate_uid(uid: str) -> None:
    """限制客户标识字符，也保护使用该标识组成的本地缓存路径。"""
    if not isinstance(uid, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", uid):
        raise ValueError("客户 UID 必须是安全的字母、数字、下划线或连字符标识")


def validate_dates(start: date, end: date) -> None:
    """官方参数只有日期，含首尾；不在这里假设小时级取数协议。"""
    if not all(isinstance(item, date) and not isinstance(item, datetime) for item in (start, end)):
        raise ValueError("取数参数必须是日期，不是时间戳")
    if start > end:
        raise ValueError("取数起始日期不能晚于结束日期")


class _NoRedirect(HTTPRedirectHandler):
    """不把客户 UID 和取数范围跟随重定向发送到其他地址。"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """拒绝重定向，避免将客户标识随 POST 请求发送到未确认的地址。"""
        return None


class ChatRecordsClient:
    """调用已正式说明的只读取数 POST，不臆造鉴权、分页或替代地址。"""

    def __init__(self, url: str = OFFICIAL_URL, timeout: float = 30, retries: int = 2):
        if url != OFFICIAL_URL:
            raise ValueError("当前只允许使用已正式说明的 chatRecords 地址")
        if timeout <= 0 or retries < 0:
            raise ValueError("超时须大于零，重试次数不能为负数")
        self.url = url
        self.timeout = timeout
        self.retries = retries
        self._opener = build_opener(_NoRedirect())

    def fetch(self, uid: str, start: date, end: date) -> dict:
        """获取闭区间内原始响应；仅重试暂时性 HTTP 错误和有限次网络失败。"""
        validate_uid(uid)
        validate_dates(start, end)
        body = json.dumps({"uid": uid, "start": start.isoformat(), "end": end.isoformat()}).encode("utf-8")
        for attempt in range(self.retries + 1):
            request = Request(
                self.url,
                data=body,
                headers={"Content-Type": "application/json;charset=UTF-8", "Accept": "application/json"},
                method="POST",
            )
            try:
                with self._opener.open(request, timeout=self.timeout) as response:
                    if response.status != 200:
                        raise ChatRecordsError("官方取数接口未返回 HTTP 200")
                    raw = response.read()
            except HTTPError as exc:
                code = exc.code
                exc.close()
                if code in (408, 429, 500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(min(2**attempt, 4))
                    continue
                error_type = TransientChatRecordsError if code in (408, 429, 500, 502, 503, 504) else ChatRecordsError
                raise error_type(f"官方取数接口 HTTP {code}；未记录响应正文") from None
            except (URLError, TimeoutError, socket.timeout, ConnectionError, OSError, HTTPException):
                if attempt < self.retries:
                    time.sleep(min(2**attempt, 4))
                    continue
                raise TransientChatRecordsError("官方取数接口网络连接失败；请检查内网与服务状态") from None
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeError):
                raise ChatRecordsError("官方取数接口返回了无效 JSON；未记录响应正文") from None
            if not isinstance(payload, dict):
                raise ChatRecordsError("官方取数接口响应顶层必须是对象")
            # 官方样例已实测成功码为整数 0；失败说明可能包含内部信息，不透传。
            if type(payload.get("code")) is not int or payload["code"] != 0:
                raise ChatRecordsError("官方取数接口返回业务失败；未记录响应正文")
            return payload
        raise ChatRecordsError("官方取数接口重试已耗尽")
