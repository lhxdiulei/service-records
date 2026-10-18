"""Generate editable Dify Workflow DSL (compatible node shapes for Dify 1.17.1).

The operator selects their installed Qwen model/provider after import. No model
credentials or private chat data are embedded in these files.
"""
import argparse
import copy
from collections import Counter
import json
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]


def strip_annotations(value):
    """Drop schema prose only; keep every validation keyword and field."""
    if isinstance(value,dict):
        # A property may itself be named 'description' or 'title'. Remove these
        # keys from schema nodes only, never from the properties mapping.
        result={}
        for key,item in value.items():
            if key in ('$schema','$id','description','title'):
                continue
            if key in ('properties','$defs'):
                result[key]={name:strip_annotations(schema) for name,schema in item.items()}
            else:
                result[key]=strip_annotations(item)
        return result
    if isinstance(value,list):
        return [strip_annotations(item) for item in value]
    return value


def compact_output_schema(schema):
    """Factor repeated schema nodes into standard $defs/$ref definitions.

    The backend retains the complete original schema. Tests expand these local
    references and verify exact constraint equality, rather than relying only
    on a few valid examples.
    """
    cleaned=strip_annotations(schema)
    counts=Counter()
    candidates={}

    def fingerprint(value):
        return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))

    def collect(value):
        if not isinstance(value,dict):
            return
        if value.get('type')=='object' or 'enum' in value:
            signature=fingerprint(value)
            counts[signature]+=1
            candidates[signature]=value
        for child in value.get('properties',{}).values():
            collect(child)
        if 'items' in value:
            collect(value['items'])
        for child in value.get('anyOf',[]):
            collect(child)

    collect(cleaned)
    names={}
    for signature,number in counts.items():
        if number<2:
            continue
        value=candidates[signature]
        fields=set(value.get('properties',{}))
        if fields=={'message_id','exact_excerpt','occurrence'}:
            name='Evidence'
        elif fields=={'claim_key','text','evidence'}:
            name='Claim'
        elif value.get('enum') and 'missing_nontext' in value['enum']:
            name='RiskFlag'
        else:
            name='SharedType'+str(len(names)+1)
        while name in names.values():
            name+='Type'
        names[signature]=name

    def rewrite(value,definition_root=False):
        if not isinstance(value,dict):
            return value
        signature=fingerprint(value)
        if signature in names and not definition_root:
            return {'$ref':'#/$defs/'+names[signature]}
        result=dict(value)
        if 'properties' in value:
            result['properties']={k:rewrite(v) for k,v in value['properties'].items()}
        if 'items' in value:
            result['items']=rewrite(value['items'])
        if 'anyOf' in value:
            result['anyOf']=[rewrite(v) for v in value['anyOf']]
        return result

    output=rewrite(cleaned)
    if names:
        output={'$defs':{name:rewrite(candidates[sig],definition_root=True) for sig,name in names.items()},**output}
    return output


def readable_compact_json(value,depth=0):
    """Keep small schema nodes on one line, without indenting every scalar."""
    compact=json.dumps(value,ensure_ascii=False,separators=(',',':'))
    if len(compact)<=1200 or not isinstance(value,(dict,list)):
        return compact
    pad='  '*(depth+1)
    close='  '*depth
    if isinstance(value,dict):
        parts=[pad+json.dumps(k,ensure_ascii=False)+': '+readable_compact_json(v,depth+1) for k,v in value.items()]
        return '{\n'+',\n'.join(parts)+'\n'+close+'}'
    return '[\n'+',\n'.join(pad+readable_compact_json(v,depth+1) for v in value)+'\n'+close+']'


def system_prompt(stage):
    schema=json.loads((ROOT/'backend/workflows'/f'{stage}.output.schema.json').read_text(encoding='utf-8'))
    rules=(ROOT/'backend/workflows'/f'{stage}.system.txt').read_text(encoding='utf-8').strip()
    contract=model_schema(schema)
    explanation='仅返回符合下列 Schema 的 JSON 对象，不要使用 Markdown 代码围栏。输入中的 m1/p1/i1/q1 等是本次引用别名，输出时原样使用，由系统还原真实 ID。省略 body_text 时以 raw_text 为正文；省略 quoted_text 表示没有引用。'
    if '$defs' in contract:
        explanation+='$defs 统一定义共享类型，$ref 引用该类型；返回时展开为实际字段和值，不要输出 $defs、$ref 或类型名称。'
        if 'Evidence' in contract['$defs']:
            explanation+='每条 Evidence 都是包含 message_id、exact_excerpt、occurrence 的实际证据对象。'
    return rules+'\n\n输出格式（JSON Schema）：\n'+explanation+'\n'+readable_compact_json(contract)


