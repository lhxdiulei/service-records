"""Keep human review for business content; routine replies never require a decision."""
import re
from .parser import direct_parts,MEDIA
from .db import rows,one,audit
from . import deletions as D

SQL=re.compile(r'\b(select|join|where|insert\s+into|update\s+\w+\s+set|create\s+table|alter\s+table|group\s+by)\b',re.I)
IDENTIFIER=re.compile(r'\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b|\b[A-Za-z]+\.[A-Za-z_]+\b|\b[a-zA-Z]+(?:[A-Z][a-z0-9]+)+\b')
DOMAIN=re.compile(r'债券|存单|存款|可转债|股票|证券|基金|计息|利率|到期日|发行信息|招标|估值|机构性质|企业性质|披露|复权|财报|交易日|发行起始|中英文|市场范围|订单|支付|退款|发票|账单|合同|报表|登录|权限|额度|余额|库存|结算|计费')
OBJECT=re.compile(r'字段|数据|表|接口|口径|代码|参数|价格|计算|发行|到期|机构')
LOGIC=re.compile(r'[？?]|咨询|为啥|为什么|如何|怎么|哪个|哪些|什么|不对|错误|缺失|为空|没有|无法|失败|异常|取值|计算|关联|对应|表示|含义|口径|定义|枚举|规则|区别|不维护|不支持')
REQUEST=re.compile(r'(?:#|需求(?:编?号)?[\s:：]*)(\d{8,})')
STATUS=re.compile(r'稍等|收到|已调整|已修改|已处理|已提需求|需求.*(?:跟进|请查收)|有进展.*回复|(?:后台|生产|规划).*(?:反馈|跟进)|(?:正常|预计).*工作日.*反馈')
ANSWER=re.compile(r'(?:\d+|[一二三四五六七八九十两]+)\s*(?:个)?(?:工作日|天|小时|分钟).*(?:反馈|处理|到账|生效)|(?:取|查询|关联|对应|表示|使用|应为|不是|不维护|不支持).*(?:字段|表|代码|债券|存单|币种|口径)')


def answer_content(message):
    body,_,_=direct_parts(message.get('raw_text',''))
    return bool(ANSWER.search(body))


def business_content(message):
    raw=message.get('raw_text','').strip()
    if not raw or MEDIA.fullmatch(raw):return False
    body,_,_=direct_parts(raw)
    # A quoted business question does not turn "收到/已调整" into a new
    # substantive question. Exact quote matching is handled separately below.
    text=body
    text=re.sub(r'@[^\s@]+','',text)
    if SQL.search(text) or IDENTIFIER.search(text):return True
    if STATUS.search(text) and not LOGIC.search(text):return False
    return bool(DOMAIN.search(text) or OBJECT.search(text) and LOGIC.search(text))


def disposition(reason,message):
    if not business_content(message) and not answer_content(message):return 'ignored','事务性回复或未包含明确业务问题/规则，无需人工确认；原文保留'
    if reason in ('nontext_only','chitchat','system_message'):
        return 'needs_review','模型将明确业务内容判为非业务信息，需人工核对归属'
    return 'needs_review',reason


def compact(text):
    return re.sub(r'\s+','',text or '').strip('"“”「」')


def quote_content(text):
    """Strip the quote wrapper and author, retaining an exact textual anchor."""
    _,quoted,_=direct_parts(text)
    if not quoted:return ''
    quoted=re.sub(r'^.*?引用/回复消息[：:]\s*','',quoted,flags=re.S)
    quoted=quoted.strip().lstrip('"“「')
    quoted=re.sub(r'^[^\r\n：:]{1,120}[：:]\s*','',quoted)
    quoted=re.sub(r'(?:\r?\n)?(?:-{3,}|(?:-\s+){4,}-?)\s*$','',quoted)
    return compact(quoted.rstrip('"”」\r\n '))


def quote_author(raw):
    _,quoted,_=direct_parts(raw)
    quoted=re.sub(r'^.*?引用/回复消息[：:]\s*','',quoted,flags=re.S).strip().lstrip('"“「')
    match=re.match(r'([^\r\n：:]{1,120})[：:]',quoted)
    return match[1].strip() if match else None


def substantive(text):
    return business_content({'raw_text':text}) or answer_content({'raw_text':text})


