"""原文中显式事件与消息引用的词法识别；出现引用不等于业务归属。"""

import re


_UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
EVENT_REFERENCE = re.compile(r"\bevent_id\s*[:=]\s*(" + _UUID + r")(?![\w-])")
MESSAGE_REFERENCE = re.compile(r"\bmessage_id\s*[:=]\s*([a-zA-Z][a-zA-Z0-9_]*:[a-zA-Z0-9_.-]+)")