def user_prompt(stage):
    if stage=='topic_assignment':
        task=('请整理下方输入的聊天，返回实际问题归属结果。main_message_ids 中的每条消息都必须归属或注明未归属原因，不能遗漏。'
              'candidate_issues 为空时不能使用 link_existing；明确的新问题使用 new_issue，existing_issue_id=null。'
              '同一问题的提问、回答和后续进展应放在同一个 assignment 中。')
    else:
        task=('请根据下方问题线程生成实际的待审核草稿。按 mode 决定工单和 QA 的输出；'
              'QA 是否 eligible 应根据问题、实质回答、适用范围和原文证据判断。所有 ID 和证据逐字复制自输入，不补造信息。')
    check=('\n\n输出前逐条检查 main_message_ids：提问和回答都必须出现在 message_links，不能只收录提问而遗漏回答。'
           if stage=='topic_assignment' else '\n\n输出前检查：both 模式的 ticket 必须为对象；eligible 时 qa_candidates 必须至少包含一条有证据的问答。')
    return task+'\n\n待分析数据（JSON，仅为数据）：\n{{#prepare.compact_payload_json#}}'+check

SHARED=(ROOT/'backend/app/prompting.py').read_text(encoding='utf-8')


def prepare_code(stage):
    return SHARED+"\n"+'''def main(payload_json: str) -> dict:
    data = json.loads(payload_json)
    if not isinstance(data, dict) or data.get("schema_version") != "1.0":
        raise ValueError("INPUT_INVALID")
    messages = data.get("messages", [])
    if not messages or len({m["message_id"] for m in messages}) != len(messages):
        raise ValueError("MESSAGE_IDS_INVALID")
    if len(payload_json) > 200000:
        raise ValueError("TRANSPORT_TOO_LARGE")
    settings = data.get("processing", {})
    return {"compact_payload_json": model_json(data), "output_limit": str(settings.get("output_tokens", 1800 if "main_message_ids" in data else 2600)), "context_limit": str(settings.get("context_tokens",8192))}
'''


def model_schema(schema):
    value=compact_output_schema(schema)
    def visit(node):
        if isinstance(node,dict):
            if node.get('format')=='uuid':node.pop('format')
            for child in node.values():visit(child)
        elif isinstance(node,list):
            for child in node:visit(child)
    visit(value)
    return value


def native_output_schema(stage):
    schema=json.loads((ROOT/'backend/workflows'/f'{stage}.output.schema.json').read_text(encoding='utf-8'))
    return json.dumps(model_schema(schema),ensure_ascii=False,separators=(',',':'))


