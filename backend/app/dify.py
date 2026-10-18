"""Dify transport. Model output is always untrusted until semantic validation."""
import json
import os
import time
import httpx
from jsonschema import Draft202012Validator
from . import config
from .db import plain

from .services import locate


class DifyError(Exception):
    def __init__(self,code,message):
        self.code,self.message=code,message
        super().__init__(message)


def profiles():
    return [{'id':p,'configured':bool(os.getenv(f'DIFY_{p.upper()}_TOPIC_KEY') and os.getenv(f'DIFY_{p.upper()}_RECORD_KEY'))} for p in ['local','external']]


def settings(profile,stage):
    if profile not in ('local','external'):raise DifyError('invalid_profile','未知模型配置')
    prefix='DIFY_'+profile.upper()
    url=os.getenv(prefix+'_BASE_URL','').rstrip('/')
    key=os.getenv(prefix+('_TOPIC_KEY' if stage=='topic_assignment' else '_RECORD_KEY'),'')
    if not url or not key:raise DifyError('dify_not_configured','请配置所选模式的两条 Dify 工作流 API Key')
    if profile=='local' and not url.startswith('http://') and not url.startswith('https://'):
        raise DifyError('invalid_endpoint','本地模式需要明确配置内网 Dify 地址')
    return url,key


def validate_schema(name,value):
    schema=json.loads((config.WORKFLOW_DIR/(name+'.schema.json')).read_text(encoding='utf-8'))
    error=next(iter(Draft202012Validator(schema).iter_errors(value)),None)
    if error:raise DifyError('schema_invalid',f'工作流数据结构不匹配：{error.json_path}')


def validate_topic(payload,result):
    validate_schema('topic_assignment.output',result)
    main=set(payload['main_message_ids']);allowed={m['message_id'] for m in payload['messages']}
    existing={i['issue_id'] for i in payload['candidate_issues']};assigned=set();keys=set()
    for item in result['assignments']:
        if item['local_topic_key'] in keys:raise DifyError('duplicate_topic','问题局部编号重复')
        keys.add(item['local_topic_key'])
        ids={m['message_id'] for m in item['message_links']}
        if not ids<=allowed:raise DifyError('message_scope','问题归属引用了输入外消息')
        assigned|=ids&main
        if item['decision']=='new_issue' and (item['existing_issue_id'] is not None or not ids&main):raise DifyError('invalid_topic','只有上下文不能建立新问题')
        if item['decision']=='link_existing' and item['existing_issue_id'] not in existing:raise DifyError('unknown_issue','不能关联候选列表外的问题')
    unassigned={m['message_id'] for m in result['unassigned_messages']}
    if not unassigned<=main or assigned&unassigned or assigned|unassigned!=main:raise DifyError('message_coverage','消息归属结果不完整或互相冲突')


def validate_extraction(payload,result):
    validate_schema('record_extraction.output',result)
    messages={m['message_id']:m for m in payload['messages']};allowed=set(payload['allowed_message_ids'])
    def walk(value):
        if isinstance(value,dict):
            if 'exact_excerpt' in value:
                if value['message_id'] not in allowed:raise DifyError('evidence_scope','证据引用了输入外消息')
                try:locate(messages[value['message_id']]['raw_text'],value['exact_excerpt'],value['occurrence'])
                except Exception:raise DifyError('evidence_missing','模型引用的原文不存在')
            for child in value.values():walk(child)
        elif isinstance(value,list):
            for child in value:walk(child)
    walk(result)
    ticket=result['ticket'];mode=payload['mode']
    if (ticket is None)!=(mode=='qa'):raise DifyError('mode_mismatch','工单输出与模式不符')
    eligible=result['qa_assessment']['eligibility']=='eligible'
    if bool(result['qa_candidates'])!=eligible or (not payload['issue']['input_complete'] and eligible):raise DifyError('qa_incomplete','上下文不完整时不能生成可用 QA')
    if mode=='ticket' and (eligible or result['qa_assessment']['eligibility']!='not_requested'):raise DifyError('mode_mismatch','未请求 QA')
    if ticket:
        fid=ticket['first_visible_message_id'];qid=ticket['first_question_message_id']
        if fid not in allowed or (ticket['date_basis']=='first_question' and qid not in allowed) or (ticket['date_basis']=='first_visible_context' and qid is not None):raise DifyError('date_scope','日期依据不合法')
    related={q['qa_id']:q for q in payload['related_qa']}
    for qa in result['qa_candidates']:
        if qa['action']=='propose_revision':
            old=related.get(qa['existing_qa_id'])
            if not old or old['source_issue_ids']!=[payload['issue']['issue_id']]:raise DifyError('multi_issue_revision','多来源 QA 必须人工修订')
        elif qa['existing_qa_id'] is not None:raise DifyError('qa_target','新 QA 不应带已有 ID')
        for c in qa['contributors']:
            for e in c['evidence']:
                m=messages[e['message_id']];a,b=locate(m['raw_text'],e['exact_excerpt'],e['occurrence'])
                if m['participant_id']!=c['participant_id'] or not any(s['start']<=a and b<=s['end'] for s in m['direct_body_spans']):raise DifyError('contributor_mismatch','贡献者不是直接发言人')


