"""Lossless source parts, token packing, cross-batch retrieval and evidence merge."""
import copy
import json
import math
import re
from uuid import uuid5,NAMESPACE_URL
from .prompting import replace_ids
from . import budget


def unassigned_disposition(reason,message):
    from .triage import disposition
    return disposition(reason,message)


def parts(messages,limit=650,limits=None):
    return [dict(message_id=m['message_id'],start=a,end=b)
            for m in messages for a,b in (budget.split_ranges(m['raw_text'],limit,limits) if m['raw_text'] else [(0,0)])]


def materialize(messages,ranges):
    by_id={m['message_id']:m for m in messages}
    output=[]
    for p in ranges:
        m=budget.fragment(by_id[p.get('source_message_id',p['message_id'])],p['start'],p['end'])
        m['message_id']=p['message_id'];output.append(m)
    return output


def view_range(source,a,b):
    return dict(message_id=str(uuid5(NAMESPACE_URL,f'records-source:{source}:{a}:{b}')),
                source_message_id=source,start=a,end=b)


def view_parts(messages,ranges,limit,limits=None):
    by_id={m['message_id']:m for m in messages};output=[]
    for p in ranges:
        source=p.get('source_message_id',p['message_id'])
        for a,b in budget.split_ranges(by_id[source]['raw_text'][p['start']:p['end']],limit,limits):
            output.append(view_range(source,p['start']+a,p['start']+b))
    return output


def terms(text):
    words=set(re.findall(r'[a-z_][a-z0-9_.]*',text.lower()))
    for run in re.findall(r'[\u4e00-\u9fff]+',text):
        words.update(run[i:i+2] for i in range(len(run)-1))
    return words


def rank_candidates(candidates,messages):
    query=terms('\n'.join(m['raw_text'] for m in messages))
    source_ids={m['message_id'] for m in messages}
    documents=[terms(c['title']+' '+c['summary']) for c in candidates]
    df={t:sum(t in d for d in documents) for t in query}
    def score(index):
        c=candidates[index]
        linked=bool(source_ids.intersection(c.get('support_message_ids',[])))
        lexical=sum(math.log(1+len(candidates)/(1+df[t])) for t in query&documents[index])
        return linked,lexical,-index
    return [candidates[i] for i in sorted(range(len(candidates)),key=score,reverse=True)]


def packet(base,messages,ranges,phase,**processing):
    value=copy.deepcopy(base)
    value['messages']=materialize(messages,ranges)
    present={m['participant_id'] for m in value['messages']}
    value['participants']=[p for p in value['participants'] if p['participant_id'] in present]
    value['processing']=dict(phase=phase,source_ranges=ranges,**processing)
    return value


def topic_packet(base,messages,plan,cursor,candidates,limits,context_ranges=(),max_parts=0):
    by_id={m['message_id']:m for m in messages}
    first=materialize(messages,[plan[cursor]])
    ranked=rank_candidates(candidates,first)[:8]
    end=cursor
    best=None
    while end<len(plan):
        if max_parts and end-cursor>=max_parts:break
        selected=plan[cursor:end+1]
        ids=[p['message_id'] for p in selected]
        if len(set(ids))!=len(ids):break  # two parts of one source need separate calls
        contexts=list({p['message_id']:p for p in context_ranges if p['message_id'] not in ids}.values())[-2:]
        all_ranges=contexts+selected
        value=packet(base,messages,all_ranges,'topic',cursor_start=cursor,cursor_end=end+1)
        value.update(main_message_ids=ids,context_message_ids=[p['message_id'] for p in contexts],candidate_issues=ranked)
        # Reserve output for every possible assignment, rather than filling the
        # input window and then truncating a many-topic JSON response.
        output_fits=150*len(ids)+100<=limits['topic_output']
        measured=budget.measure('topic_assignment',value,limits)
        if not measured['fits'] or not output_fits:
            if best is not None:break
            if contexts:
                context_ranges=();continue
            if ranked:
                ranked=ranked[:-1];continue
            raise ValueError('Single source part exceeds model prompt budget')
        best=value;end+=1
    if best is None:raise ValueError('Cannot pack source part')
    return best