def suggest_issue(db,customer_id,message):
    raw=message.get('raw_text','');body,_,_=direct_parts(raw)
    quote=quote_content(raw);text=compact(body);requests=set(REQUEST.findall(raw))
    author=quote_author(raw)
    sender=message.get('sender_name_raw')
    if not sender and (mid:=message.get('id') or message.get('message_id')):
        original=one(db,'SELECT sender_name_raw FROM messages WHERE id=%s',(mid,))
        sender=original['sender_name_raw'] if original else None
    reply_id=message.get('quoted_message_id') or message.get('reply_to_message_id')
    if not quote and not requests and not reply_id and not substantive(raw):return None
    candidates=rows(db,'''SELECT im.issue_id,m.id,m.raw_text,m.sender_name_raw,im.relation FROM issue_messages im JOIN messages m ON m.id=im.message_id
        JOIN issues i ON i.id=im.issue_id JOIN tickets t ON t.issue_id=i.id
        WHERE im.active AND i.lifecycle='active' AND i.customer_id=%s AND NOT '''+D.deleted('ticket','t')+' AND NOT '+D.deleted('message','m'),(customer_id,))
    matches=set()
    for anchor in candidates:
        anchor_body,_,_=direct_parts(anchor['raw_text']);anchor_text=compact(anchor_body)
        anchor_quote=quote_content(anchor['raw_text'])
        if reply_id and str(anchor['id'])==str(reply_id):matches.add(str(anchor['issue_id']))
        elif quote and len(anchor_text)>=6 and substantive(anchor_body) and anchor_text==quote and (not author or author==anchor['sender_name_raw']):matches.add(str(anchor['issue_id']))
        # The original question may be ignored while its quoted answer is already
        # assigned. Recover the question through that exact reverse quote edge.
        elif len(text)>=6 and substantive(body) and anchor_quote==text and (not quote_author(anchor['raw_text']) or quote_author(anchor['raw_text'])==sender):matches.add(str(anchor['issue_id']))
        elif requests & set(REQUEST.findall(anchor['raw_text'])):matches.add(str(anchor['issue_id']))
    return next(iter(matches)) if len(matches)==1 else None


def relation(message):
    body,_,_=direct_parts(message.get('raw_text',''))
    if re.search(r'不是|不对|改成|修改下',body):return 'correction'
    if re.search(r'[？?]|(?:能否|有没有|为什么|为啥|怎么|如何)',body):return 'question'
    return 'answer' if substantive(body) else 'progress'


def apply(db,user,customer_id,message,reason):
    from . import services as S
    mid=str(message.get('id') or message['message_id'])
    issue_id=suggest_issue(db,customer_id,message)
    if issue_id:
        S.lock_sources(db,[issue_id],user,[mid])
        issue=S.entity(db,'issues',issue_id,user)
        S.assign_messages(db,user,issue,[dict(message_id=mid,relation=relation(message))],ai=True)
        db.execute("UPDATE message_dispositions SET decision_source='rule',reason='按引用或需求号唯一匹配已有问题，自动关联' WHERE message_id=%s",(mid,))
        return 'assigned','按引用或需求号唯一匹配已有问题，自动关联',issue_id
    state,note=disposition(reason,message)
    return state,note,None


def reassess(db,user,dry_run=False,state='needs_review'):
    from . import services as S
    where,args=S.visibility(user,'m')
    if not dry_run:
        # Match the group-first order used by interactive disposition changes.
        # Read pending work only after locks so a concurrent human choice wins.
        rows(db,'SELECT g.id FROM chat_groups g WHERE '+S.visibility(user,'g')[0]+' ORDER BY g.id FOR UPDATE',S.visibility(user,'g')[1])
    items=rows(db,'''SELECT m.* FROM messages m JOIN message_dispositions d ON d.message_id=m.id
        WHERE '''+where+" AND d.state=%s AND coalesce(d.decision_source,'rule')!='human' AND NOT "+D.deleted('message','m')+' ORDER BY m.group_id,m.sent_at NULLS LAST,m.source_index,m.id',args+(state,))
    report=dict(before=len(items),ignored=0,linked=0,business_review=0,dry_run=dry_run,source_state=state,issue_ids=[])
    for m in items:
        if dry_run:
            issue_id=suggest_issue(db,m['customer_id'],m)
            new_state='assigned' if issue_id else disposition('ambiguous',m)[0]
        else:
            new_state,note,issue_id=apply(db,user,m['customer_id'],m,'业务内容尚未明确归属，需要人工确认')
            if new_state!='assigned' and new_state!=state:db.execute("UPDATE message_dispositions SET state=%s,decision_source='rule',reason=%s,version=version+1,updated_at=now() WHERE message_id=%s",(new_state,note,m['id']))
        if issue_id:report['issue_ids'].append(issue_id)
        report['linked' if new_state=='assigned' else 'ignored' if new_state=='ignored' else 'business_review']+=1
    report['issue_ids']=sorted(set(report['issue_ids']))
    if not dry_run:
        for gid in sorted({str(m['group_id']) for m in items}):S.watermark(db,gid)
        audit(db,user['id'],'business_triage','messages',None,details=report)
    return report