def decode_outputs(outputs):
    if outputs.get('validation_status') not in (None,'valid'):raise DifyError('workflow_invalid','工作流节点校验失败')
    value=outputs.get('result_json')
    if isinstance(value,dict):return value
    if not isinstance(value,str):raise DifyError('workflow_output','工作流必须输出 result_json')
    try:return json.loads(value)
    except (ValueError,TypeError):raise DifyError('workflow_output','result_json 不是合法 JSON')


def run_workflow(profile,stage,payload,on_started,run_id=None,client=None):
    base,key=settings(profile,stage)
    user='service-records:'+payload['scope']['customer_id']
    headers={'Authorization':'Bearer '+key}
    owned=client is None
    client=client or httpx.Client(timeout=httpx.Timeout(45,connect=10),follow_redirects=False)
    deadline=time.monotonic()+600
    def check_revision(data):
        if hasattr(on_started,'check_workflow'):
            if not data.get('workflow_id'):
                raise DifyError('workflow_version_unknown','Dify 未返回工作流版本，无法安全续跑；请核对接口兼容性')
            on_started.check_workflow(str(data['workflow_id']))
    try:
        if run_id:
            # A known remote run is queried, never silently re-executed.
            while time.monotonic()<deadline:
                response=client.get(base+'/workflows/run/'+run_id,headers=headers,params={'user':user})
                response.raise_for_status();data=response.json()
                check_revision(data)
                if data.get('status')=='succeeded':return decode_outputs(data.get('outputs') or {})
                if data.get('status') in ('failed','stopped'):raise DifyError('remote_failed','Dify 已终止此运行，请检查后显式重试')
                time.sleep(2)
            raise DifyError('remote_pending','远端任务仍在运行，可稍后重试查询')
        with client.stream('POST',base+'/workflows/run',headers=headers,json={'inputs':{'payload_json':json.dumps(plain(payload),ensure_ascii=False)},'response_mode':'streaming','user':user}) as response:
            if response.status_code==429:raise DifyError('remote_rate_limit','Dify 限流，请稍后重试')
            response.raise_for_status()
            received=False
            for line in response.iter_lines():
                if time.monotonic()>deadline:raise DifyError('remote_timeout','工作流运行超过10分钟，请查询任务状态')
                if not line.startswith('data:'):continue
                event=json.loads(line[5:].strip());kind=event.get('event');data=event.get('data') or {}
                if kind=='workflow_started':
                    received=True
                    on_started(event.get('workflow_run_id') or data.get('id'),event.get('task_id'))
                    check_revision(data)
                elif kind=='workflow_finished':
                    if data.get('status')!='succeeded':raise DifyError('remote_failed','Dify 工作流失败，请查看 Dify 运行记录')
                    return decode_outputs(data.get('outputs') or {})
                elif kind=='error':raise DifyError('remote_failed','Dify 返回运行错误')
            raise DifyError('remote_disconnected' if received else 'remote_result_unknown','连接中断，结果尚未确认；可查询任务后重试')
    except httpx.HTTPError as exc:
        raise DifyError('remote_transport','无法完成 Dify 请求，请检查地址、密钥和运行记录') from exc
    finally:
        if owned:client.close()
