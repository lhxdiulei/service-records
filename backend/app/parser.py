"""Lossless text-body parser. Chat content is untrusted data, never executable."""
import re
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
VERSION = 'wechat-text-1.0'
HEADER = re.compile(r'^\s*"?(?P<stamp>\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}:\d{2})\s*[:：]\s*(?P<sender>[^:\r\n：]{1,120})[:：]')
ALTERNATIVE = re.compile(r'^(?P<sender>[^\r\n]{1,120}?)\s+(?P<stamp>\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}:\d{2})\s*$')
INCOMPLETE_HEADER = re.compile(r'^\s*"?(?P<stamp>\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}:\d{2})\s*[:：]\s*(?P<sender>[^:\r\n：]{1,120})\s*$')
MEDIA = re.compile(r'^(?:\[(?:图片|视频|语音|文件|表情)\]|config/media/\S+)$')


def decode_file(data, encoding='auto'):
    encodings = ['utf-8-sig', 'gb18030', 'utf-16'] if encoding == 'auto' else [encoding]
    for name in encodings:
        try:
            text = data.decode(name)
            if '\x00' in text:
                continue
            return text, name
        except (UnicodeError, LookupError):
            pass
    raise ValueError('无法解码文件，请指定 UTF-8、GB18030 或 UTF-16 编码')


def direct_parts(raw):
    """Unknown quoted fragments are excluded conservatively from attribution."""
    start = 0
    if '这是一条引用/回复消息' in raw or raw.lstrip().startswith('「'):
        separator = re.search(r'(?m)^\s*(?:-{3,}|(?:-\s+){4,}-?)\s*(?:\r?\n|$)', raw)
        if not separator:
            return '', raw, []
        start = separator.end()
    spans = []
    cursor = start
    for line in raw[start:].splitlines(keepends=True):
        end = cursor + len(line)
        if line.strip() and not line.lstrip().startswith('>') and not MEDIA.fullmatch(line.strip()):
            spans.append({'start_cp': cursor, 'end_cp': end})
        cursor = end
    return raw[start:], raw[:start], spans


def parse_text(text):
    lines = text.splitlines(keepends=True)
    entries, cursor, headers = [], 0, []
    for number, line in enumerate(lines, 1):
        match = HEADER.match(line) or ALTERNATIVE.match(line.rstrip('\r\n')) or INCOMPLETE_HEADER.match(line.rstrip('\r\n'))
        if match:
            body_start = cursor + match.end()
            if match.re in (ALTERNATIVE,INCOMPLETE_HEADER):
                body_start = cursor + len(line)
            headers.append((cursor, body_start, number, match))
        cursor += len(line)
    if not headers:
        raise ValueError('没有识别到消息头，支持“2026-07-13 09:00:00:昵称:正文”和“昵称 2026-07-13 09:00:00”格式')
    if text[:headers[0][0]].strip():
        entries.append(dict(sender=None, sent_at=None, timestamp_raw=None, raw_header='',
            raw_text=text[:headers[0][0]], source_body_start=0, source_body_end=headers[0][0],
            source_line_start=1, source_line_end=headers[0][2]-1, kind='malformed',
            direct_body_spans=[], warnings=['消息头之前存在文本，需要人工确认']))
    for index, (offset, start, line_no, match) in enumerate(headers):
        end = headers[index+1][0] if index+1 < len(headers) else len(text)
        raw = text[start:end]
        warnings = []
        malformed = match.re is INCOMPLETE_HEADER
        if malformed:
            warnings.append('消息头缺少正文分隔符，需要人工确认；已保留独立记录')
        try:
            dt = datetime.strptime(match['stamp'].replace('/', '-'), '%Y-%m-%d %H:%M:%S').replace(tzinfo=TZ)
        except ValueError:
            dt = None
            warnings.append('时间格式无效，需要人工更正')
        _, _, spans = direct_parts(raw)
        if text[offset:offset+1] == '"':
            warnings.append('消息头前存在引号，请检查引用边界')
        entries.append(dict(sender=match['sender'].strip(), sent_at=dt.isoformat() if dt else None,
            timestamp_raw=match['stamp'], raw_header=text[offset:start], raw_text=raw,
            source_body_start=start, source_body_end=end, source_line_start=line_no,
            source_line_end=headers[index+1][2]-1 if index+1 < len(headers) else len(lines),
            kind='malformed' if malformed else 'media_placeholder' if MEDIA.fullmatch(raw.strip()) else 'text',
            direct_body_spans=spans, warnings=warnings))
    return entries
