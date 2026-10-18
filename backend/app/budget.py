"""Budget the exact compact Qwen text prompt, including correction headroom."""
import hashlib

import os
from functools import lru_cache
from pathlib import Path
from tokenizers import Tokenizer

from .prompting import model_json

BASE=Path(__file__).resolve().parents[1]
PROMPTS=Path(os.getenv('AI_PROMPT_DIR',str(BASE/'prompts' if (BASE/'prompts').exists() else BASE.parent/'dify')))
TOKENIZER=Path(os.getenv('AI_TOKENIZER_FILE',str(BASE/'tokenizers/qwen3-vl.json')))


@lru_cache(maxsize=4)
def tokenizer(path=str(TOKENIZER)):
    return Tokenizer.from_file(path)


def count(text,limits=None):
    if limits and limits.get('tokenizer_kind')=='utf8_upper_bound':return len(text.encode('utf-8'))
    if limits and limits.get('tokenizer_kind')!='hf_json':raise ValueError('Unsupported tokenizer_kind')
    return len(tokenizer((limits or {}).get('tokenizer_file',str(TOKENIZER))).encode(text,add_special_tokens=False).ids)


@lru_cache(maxsize=2)
def prompts(stage):
    return tuple((PROMPTS/(stage+'_v1.'+kind+'.txt')).read_text(encoding='utf-8').strip() for kind in ('system','user'))


def policy(profile='local'):
    prefix='AI_'+profile.upper()+'_'
    kind=os.getenv(prefix+'TOKENIZER_KIND','hf_json' if profile=='local' else 'utf8_upper_bound')
    path=Path(os.getenv(prefix+'TOKENIZER_FILE',str(TOKENIZER)))
    return dict(context=int(os.getenv(prefix+'CONTEXT_TOKENS',os.getenv('AI_CONTEXT_TOKENS','8192'))),
                model=os.getenv(prefix+'MODEL','qwen3-vl:4b-instruct-q4_K_M' if profile=='local' else 'operator_configured'),
                tokenizer_kind=kind,tokenizer_file=str(path),
                topic_output=int(os.getenv(prefix+'TOPIC_OUTPUT_TOKENS','1800')),record_output=int(os.getenv(prefix+'RECORD_OUTPUT_TOKENS','2600')),
                correction_headroom=512,safety=256,fragment_tokens=650,
                tokenizer_sha256=hashlib.sha256(path.read_bytes()).hexdigest() if kind=='hf_json' else 'utf8-upper-bound-v1',
                prompt_sha256=hashlib.sha256(''.join(sum([list(prompts(s)) for s in ('topic_assignment','record_extraction')],[])).encode()).hexdigest())


def measure(stage,payload,limits=None):
    limits=limits or policy()
    system,user=prompts(stage)
    rendered=user.replace('{{#prepare.compact_payload_json#}}',model_json(payload))
    chat='<|im_start|>system\n'+system+'<|im_end|>\n<|im_start|>user\n'+rendered+'<|im_end|>\n<|im_start|>assistant\n'
    output=limits['topic_output' if stage=='topic_assignment' else 'record_output']
    tokens=count(chat,limits)
    available=limits['context']-output-limits['correction_headroom']-limits['safety']
    return dict(input_tokens=tokens,output_reserve=output,context_limit=limits['context'],input_limit=available,fits=tokens<=available)


def split_ranges(text,max_tokens,limits=None):
    """Exact, disjoint Unicode code-point coverage, including long SQL lines."""
    start=0
    while start<len(text):
        window_end=min(len(text),start+max_tokens*12)
        if count(text[start:window_end],limits)<=max_tokens:
            yield start,window_end;start=window_end;continue
        lo,hi=start+1,window_end
        while lo<hi:
            mid=(lo+hi+1)//2
            if count(text[start:mid],limits)<=max_tokens:lo=mid
            else:hi=mid-1
        end=lo
        # Prefer paragraph/line boundaries, but never discard delimiters.
        boundary=text.rfind('\n',start,end)
        if boundary>=start+(end-start)//2:end=boundary+1
        yield start,end
        start=end


def fragment(message,start,end):
    if start==0 and end==len(message['raw_text']):return dict(message)
    m=dict(message);raw=m['raw_text'][start:end]
    m.update(raw_text=raw,body_text=raw,quoted_text='',direct_body_spans=[
        {'start':max(start,s['start'])-start,'end':min(end,s['end'])-start}
        for s in message['direct_body_spans'] if max(start,s['start'])<min(end,s['end'])])
    m['body_text']=''.join(raw[s['start']:s['end']] for s in m['direct_body_spans'])
    m['quoted_text']=raw[:m['direct_body_spans'][0]['start']] if m['direct_body_spans'] else raw
    return m
