"""Lossless, deliberately conservative filtering before model processing.

Only return a reason for certain noise; never edit a message or its offsets.
An unrecognized value, uncertain parse, or useful adjacent context means keep.
"""
from datetime import datetime, timedelta
import re

from .parser import MEDIA


VERSION = 'conservative-noise-1.0'
REASONS = {
    'empty': '空白消息，未包含正文',
    'media_placeholder': '纯媒体占位，未包含可供模型抽取的文字',
    'isolated_greeting': '独立的纯问候，邻近没有可识别的业务上下文',
    'isolated_thanks': '独立的纯致谢，邻近没有可识别的业务上下文',
    'export_system_notice': '已识别的聊天导出或消息分隔系统通知',
}

# Do not expand this into a classifier based on missing business keywords.
# A short unknown answer ("有维护的", "正常了", "收到") may carry evidence.
_GREETING = re.compile(r'(?:你好|您好|大家好|早上好|早安|晚上好)[!！。．.~～]{0,3}')
_THANKS = re.compile(r'(?:谢谢|谢谢你|谢谢您|多谢|感谢)[!！。．.~～]{0,3}')
_SYSTEM_SENDERS = frozenset({'系统', '系统消息', '系统通知', '导出工具'})
_SYSTEM_NOTICES = frozenset({
    '以上是历史消息', '以下为新消息', '以下是新消息',
    '聊天记录导出完成', '消息记录导出完成',
})
_KINDS = frozenset({'text', 'media_placeholder', 'system', 'system_message'})
_SOCIAL = frozenset({'isolated_greeting', 'isolated_thanks'})
_CONTEXT_WINDOW = timedelta(minutes=30)


def _timestamp(entry):
    value = entry.get('sent_at')
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            pass
    return None


def _uncertain(entry, raw):
    """Warnings and quote/reply structure always win over a noise match."""
    kind = entry.get('kind', 'text')
    if not isinstance(kind, str) or kind not in _KINDS:
        return True
    if kind == 'media_placeholder' and not MEDIA.fullmatch(raw.strip()):
        return True
    if any(entry.get(key) for key in (
        'warnings', 'parse_warnings', 'parse_error', 'parse_errors',
        'quoted_text', 'quoted_message_id', 'reply_to_message_id',
        'reply_to', 'mentions',
    )):
        return True
    if 'sent_at' in entry and _timestamp(entry) is None:
        return True
    if ('@' in raw or '这是一条引用/回复消息' in raw
            or re.search(r'(?m)^\s*[>「“"]', raw)):
        return True
    spans = entry.get('direct_body_spans')
    if 'direct_body_spans' not in entry:
        return False
    if not isinstance(spans, list):
        return True
    cursor = 0
    for span in spans:
        if not isinstance(span, dict):
            return True
        start = span.get('start_cp', span.get('start'))
        end = span.get('end_cp', span.get('end'))
        if (type(start) is not int or type(end) is not int
                or not 0 <= cursor <= start < end <= len(raw)):
            return True
        # An omitted non-whitespace fragment could be quoted context.
        if raw[cursor:start].strip():
            return True
        cursor = end
    return bool(raw[cursor:].strip() and not MEDIA.fullmatch(raw.strip()))


def _candidate(entry):
    if not isinstance(entry, dict):
        return None
    raw = entry.get('raw_text')
    if not isinstance(raw, str) or _uncertain(entry, raw):
        return None
    text = raw.strip()
    if not text:
        return 'empty'
    if MEDIA.fullmatch(text):
        return 'media_placeholder'
    # Exact whole-message matching also preserves multiline text, SQL,
    # questions, corrections, dates, deadlines, emoji and unfamiliar replies.
    if _GREETING.fullmatch(text):
        return 'isolated_greeting'
    if _THANKS.fullmatch(text):
        return 'isolated_thanks'
    sender = entry.get('sender', entry.get('sender_name_raw'))
    if (text in _SYSTEM_NOTICES
            and (isinstance(sender, str) and sender in _SYSTEM_SENDERS
                 or entry.get('kind') in {'system', 'system_message'})):
        return 'export_system_notice'
    return None


def _possibly_related(entries, current, neighbour):
    first, second = entries[min(current, neighbour)], entries[max(current, neighbour)]
    if not isinstance(first, dict) or not isinstance(second, dict):
        return True
    start, end = _timestamp(first), _timestamp(second)
    if start is None or end is None:
        return True
    try:
        distance = end - start
    except TypeError:  # Mixed naive/aware dates are uncertain, not a boundary.
        return True
    return distance < timedelta(0) or distance <= _CONTEXT_WINDOW


def classify(entries):
    """Return one reason code or None (keep) per original entry.

    Pure greetings/thanks are kept if the nearest potentially useful message
    on either side is within 30 minutes. Noise between them is skipped, so
    consecutive greetings do not hide a question or its closing thanks.
    Missing, invalid, or out-of-order times are not evidence of a boundary.
    No content, codepoint offset, or metadata is rewritten.
    """
    entries = list(entries)
    reasons = [_candidate(entry) for entry in entries]
    previous = []
    last = None
    for index, reason in enumerate(reasons):
        previous.append(last)
        if reason is None:
            last = index
    following = [None] * len(entries)
    last = None
    for index in range(len(entries) - 1, -1, -1):
        following[index] = last
        if reasons[index] is None:
            last = index
    return [
        None if reason in _SOCIAL and any(
            neighbour is not None and _possibly_related(entries, index, neighbour)
            for neighbour in (previous[index], following[index])
        ) else reason
        for index, reason in enumerate(reasons)
    ]
