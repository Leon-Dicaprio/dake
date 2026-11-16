"""将仅有空白差异且唯一可定位的引用还原为实际输入原文。"""

import json


def align_quotes(content, messages):
    """不改写事实或消息编号；跨消息、文字不同和多处匹配保持原输出供校验拒绝。"""
    try:
        value = json.loads(content)
    except (ValueError, TypeError):
        return content
    available = {m.key: m.content for m in messages}

    def walk(item):
        if isinstance(item, dict):
            quote = item.get("quote")
            ids = item.get("evidence_ids", [item.get("message_id")])
            if isinstance(quote, str) and quote.strip() and isinstance(ids, list):
                bodies = [available[key] for key in ids if isinstance(key, str) and key in available]
                if bodies and not any(quote in body for body in bodies):
                    # 用位置映射恢复原文，避免模型复制空格或换行时触发无意义的整批重试。
                    needle = "".join(c for c in quote if not c.isspace())
                    matches = []
                    for body in bodies:
                        positions = [i for i, c in enumerate(body) if not c.isspace()]
                        compact = "".join(body[i] for i in positions)
                        start = compact.find(needle)
                        while start >= 0:
                            matches.append(body[positions[start]:positions[start + len(needle) - 1] + 1])
                            start = compact.find(needle, start + 1)
                    if len(matches) == 1:
                        item["quote"] = matches[0]
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return json.dumps(value, ensure_ascii=False)