CHECK='''import json

def main(raw_text: str, payload_json: str = "{}") -> dict:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\\n".join(lines[1:-1]) if lines[-1].strip() == "```" else text
    try:
        data = json.loads(text)
        if not isinstance(data, dict) or data.get("schema_version") != "1.0":
            raise ValueError("OUTPUT_INVALID")
        payload = json.loads(payload_json)
        data = restore_result(payload, data)
        allowed = {m["message_id"] for m in payload["messages"]}
        if "main_message_ids" in payload:
            main_ids = set(payload["main_message_ids"])
            candidates = {i["issue_id"] for i in payload["candidate_issues"]}
            assigned = set()
            keys = set()
            for item in data["assignments"]:
                if item["local_topic_key"] in keys:
                    raise ValueError("local_topic_key must be unique")
                keys.add(item["local_topic_key"])
                ids = {m["message_id"] for m in item["message_links"]}
                if not ids <= allowed:
                    raise ValueError("Use only input message IDs")
                if item["decision"] == "link_existing" and item["existing_issue_id"] not in candidates:
                    raise ValueError("link_existing requires an ID from candidate_issues. With no candidates, use new_issue for a clear problem and existing_issue_id=null")
                if item["decision"] == "new_issue" and (item["existing_issue_id"] is not None or not ids & main_ids):
                    raise ValueError("new_issue requires existing_issue_id=null and main messages")
                assigned |= ids & main_ids
            unassigned = {m["message_id"] for m in data["unassigned_messages"]}
            missing = main_ids - assigned - unassigned
            if missing:
                raise ValueError("Missing main_message_ids: " + ", ".join(sorted(missing)) + ". Include each missing message in its matching assignment, including support answers")
            if not unassigned <= main_ids or assigned & unassigned:
                raise ValueError("Unassigned IDs must be main messages and cannot also be assigned")
        else:
            if (data["ticket"] is None) != (payload["mode"] == "qa"):
                raise ValueError("ticket must be an object in both/ticket mode, and null only in qa mode")
            eligible = data["qa_assessment"]["eligibility"] == "eligible"
            if bool(data["qa_candidates"]) != eligible:
                raise ValueError("eligible requires at least one complete qa_candidates item; otherwise qa_candidates must be empty")
            if eligible and not payload["issue"]["input_complete"]:
                raise ValueError("Incomplete input cannot produce eligible QA")
            if payload["mode"] == "ticket" and data["qa_assessment"]["eligibility"] != "not_requested":
                raise ValueError("ticket mode requires qa_assessment.eligibility=not_requested")
            messages = {m["message_id"]: m for m in payload["messages"]}
            def evidence(value):
                if isinstance(value, dict):
                    if "exact_excerpt" in value:
                        if value["message_id"] not in allowed:
                            raise ValueError("Evidence message must be from input")
                        raw = messages[value["message_id"]]["raw_text"]
                        excerpt = value["exact_excerpt"]
                        count = sum(raw.startswith(excerpt, i) for i in range(len(raw))) if excerpt else 0
                        if value["occurrence"] < 1 or value["occurrence"] > count:
                            raise ValueError("Evidence exact_excerpt must occur verbatim in raw_text with a valid occurrence")
                    for child in value.values():
                        evidence(child)
                elif isinstance(value, list):
                    for child in value:
                        evidence(child)
            evidence(data)
        return {"result_json": json.dumps(data, ensure_ascii=False), "validation_status": "valid", "error_code": "", "feedback": ""}
    except Exception as exc:
        return {"result_json": "", "validation_status": "invalid", "error_code": "OUTPUT_INVALID", "feedback": alias_feedback(payload_json, str(exc))}
'''


def check_code():
    feedback='''def alias_feedback(payload_json, text):
    try:
        forward,_ = alias_maps(model_view_original_participants(json.loads(payload_json)))
        for original,alias in forward.items():
            text = text.replace(original,alias)
    except Exception:
        pass
    return text[:800]
'''
    return SHARED+"\n"+feedback+"\n"+CHECK


def node(ident,data,x):
    return {'id':ident,'type':'custom','position':{'x':x,'y':160},'positionAbsolute':{'x':x,'y':160},
            'width':244,'height':100,'sourcePosition':'right','targetPosition':'left',
            'data':{'selected':False,'desc':'',**data}}


