import copy
import json
import unittest
from uuid import uuid4
from app import budget,pipeline
from app.prompting import model_view,restore_result


def message(raw,mid=None):
    return dict(message_id=mid or str(uuid4()),participant_id='p-real',sent_at='2026-10-15T01:00:00Z',raw_text=raw,
                body_text=raw,quoted_text='',direct_body_spans=[{'start':0,'end':len(raw)}],reply_to_message_id=None,
                has_nontext=False,parse_warnings=[])


def base():
    return dict(schema_version='1.0',participants=[{'participant_id':'p-real','display_name':'甲','role':'customer'}])


class PipelineTests(unittest.TestCase):
    def test_restored_empty_message_keeps_its_identity_in_model_input(self):
        m=message('');limits=budget.policy();plan=pipeline.parts([m],90,limits)
        self.assertEqual(plan,[dict(message_id=m['message_id'],start=0,end=0)])
        packet=pipeline.topic_packet(base(),[m],plan,0,[],limits)
        self.assertEqual(packet['main_message_ids'],[m['message_id']])
        self.assertEqual(packet['messages'][0]['raw_text'],'')

    def test_token_packing_covers_every_source_under_budget(self):
        messages=[message(('请查询 Demo'+str(i)+' 的字段。😀\n')*(i%8+1)) for i in range(50)]
        limits=budget.policy();plan=pipeline.parts(messages,90,limits)
        cursor=0;seen=[];sizes=[]
        while cursor<len(plan):
            p=pipeline.topic_packet(base(),messages,plan,cursor,[],limits,plan[max(0,cursor-2):cursor])
            self.assertTrue(budget.measure('topic_assignment',p,limits)['fits'])
            end=p['processing']['cursor_end'];seen+=plan[cursor:end];sizes.append(end-cursor);cursor=end
        self.assertEqual(seen,plan)
        for m in messages:
            ranges=[p for p in plan if p['message_id']==m['message_id']]
            self.assertEqual(''.join(m['raw_text'][p['start']:p['end']] for p in ranges),m['raw_text'])
        self.assertGreater(len(sizes),1)

    def test_long_unicode_evidence_restores_exact_occurrence(self):
        raw='前文 😀重复\r\n'+'SQL值 e\u0301\n'*180+'😀重复\r\n尾部'
        m=message(raw);a=raw.rfind('😀重复');p=pipeline.view_range(m['message_id'],a,len(raw))
        local=pipeline.packet(base(),[m],[p],'map')
        output={'first_visible_message_id':p['message_id'],'evidence':[{'message_id':p['message_id'],'exact_excerpt':'😀重复','occurrence':1}]}
        restored=pipeline.globalize(output,local,[m])
        self.assertEqual(restored['first_visible_message_id'],m['message_id'])
        self.assertEqual(restored['evidence'][0]['occurrence'],2)
        self.assertEqual(m['raw_text'],raw)

    def test_noncontiguous_windows_never_forge_concatenated_source(self):
        m=message('明确问题？'+'中间资料\n'*1000+'最终答案。')
        result={'evidence':[{'message_id':m['message_id'],'exact_excerpt':s,'occurrence':1} for s in ['明确问题？','最终答案。']]}
        windows=pipeline.evidence_windows([result],[m])
        views=pipeline.materialize([m],windows)
        self.assertGreaterEqual(len(views),2)
        self.assertEqual(len({v['message_id'] for v in views}),len(views))
        for view,p in zip(views,windows):self.assertEqual(view['raw_text'],m['raw_text'][p['start']:p['end']])

    def test_old_issue_retrieval_is_not_limited_to_recent_twenty(self):
        candidates=[dict(issue_id=str(uuid4()),title='登录咨询'+str(i),summary='登录密码',support_message_ids=[]) for i in range(45)]
        candidates.append(dict(issue_id='old-target',title='DemoRecord EndDate 截止日期',summary='表字段说明',support_message_ids=[]))
        ranked=pipeline.rank_candidates(candidates,[message('DemoRecord 的 EndDate 还需要确认')])
        self.assertEqual(ranked[0]['issue_id'],'old-target')

    def test_aliases_preserve_content_and_restore_only_identifier_fields(self):
        m=message('业务字段的值就是 m1，不能替换。');p=base();p['messages']=[m]
        compact=model_view(p)
        self.assertEqual(compact['messages'][0]['raw_text'],m['raw_text'])
        result=restore_result(p,{'message_id':'m1','participant_id':'p1','text':'m1'})
        self.assertEqual(result,{'message_id':m['message_id'],'participant_id':'p-real','text':'m1'})

    def test_other_model_conservative_budget_uses_utf8_bound(self):
        limits=copy.deepcopy(budget.policy());limits['tokenizer_kind']='utf8_upper_bound'
        self.assertEqual(budget.count('中文😀',limits),len('中文😀'.encode()))
        text='中文😀\n'*50
        self.assertEqual(''.join(text[a:b] for a,b in budget.split_ranges(text,32,limits)),text)