def record_packets(base,messages,ranges,limits,phase='map'):
    index=0
    while index<len(ranges):
        end=index;best=None
        while end<len(ranges):
            chosen=ranges[index:end+1]
            if len({p['message_id'] for p in chosen})!=len(chosen):break
            value=packet(base,messages,chosen,phase,source_parts_complete=False)
            value['allowed_message_ids']=[m['message_id'] for m in value['messages']]
            # Partial evidence has no final QA yet. Keep the usual combined
            # contract so small models can report missing_context/no_answer;
            # input_complete=False still forbids eligible QA candidates.
            value['mode']='both';value['issue']['input_complete']=False
            if not budget.measure('record_extraction',value,limits)['fits']:break
            best=value;end+=1
        if best is None:raise ValueError('Source part cannot fit extraction prompt')
        yield best
        index+=len(best['messages'])


def globalize(result,payload,original_messages):
    """Restore fragment occurrence to the precise full-message occurrence."""
    value=copy.deepcopy(result)
    sources={m['message_id']:m for m in original_messages}
    ranges={p['message_id']:p for p in payload.get('processing',{}).get('source_ranges',[])}
    fragments={m['message_id']:m for m in payload['messages']}
    def visit(node):
        if isinstance(node,dict):
            if 'exact_excerpt' in node:
                mid=node['message_id'];excerpt=node['exact_excerpt'];start=-1
                for _ in range(node['occurrence']):start=fragments[mid]['raw_text'].find(excerpt,start+1)
                if start<0:raise ValueError('Fragment evidence missing')
                source=ranges.get(mid,{}).get('source_message_id',mid)
                target=ranges.get(mid,{}).get('start',0)+start
                raw=sources[source]['raw_text']
                if raw[target:target+len(excerpt)]!=excerpt:raise ValueError('Fragment evidence offset changed')
                node['occurrence']=sum(raw.startswith(excerpt,i) for i in range(target+1))
                node['message_id']=source
            for child in node.values():visit(child)
        elif isinstance(node,list):
            for child in node:visit(child)
    visit(value)
    return replace_ids(value,{mid:p.get('source_message_id',mid) for mid,p in ranges.items()})


def evidence_windows(results,messages,limits=None):
    by_id={m['message_id']:m for m in messages};ranges={}
    def add(mid,a,b):ranges.setdefault(mid,[]).append((a,b))
    def visit(node):
        if isinstance(node,dict):
            if 'exact_excerpt' in node:
                raw=by_id[node['message_id']]['raw_text'];a=-1
                for _ in range(node['occurrence']):a=raw.find(node['exact_excerpt'],a+1)
                if a>=0:add(node['message_id'],a,a+len(node['exact_excerpt']))
            for child in node.values():visit(child)
        elif isinstance(node,list):
            for child in node:visit(child)
    for result in results:visit(result)
    # Preserve a visible question anchor even if a partial map produced no claim.
    for m in messages:
        if m.get('relation')=='question' or '?' in m['raw_text'] or '？' in m['raw_text']:
            a,b=next(budget.split_ranges(m['raw_text'],350,limits));add(m['message_id'],a,b)
    output=[]
    for m in messages:
        merged=[]
        for a,b in sorted(ranges.get(m['message_id'],[])):
            # Retain nearby original wording around a quote, so the reducer
            # sees sentence context rather than isolated words or SQL values.
            raw=m['raw_text'];lo=max(0,a-80);hi=min(len(raw),b+80)
            before=raw.rfind('\n',lo,a);after=raw.find('\n',b,hi)
            a=before+1 if before>=0 else lo
            b=after+1 if after>=0 else hi
            if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
            else:merged.append((a,b))
        # Distinct source views retain exact offsets; noncontiguous quotes are
        # never concatenated into invented source text.
        for a,b in merged:output.append(view_range(m['message_id'],a,b))
    return output


def merge_ticket_claims(final,mapped):
    value=copy.deepcopy(final)
    if value['ticket'] is None:return value
    seen=set();claims=[]
    for result in mapped+[value]:
        if result['ticket'] is None:continue
        for claim in result['ticket']['claims']:
            key=json.dumps([claim['text'],claim['evidence']],sort_keys=True,ensure_ascii=False)
            if key not in seen:
                seen.add(key);claims.append(dict(claim,claim_key='c'+str(len(claims)+1)))
    value['ticket']['claims']=claims
    value['risk_flags']=sorted(set(value['risk_flags'])|{r for result in mapped for r in result['risk_flags'] if r not in ('missing_history','context_truncated')})
    return value