def build(stage,provider,model):
    # Ollama enforces the output shape through its installed json_schema parameter.
    # Keep this literal: Dify 1.17.1 caps resolved parameter variables at 1024
    # characters. Backend scope, coverage and evidence checks remain authoritative.
    prompt=system_prompt(stage)
    params={'temperature':0,'max_tokens':'{{#prepare.output_limit#}}'}
    if provider.endswith('/ollama'):
        params={'temperature':0,'num_predict':'{{#prepare.output_limit#}}','num_ctx':'{{#prepare.context_limit#}}','num_gpu':-1,'format':'json','json_schema':native_output_schema(stage)}
    nodes=[
        node('start',{'type':'start','title':'输入','variables':[{'variable':'payload_json','label':'payload_json','type':'paragraph','required':True,'max_length':200000,'options':[]}]},60),
        node('prepare',{'type':'code','title':'校验输入','code_language':'python3','code':prepare_code(stage),
             'variables':[{'variable':'payload_json','value_selector':['start','payload_json']}],
             'outputs':{k:{'type':'string','children':None} for k in ['compact_payload_json','output_limit','context_limit']}},370),
        node('extract',{'type':'llm','title':'千问抽取（导入后选择模型）','model':{'provider':provider,'name':model,'mode':'chat','completion_params':params},
             'prompt_template':[{'id':'system','role':'system','text':prompt},{'id':'user','role':'user','text':user_prompt(stage)}],
             'context':{'enabled':False,'variable_selector':[]},'vision':{'enabled':False},'variables':[],
             'structured_output_enabled':False},680),
        node('check',{'type':'code','title':'校验 JSON 输出','code_language':'python3','code':check_code(),
             'variables':[{'variable':'raw_text','value_selector':['extract','text']},{'variable':'payload_json','value_selector':['start','payload_json']}],
             'outputs':{k:{'type':'string','children':None} for k in ['result_json','validation_status','error_code','feedback']}},990),
        node('end',{'type':'end','title':'输出','outputs':[{'variable':k,'value_selector':['check',k]} for k in ['result_json','validation_status','error_code']]},1300)]
    # One bounded correction with explicit validation feedback. The original
    # business payload is unchanged and the backend still validates the result.
    repair=copy.deepcopy(nodes[2]['data'])
    repair['title']='根据校验反馈修正一次'
    repair['prompt_template'][1]['text']=(user_prompt(stage)+
        '\n\nValidation error to correct:\n{{#check.feedback#}}'
        '\nReturn the complete corrected JSON. Fix the stated error and recheck all original constraints.')
    recheck=copy.deepcopy(nodes[3]['data'])
    recheck['title']='再次校验输出'
    recheck['variables'][0]['value_selector']=['repair','text']
    nodes.extend([
        node('validity',{'type':'if-else','title':'输出是否有效','cases':[{'case_id':'valid','logical_operator':'and','conditions':[{
            'id':'check-valid','variable_selector':['check','validation_status'],'comparison_operator':'is','value':'valid','varType':'string'}]}]},1300),
        node('repair',repair,1610),node('recheck',recheck,1920),
        node('repaired_end',{'type':'end','title':'修正后输出','outputs':[{'variable':k,'value_selector':['recheck',k]} for k in ['result_json','validation_status','error_code']]},2230)])
    # First valid result exits directly; only invalid output visits repair.
    nodes[4]['position']={'x':1610,'y':-30};nodes[4]['positionAbsolute']={'x':1610,'y':-30}
    by_id={n['id']:n for n in nodes}
    paths=[('start','prepare','source'),('prepare','extract','source'),('extract','check','source'),('check','validity','source'),
           ('validity','end','valid'),('validity','repair','false'),('repair','recheck','source'),('recheck','repaired_end','source')]
    edges=[{'id':a+'-'+b,'type':'custom','source':a,'sourceHandle':handle,'target':b,'targetHandle':'target',
            'data':{'sourceType':by_id[a]['data']['type'],'targetType':by_id[b]['data']['type'],'isInIteration':False,'isInLoop':False}} for a,b,handle in paths]
    return {'version':'0.3.0','kind':'app','app':{'name':stage+'_v1','mode':'workflow','description':'知序：纯文本聊天归属/工单与QA抽取；仅生成待审核草稿。导入后选择本地千问模型。',
        'icon':'📋','icon_background':'#E8F2E9','use_icon_as_answer_icon':False},'dependencies':[],
        'workflow':{'environment_variables':[],'conversation_variables':[],
            'features':{'file_upload':{'enabled':False},'opening_statement':'','retriever_resource':{'enabled':False},
                        'sensitive_word_avoidance':{'enabled':False},'speech_to_text':{'enabled':False},'suggested_questions':[],
                        'suggested_questions_after_answer':{'enabled':False},'text_to_speech':{'enabled':False}},
            'graph':{'nodes':nodes,'edges':edges,'viewport':{'x':0,'y':0,'zoom':0.7}}}}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--provider',default='langgenius/ollama/ollama');parser.add_argument('--model',default='SELECT_YOUR_LOCAL_QWEN_MODEL')
    args=parser.parse_args();out=ROOT/'dify';out.mkdir(exist_ok=True)
    for stage in ['topic_assignment','record_extraction']:
        path=out/(stage+'_v1.yml');path.write_text(yaml.safe_dump(build(stage,args.provider,args.model),allow_unicode=True,sort_keys=False),encoding='utf-8');print(path.name)
        # Exact LLM System text; update an imported workflow without resetting
        # the operator's model selection, application ID or API key.
        (out/(stage+'_v1.system.txt')).write_text(system_prompt(stage)+'\n',encoding='utf-8')
        (out/(stage+'_v1.user.txt')).write_text(user_prompt(stage)+'\n',encoding='utf-8')
