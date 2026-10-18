"""Real PostgreSQL integration tests; creates and drops ONLY its own random database.

Run: python -m unittest discover -s tests -v (from backend, with DB admin URL).
No external model is called. Dify uses a deterministic transport double.
"""
import copy
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit,urlunsplit
import httpx
import psycopg
from psycopg import sql
from fastapi.testclient import TestClient
from app import config,dify
from app.db import connect,one,rows,uid,plain,insert
from app.migrate import migrate
from app.main import app
from app.parser import parse_text,decode_file,direct_parts
from app.services import locate
from app.worker import run_job

QUESTION='示例表 DemoRecord 的截止日期取哪个字段？'
ANSWER='DemoRecord 的 EndDate 表示截止日期。'
TEXT=f'2026-07-13 09:00:00:客户甲:{QUESTION}\n2026-07-14 10:00:00:客服乙:{ANSWER}\n'
ORIGIN='http://localhost:8088'


class ParserTests(unittest.TestCase):
    def test_business_review_excludes_routine_progress_and_quoted_acknowledgements(self):
        from app.triage import business_content,disposition
        for text in ['稍等','收到稍等','@jimmy 已调整','不知道额，下游反馈的','麻烦确认下资讯文件来源','我在跟底层确认有没有维护这个了','有维护的',
            '@山山而川 债券有两个问题后台还没反馈 有进展我会回复',
            '这是一条引用/回复消息：\n"客户：可转债有到期日期这个概念吗？"\n------\n@客户 已调整']:
            with self.subTest(text=text):
                self.assertFalse(business_content({'raw_text':text}))
                self.assertEqual(disposition('ambiguous',{'raw_text':text})[0],'ignored')
        for text in ['可转债有到期日期这个概念吗？','累进利率这样的','发行信息为啥没有这个债啊？',
            'select t.innercode,j.* from secumainall j left join HK_RMFArchives t on j.innercode=t.innercode',
            'Bond_ConBDBasicInfo 的 EndDate 是到期日期','这个接口字段为什么为空？','稍等，EndDate 字段不对']:
            with self.subTest(text=text):
                self.assertTrue(business_content({'raw_text':text}))
                self.assertEqual(disposition('nontext_only',{'raw_text':text})[0],'needs_review')
        self.assertEqual(disposition('nontext_only',{'raw_text':'正常三个工作日内有反馈'})[0],'needs_review')

    def test_multiline_reverse_order_and_lossless_offsets(self):
        raw='2026-07-14 10:00:00:乙:第一行😀\r\nSELECT * FROM Demo;\r\n2026-07-13 09:00:00:甲:提问\r\n'
        records=parse_text(raw)
        self.assertEqual(len(records),2)
        self.assertGreater(records[0]['sent_at'],records[1]['sent_at'])
        for r in records:self.assertEqual(raw[r['source_body_start']:r['source_body_end']],r['raw_text'])
        self.assertIn('SELECT * FROM Demo;',records[0]['raw_text'])

    def test_unicode_and_quoted_attribution(self):
        self.assertEqual(locate('😀e\u0301\r\n哈哈哈','哈哈',2),(6,8))
        raw='这是一条引用/回复消息：\n"客户：原话"\n------\n我的直接回答'
        body,quoted,spans=direct_parts(raw)
        self.assertEqual(body,'我的直接回答');self.assertIn('原话',quoted)
        self.assertEqual(raw[spans[0]['start_cp']:spans[0]['end_cp']],'我的直接回答')
        self.assertEqual(decode_file('中文'.encode('gb18030'))[0],'中文')

    def test_malformed_header_is_isolated(self):
        text='2026-07-13 09:00:00:甲:正常消息\n2026-07-13 10:00:00:乙\n无法确认的正文\n2026-07-13 11:00:00:甲:下一条\n'
        parsed=parse_text(text)
        self.assertEqual(len(parsed),3)
        self.assertEqual(parsed[1]['kind'],'malformed')
        self.assertIn('无法确认',parsed[1]['raw_text'])
        self.assertNotIn('无法确认',parsed[0]['raw_text'])


class SystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_url=config.DATABASE_URL
        cls.original_data=config.DATA_DIR
        cls.database='records_test_'+uid().replace('-','')
        with psycopg.connect(cls.original_url,autocommit=True) as db:
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.database)))
        parts=urlsplit(cls.original_url)
        config.DATABASE_URL=urlunsplit((parts.scheme,parts.netloc,'/'+cls.database,parts.query,parts.fragment))
        cls.temp=tempfile.TemporaryDirectory();config.DATA_DIR=Path(cls.temp.name)
        with patch.dict(os.environ,{'ADMIN_PASSWORD':'test-admin-password-2026'}):migrate()
        from app.security import passwords
        with connect() as db:
            db.execute("INSERT INTO users(id,username,display_name,password_hash,role) VALUES(%s,%s,%s,%s,'agent')",(uid(),'fixture-support','客服乙',passwords.hash('fixture-staff-password')))
        runtime_netloc='records_app:'+os.environ['APP_DB_PASSWORD']+'@'+parts.netloc.rsplit('@',1)[-1]
        config.DATABASE_URL=urlunsplit((parts.scheme,runtime_netloc,'/'+cls.database,parts.query,parts.fragment))

    @classmethod
    def tearDownClass(cls):
        config.DATABASE_URL=cls.original_url;config.DATA_DIR=cls.original_data;cls.temp.cleanup()
        with psycopg.connect(cls.original_url,autocommit=True) as db:
            db.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(cls.database)))

    def setUp(self):
        self.client=TestClient(app);self.login(self.client,'admin','test-admin-password-2026')
        self.customer=self.fixture_customer({'name':'集成测试客户 '+uid()})
        self.group=self.fixture_group({'customer_id':self.customer['id'],'name':'客户服务群'})

    def login(self,client,username,password):
        token=client.get('/api/v1/auth/csrf').json()['csrf_token']
        r=client.post('/api/v1/auth/login',json={'username':username,'password':password},headers={'Origin':ORIGIN,'X-CSRF-Token':token})
        self.assertEqual(r.status_code,200,r.text)
        client.headers.update({'Origin':ORIGIN,'X-CSRF-Token':r.json()['csrf_token']})

    def fixture_customer(self,data):
        with connect() as db:
            return plain(insert(db,'customers',dict(id=uid(),**data)))

    def fixture_group(self,data):
        with connect() as db:
            return plain(insert(db,'chat_groups',dict(id=uid(),**data)))

    def fixture_participants(self,group_id):
        with connect() as db:
            return plain(rows(db,'SELECT * FROM participants WHERE group_id=%s ORDER BY display_name,id',(group_id,)))

    def fixture_scopes(self,user_id,customer_ids):
        # Exercise existing storage isolation and replay guards without a management API.
        with connect() as db:
            db.execute('DELETE FROM user_customer_scopes WHERE user_id=%s',(user_id,))
            for cid in customer_ids:
                insert(db,'user_customer_scopes',dict(user_id=user_id,customer_id=cid,granted_by=user_id))
            db.execute('UPDATE users SET scope_version=scope_version+1 WHERE id=%s',(user_id,))

    def fixture_user(self,data,**kwargs):
        data=dict(data)
        customer_ids=data.pop('customer_ids',None)
        response=self.req('POST','/users',data,**kwargs)
        if response.status_code==201 and customer_ids is not None:
            self.fixture_scopes(response.json()['id'],customer_ids)
        return response

    def req(self,method,path,body=None,version=None,client=None,status=None,key=None,**kwargs):
        headers={'Idempotency-Key':key or uid()}
        if version is not None:headers['If-Match']=f'"{version}"'
        r=(client or self.client).request(method,'/api/v1'+path,json=body,headers=headers,**kwargs)
        if status is None:self.assertLess(r.status_code,300,r.text)
        else:self.assertEqual(r.status_code,status,r.text)
        return r

    def imported(self,text=TEXT):
        r=self.req('POST','/imports',data={'group_id':self.group['id']},files={'file':('chat.txt',text.encode(),'text/plain')}).json()
        b=r['batch'];self.req('POST',f"/imports/{b['id']}/confirm",{'parse_version':b['parse_version'],'accept_warnings':True},b['version'])
        messages=self.req('GET',f"/messages?group_id={self.group['id']}&limit=500").json()['items']
        people=self.fixture_participants(self.group['id'])
        for p in people:
            self.assertEqual(p['role'],'support' if p['display_name']=='客服乙' else 'customer')
            self.assertTrue(p['identity_verified'])
        return b,messages,people

    def issue(self):
        b,msg,people=self.imported()
        result=self.req('POST','/issues',{'group_id':self.group['id'],'title':'字段咨询','messages':[{'message_id':msg[0]['id'],'relation':'question'},{'message_id':msg[1]['id'],'relation':'answer'}]}).json()
        return result,b,msg,people

    def evidence(self,msg,text):return self.req('POST','/evidence-spans',{'message_id':msg['id'],'exact_excerpt':text,'occurrence':1}).json()['id']

    def ticket_draft(self,t,msg):
        q=self.evidence(msg[0],QUESTION);a=self.evidence(msg[1],ANSWER)
        content={'title':'截止日期字段咨询','problem':QUESTION,'impact':'','handling_summary':'客服给出字段解释','current_conclusion':ANSWER,'status':'answered','first_visible_message_id':msg[0]['id'],'first_question_message_id':msg[0]['id'],'date_basis':'first_question','claims':[{'claim_key':'c1','text':ANSWER}],'next_actions':[]}
        body={'expected_object_version':t['version'],'base_revision_id':t['current_revision_id'],'content':content,'evidence':[{'evidence_span_id':eid,'field_key':key,'relation':'supports'} for key,eid in [('problem',q),('current_conclusion',a),('status',a),('claims.c1',a)]]}
        return self.req('POST',f"/tickets/{t['id']}/revisions",body,t['version']).json(),body

    def decision(self,kind,obj,r,action,client=None,**kwargs):
        return self.req('POST',f"/{kind}/{obj['id']}/revisions/{r['id']}/{action}",{'expected_object_version':obj['version'],'expected_current_revision_id':obj['current_revision_id'],'comment':'人工确认' if action!='reject' else '请补充适用范围','accept_incomplete_start':False},r['state_version'],client=client,**kwargs)

    def test_01_auth_csrf_roles_and_scope(self):
        self.assertEqual(TestClient(app).get('/api/v1/tickets').status_code,401)
        r=self.client.post('/api/v1/users',json={'name':'CSRF'},headers={'X-CSRF-Token':'invalid','Idempotency-Key':uid()});self.assertEqual(r.status_code,403)
        username='agent-'+uid()[:8]
        u=self.fixture_user({'username':username,'display_name':'测试客服','password':'agent-password-2026','role':'agent','customer_ids':[]}).json()
        agent=TestClient(app);self.login(agent,username,'agent-password-2026')
        self.req('GET',f"/messages?group_id={self.group['id']}",client=agent,status=403)
        self.req('POST','/users',{'username':'denied','display_name':'禁止创建','password':'denied-password-2026','role':'agent'},client=agent,status=403)

    def test_02_import_duplicate_and_lossless(self):
        b,msg,_=self.imported()
        self.assertEqual(len(msg),2);self.assertEqual(msg[0]['raw_text'],QUESTION+'\n')
        dup=self.req('POST','/imports',data={'group_id':self.group['id']},files={'file':('again.txt',TEXT.encode(),'text/plain')}).json()
        self.assertTrue(dup['duplicate']);self.assertEqual(dup['batch']['id'],b['id'])
        self.assertEqual(self.req('GET',f"/messages?group_id={self.group['id']}").json()['total'],2)
        with connect() as db:
            with self.assertRaises(psycopg.Error):db.execute('UPDATE messages SET raw_text=%s WHERE id=%s',('changed',msg[0]['id']))

    def test_import_prefilter_preview_confirm_restore_and_pagination(self):
        valid=[QUESTION,ANSWER,'正常了','还是不行','不是这个','已调整']
        bodies=['   ']*12+['[图片]']+valid
        text=''.join(f'2026-08-01 09:{i:02}:00:客户甲:{body}\n' for i,body in enumerate(bodies))
        uploaded=self.req('POST','/imports',data={'group_id':self.group['id']},files={'file':('screening.txt',text.encode(),'text/plain')}).json()
        batch=uploaded['batch']
        summary=batch['screening_summary']
        self.assertEqual((summary['total'],summary['retained'],summary['filtered'],summary['restored']),(19,6,13,0))
        self.assertEqual(sum(r['count'] for r in summary['reasons']),13)
        preview=self.req('GET',f"/imports/{batch['id']}/preview?screening=filtered&page=2&page_size=10").json()
        self.assertEqual((preview['total'],len(preview['records'])),(13,3))
        self.assertTrue(all(r['prefilter_filtered'] for r in preview['records']))
        self.assertTrue(all(r['prefilter_reason_label'] for r in preview['records']))
        with patch('app.prefilter.classify',side_effect=AssertionError('Confirmation must use the frozen preview')):
            confirmed=self.req('POST',f"/imports/{batch['id']}/confirm",{'parse_version':batch['parse_version'],'accept_warnings':True},batch['version']).json()
        self.assertEqual(confirmed['screening_summary']['filtered'],13)
        messages=self.req('GET',f"/messages?group_id={self.group['id']}&page_size=100&page=1").json()['items']
        self.assertEqual([m['raw_text'] for m in messages],[b+'\n' for b in bodies])
        self.assertEqual([m['disposition'] for m in messages],['ignored']*13+['pending']*6)
        original=self.req('GET',f"/imports/{batch['id']}/preview?screening=filtered&page=1").json()['records'][0]
        payload={'state':'needs_review','reason':'人工恢复预筛选消息，重新参与归属与抽取'}
        restored=self.req('PUT',f"/messages/{original['message_id']}/disposition",payload,original['disposition_version']).json()
        self.assertIsNotNone(restored['prefilter_restored_at'])
        self.req('PUT',f"/messages/{original['message_id']}/disposition",payload,original['disposition_version'],status=412)
        preview=self.req('GET',f"/imports/{batch['id']}/preview?screening=retained&page=1").json()
        self.assertEqual((preview['screening_summary']['filtered'],preview['screening_summary']['retained'],preview['screening_summary']['restored']),(12,7,1))
        record=next(m for m in preview['records'] if m['message_id']==original['message_id'])
        self.assertTrue(record['prefilter_restored']);self.assertFalse(record['prefilter_filtered'])
        self.assertEqual(record['raw_text'],original['raw_text'])
        listed=self.req('GET',f"/imports?group_id={self.group['id']}&page=1").json()['items'][0]
        self.assertEqual(listed['screening_summary'],preview['screening_summary'])
        duplicate=self.req('POST','/imports',data={'group_id':self.group['id']},files={'file':('same.txt',text.encode(),'text/plain')}).json()
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(duplicate['batch']['screening_summary']['restored'],1)
        unchanged=self.req('GET',f"/imports/{batch['id']}/preview?screening=retained").json()
        self.assertEqual(unchanged['screening_summary']['restored'],1)
        self.req('POST','/messages/reassess?state=needs_review&dry_run=false')
        with connect() as db:
            kept=one(db,'SELECT * FROM message_dispositions WHERE message_id=%s',(original['message_id'],))
            self.assertEqual(kept['state'],'needs_review');self.assertEqual(kept['decision_source'],'human')

    def test_import_prefilter_excludes_before_model_and_restored_message_returns(self):
        text=TEXT+'2026-07-15 09:00:00:客户甲:你好\n2026-07-15 09:01:00:客户甲:[图片]\n'
        batch,messages,_=self.imported(text)
        greeting=next(m for m in messages if m['raw_text'].strip()=='你好')
        question_answer={m['id'] for m in messages if m['raw_text'].strip() in (QUESTION,ANSWER)}
        seen=set()
        def fake(profile,stage,payload,on_started,run_id=None,client=None):
            self.assertEqual(stage,'topic_assignment')
            seen.update(m['message_id'] for m in payload['messages'])
            on_started('prefilter-'+uid(),'task')
            return dict(schema_version='1.0',assignments=[],unassigned_messages=[{'message_id':mid,'reason':'ambiguous','note':'合成验证'} for mid in payload['main_message_ids']])
        env={'DIFY_LOCAL_BASE_URL':'http://test/v1','DIFY_LOCAL_TOPIC_KEY':'topic','DIFY_LOCAL_RECORD_KEY':'record'}
        with patch.dict(os.environ,env),patch('app.dify.run_workflow',side_effect=fake):
            job=self.req('POST',f"/imports/{batch['id']}/extractions",{'profile':'local','mode':'both'}).json()
            self.assertEqual(set(job['input_manifest']['main_message_ids']),question_answer)
            self.req('PUT',f"/messages/{greeting['id']}/disposition",{'state':'needs_review','reason':'人工恢复'},greeting['disposition_version'])
            busy=self.req('POST',f"/imports/{batch['id']}/extractions",{'profile':'local','mode':'both'},status=409)
            self.assertEqual(busy.json()['detail']['code'],'active_job_missing_messages')
            run_job(job['id'])
            self.assertEqual(self.req('GET','/jobs/'+job['id']).json()['state'],'succeeded')
            self.assertEqual(seen,question_answer)
            seen.clear()
            restored_job=self.req('POST',f"/imports/{batch['id']}/extractions",{'profile':'local','mode':'both'}).json()
            run_job(restored_job['id'])
            self.assertIn(greeting['id'],seen)
        preview=self.req('GET',f"/imports/{batch['id']}/preview").json()
        self.assertEqual(preview['screening_summary']['restored'],1)
        self.assertEqual(preview['screening_summary']['filtered'],1)

    def test_import_prefilter_legacy_scope_and_all_noise(self):
        # Existing snapshots are immutable and must not acquire a new classification.
        with patch('app.import_screening.prepare',return_value=None):
            legacy,_,_=self.imported()
        self.assertIsNone(self.req('GET',f"/imports/{legacy['id']}/preview").json()['screening_summary'])
        batch,messages,_=self.imported('2026-08-01 09:00:00:客户甲:[图片]\n')
        noise=next(m for m in messages if m['batch_id']==batch['id'])
        env={'DIFY_LOCAL_BASE_URL':'http://test/v1','DIFY_LOCAL_TOPIC_KEY':'topic','DIFY_LOCAL_RECORD_KEY':'record'}
        with patch.dict(os.environ,env),patch('app.dify.run_workflow') as model:
            rejected=self.req('POST',f"/imports/{batch['id']}/extractions",{'profile':'local','mode':'both'},status=409)
            self.assertEqual(rejected.json()['detail']['code'],'no_pending_messages');model.assert_not_called()
        name='outside-'+uid()
        self.fixture_user({'username':name,'display_name':name,'password':'test-outside-password','role':'agent','customer_ids':[]})
        outsider=TestClient(app);self.login(outsider,name,'test-outside-password')
        self.req('GET',f"/imports/{batch['id']}/preview?screening=filtered",client=outsider,status=403)
        self.req('PUT',f"/messages/{noise['id']}/disposition",{'state':'needs_review','reason':'无权恢复'},noise['disposition_version'],client=outsider,status=403)
        self.req('DELETE',f"/records/message/{noise['id']}",version=noise['delete_version'])
        hidden=self.req('GET',f"/imports/{batch['id']}/preview?screening=filtered").json()['records'][0]
        self.assertTrue(hidden['is_deleted'])
        self.req('PUT',f"/messages/{noise['id']}/disposition",{'state':'needs_review','reason':'必须先恢复删除'},noise['disposition_version'],status=409)

    def test_03_ticket_manual_submit_approve_and_notes(self):
        result,_,msg,_=self.issue();t=result['ticket'];r,_=self.ticket_draft(t,msg)
        self.assertEqual(r['ticket_date'],'2026-07-13')
        r=self.decision('tickets',t,r,'submit').json()
        self.decision('tickets',t,r,'approve')
        detail=self.req('GET','/tickets/'+t['id']).json();self.assertEqual(detail['object']['version'],2)
        self.assertEqual(detail['revisions'][0]['state'],'approved');self.assertGreaterEqual(len(detail['events']),3)
        self.req('POST',f"/tickets/{t['id']}/notes",{'note':'内部回访安排'},2)
        detail=self.req('GET','/tickets/'+t['id']).json();self.assertEqual(detail['object']['version'],2);self.assertEqual(len(detail['notes']),1)
        self.assertEqual(detail['notes'][0]['author_username'],'admin')
        self.assertEqual([a['action'] for a in detail['reviews']],['submit','approve'])
        for action in detail['reviews']:
            self.assertEqual(action['actor_username'],'admin')
            self.assertTrue(action['actor_name'])
            self.assertEqual(action['revision_id'],r['id'])
            self.assertEqual(action['revision_no'],1)
            self.assertNotIn('password_hash',action)
        self.decision('tickets',t,r,'approve',status=412)

    def test_same_file_can_be_imported_into_different_groups(self):
        original,_,_=self.imported()
        other=self.fixture_group({'customer_id':self.customer['id'],'name':'另一个服务群'})
        uploaded=self.req('POST','/imports',data={'group_id':other['id']},files={'file':('same.txt',TEXT.encode(),'text/plain')}).json()
        self.assertFalse(uploaded['duplicate'])
        batch=uploaded['batch']
        self.assertNotEqual(batch['id'],original['id'])
        self.assertNotEqual(batch['storage_key'],original['storage_key'])
        self.req('POST',f"/imports/{batch['id']}/confirm",{'parse_version':batch['parse_version'],'accept_warnings':True},batch['version'])
        for group in (self.group,other):
            self.assertEqual(self.req('GET',f"/messages?group_id={group['id']}").json()['total'],2)

    def test_04_qa_edit_reject_then_publish(self):
        result,_,msg,people=self.issue();qev=self.evidence(msg[0],QUESTION);aev=self.evidence(msg[1],ANSWER)
        support=next(p for p in people if p['display_name']=='客服乙')
        content={'question':QUESTION,'answer':ANSWER,'answer_state':'supported','applicability':'DemoRecord','answer_claims':[{'claim_key':'a1','text':ANSWER}],
                 'contributors':[{'participant_id':support['id'],'contribution':'提供字段说明','evidence_span_ids':[aev]}]}
        ev=[{'field_key':k,'evidence_span_id':e,'relation':'supports'} for k,e in [('question',qev),('answer',aev),('answer_claims.a1',aev)]]
        created=self.req('POST','/qa',{'issue_ids':[result['issue']['id']],'content':content,'evidence':ev}).json();obj,r=created['object'],created['revision']
        r=self.decision('qa',obj,r,'submit').json();r=self.decision('qa',obj,r,'reject').json()
        body={'issue_ids':[result['issue']['id']],'content':content,'evidence':ev,'expected_object_version':1,'base_revision_id':None,'replaces_revision_id':r['id']}
        r=self.req('POST',f"/qa/{obj['id']}/revisions",body,1).json();r=self.decision('qa',obj,r,'submit').json();self.decision('qa',obj,r,'approve')
        detail=self.req('GET','/qa/'+obj['id']).json();self.assertEqual(detail['object']['version'],2);self.assertEqual(detail['revisions'][0]['state'],'approved')
        self.assertEqual(detail['revisions'][1]['state'],'rejected')
        self.assertEqual(detail['revisions'][0]['contributors'][0]['evidence_span_ids'],[aev])
        self.assertEqual([action['revision_no'] for action in detail['reviews']],[1,1,2,2])
        self.assertEqual([action['action'] for action in detail['reviews']],['submit','reject','submit','approve'])
        for action in detail['reviews']:
            self.assertEqual(action['actor_username'],'admin')
            target=next(revision for revision in detail['revisions'] if revision['id']==action['revision_id'])
            self.assertEqual(action['revision_no'],target['revision_no'])

    def test_all_parse_warnings_keep_source_indexes_and_lines_across_preview_filters(self):
        text='前言需确认\n'+''.join(f'"2026-07-13 09:{i:02}:00:客户甲:第{i}条内容\n' for i in range(13))
        batch=self.req('POST','/imports',data={'group_id':self.group['id']},files={'file':('warnings.txt',text.encode(),'text/plain')}).json()['batch']
        preview=self.req('GET',f"/imports/{batch['id']}/preview?page=1&page_size=10").json()
        self.assertEqual(len(preview['warnings']),14)
        self.assertEqual(len(preview['records']),10)
        warning=preview['warnings'][-1]
        self.assertEqual(warning['index'],13)
        self.assertEqual(warning['source_line_start'],14)
        self.assertEqual(warning['source_line_end'],14)
        target=self.req('GET',f"/imports/{batch['id']}/preview?page=2&page_size=10&screening=all").json()
        self.assertEqual([r['source_index'] for r in target['records']],[10,11,12,13])
        self.assertEqual(target['records'][-1]['raw_header']+target['records'][-1]['raw_text'],text.splitlines(keepends=True)[13])
        filtered=self.req('GET',f"/imports/{batch['id']}/preview?page=1&screening=retained").json()
        self.assertEqual(filtered['warnings'],preview['warnings'])

    def test_assigned_message_links_include_all_active_issues_and_skip_removed_or_deleted_destinations(self):
        first,_,messages,_=self.issue()
        second=self.req('POST','/issues',{'title':'另一个字段问题','messages':[{'message_id':messages[0]['id'],'relation':'context'}]}).json()
        def links():
            items=self.req('GET',f"/messages?group_id={self.group['id']}&page=1").json()['items']
            return next(m for m in items if m['id']==messages[0]['id'])['assigned_issues']
        self.assertEqual({link['ticket_id'] for link in links()},{first['ticket']['id'],second['ticket']['id']})
        self.assertEqual({link['label'] for link in links()},{'字段咨询','另一个字段问题'})
        detail=self.req('GET','/issues/'+second['issue']['id']).json()
        self.assertEqual(detail['ticket_id'],second['ticket']['id'])
        self.req('PATCH','/issues/'+second['issue']['id']+'/messages',{'messages':[]},detail['issue']['version'])
        self.assertEqual([link['ticket_id'] for link in links()],[first['ticket']['id']])
        self.req('DELETE','/records/ticket/'+first['ticket']['id'],version=0)
        self.assertEqual(links(),[])

    def test_05_stale_group_and_missing_evidence_rejected(self):
        result,_,msg,_=self.issue();t=result['ticket'];r,body=self.ticket_draft(t,msg)
        body['evidence']=[];empty=self.req('POST',f"/tickets/{t['id']}/revisions",body,1).json()
        self.decision('tickets',t,empty,'submit',status=422)
        r=self.decision('tickets',t,r,'submit').json()
        more=TEXT+'2026-07-15 11:00:00:客服乙:上次说明需要修正\n'
        self.imported(more)
        self.decision('tickets',t,r,'approve',status=409)
        self.req('POST','/evidence-spans',{'message_id':msg[1]['id'],'exact_excerpt':'这是不存在的引用','occurrence':1},status=422)

    def test_06_idempotency_and_version_required(self):
        key=uid();body={'username':'idem-'+uid(),'display_name':'幂等账号','password':'idempotent-password','role':'agent'}
        first=self.req('POST','/users',body,key=key).json()
        second=self.req('POST','/users',body,key=key).json();self.assertEqual(first['id'],second['id'])
        self.req('POST','/users',dict(body,display_name='不同请求'),key=key,status=409)
        self.req('PATCH','/users/'+first['id'],{'username':body['username'],'display_name':'更新姓名','role':'agent'},status=428)

    def test_ticket_record_evidence_can_submit_and_publish_without_duplicate_field_bindings(self):
        result,_,msg,_=self.issue();t=result['ticket'];_,body=self.ticket_draft(t,msg)
        body['evidence']=[e for e in body['evidence'] if e['field_key'].startswith('claims.')]
        r=self.req('POST',f"/tickets/{t['id']}/revisions",body,t['version']).json()
        self.assertTrue(r['problem_text'] and r['current_conclusion'])
        self.assertEqual(r['status'],'answered')
        r=self.decision('tickets',t,r,'submit').json()
        self.assertEqual(r['state'],'in_review')
        self.assertIsNone(self.req('GET','/tickets/'+t['id']).json()['object']['current_revision_id'])
        self.decision('tickets',t,r,'approve')
        detail=self.req('GET','/tickets/'+t['id']).json()
        self.assertEqual(detail['object']['current_revision_id'],r['id'])
        self.assertEqual({e['field_key'] for e in detail['revisions'][0]['evidence']},{'claims.c1'})

    def test_ticket_record_review_keeps_real_evidence_and_each_fact_mandatory(self):
        result,_,msg,_=self.issue();t=result['ticket'];_,body=self.ticket_draft(t,msg)
        for case in ('empty','context_only','unknown_field','missing_fact','contradiction'):
            with self.subTest(case=case):
                draft=copy.deepcopy(body)
                if case=='empty':draft['evidence']=[]
                if case=='context_only':
                    for e in draft['evidence']:e['relation']='context'
                if case=='unknown_field':draft['evidence']=[dict(draft['evidence'][0],field_key='unrelated_field')]
                if case=='missing_fact':draft['evidence']=[e for e in draft['evidence'] if e['field_key']=='problem']
                if case=='contradiction':draft['evidence'][0]['relation']='contradicts'
                r=self.req('POST',f"/tickets/{t['id']}/revisions",draft,t['version']).json()
                error=self.decision('tickets',t,r,'submit',status=422).json()['detail']
                self.assertEqual(error['code'],'conflicting_evidence' if case=='contradiction' else 'evidence_missing')
                self.assertNotIn('claims.c1',error['message'])
                if case=='missing_fact':
                    self.assertIn('关键事实 1',error['message'])
                    self.assertEqual(error['fields'],[{'field_key':'claims.c1','label':'关键事实 1'}])
        draft=copy.deepcopy(body);draft['content']['claims']=[]
        draft['evidence']=[e for e in draft['evidence'] if e['field_key']=='problem']
        r=self.req('POST',f"/tickets/{t['id']}/revisions",draft,t['version']).json()
        self.assertEqual(self.decision('tickets',t,r,'submit').json()['state'],'in_review')

    def test_qa_review_retains_field_fact_and_contributor_evidence_requirements(self):
        result,_,msg,people=self.issue();qev=self.evidence(msg[0],QUESTION);aev=self.evidence(msg[1],ANSWER)
        support=next(p for p in people if p['display_name']=='客服乙')
        content={'question':QUESTION,'answer':ANSWER,'answer_state':'supported','answer_claims':[{'claim_key':'answer_fact','text':ANSWER}],
                 'contributors':[{'participant_id':support['id'],'contribution':'解答','evidence_span_ids':[aev]}]}
        bindings=[{'field_key':key,'evidence_span_id':e,'relation':'supports'} for key,e in [('question',qev),('answer',aev),('answer_claims.answer_fact',aev)]]
        for missing,label in [('question','问题'),('answer','回答'),('answer_claims.answer_fact','关键事实 1'),('contributors','核心贡献者')]:
            with self.subTest(missing=missing):
                candidate=copy.deepcopy(content)
                if missing=='contributors':candidate['contributors']=[]
                created=self.req('POST','/qa',{'issue_ids':[result['issue']['id']],'content':candidate,'evidence':[e for e in bindings if e['field_key']!=missing]}).json()
                error=self.decision('qa',created['object'],created['revision'],'submit',status=422).json()['detail']
                self.assertIn(label,error['message'])
                self.assertNotIn('answer_claims.',error['message'])
                if missing!='contributors':self.assertEqual(error['fields'],[{'field_key':missing,'label':label}])

    def test_07_dify_two_workflows_durable_and_no_auto_approval(self):
        batch,msg,people=self.imported()
        topic=json.loads((config.WORKFLOW_DIR/'example.topic.output.json').read_text(encoding='utf-8'))
        record=json.loads((config.WORKFLOW_DIR/'example.extraction.output.json').read_text(encoding='utf-8'))
        # The workflow contract permits arbitrary local labels; the editor
        # uses ASCII field paths. Both claims and their evidence must map.
        record['ticket']['claims'][0]['claim_key']='字段定义'
        record['qa_candidates'][0]['answer_claims'][0]['claim_key']='字段定义'
        replacements={'40000000-0000-4000-8000-000000000001':msg[0]['id'],'40000000-0000-4000-8000-000000000002':msg[1]['id'],
            '30000000-0000-4000-8000-000000000002':next(p['id'] for p in people if p['display_name']=='客服乙')}
        def fake(profile,stage,payload,on_started,run_id=None,client=None):
            on_started('test-run-'+stage,'test-task')
            raw=json.dumps(topic if stage=='topic_assignment' else record)
            for a,b in replacements.items():raw=raw.replace(a,b)
            return json.loads(raw)
        env={'DIFY_LOCAL_BASE_URL':'http://test-dify/v1','DIFY_LOCAL_TOPIC_KEY':'test-topic','DIFY_LOCAL_RECORD_KEY':'test-record'}
        with patch.dict(os.environ,env),patch('app.dify.run_workflow',side_effect=fake) as calls:
            job=self.req('POST',f"/imports/{batch['id']}/extractions",{'profile':'local','mode':'both'}).json()
            run_job(job['id'])
            # Simulate a broker redelivery / dispatcher recovery after result commit.
            with connect() as db:db.execute("UPDATE extraction_jobs SET state='queued',finished_at=NULL WHERE id=%s",(job['id'],))
            run_job(job['id'])
        result=self.req('GET','/jobs/'+job['id']).json();self.assertEqual(result['state'],'succeeded',result);self.assertEqual(calls.call_count,2)
        ticket=self.req('GET','/tickets').json()[0]['latest_revision']
        qa=self.req('GET','/qa').json()[0]['latest_revision']
        self.assertEqual(ticket['claims'][0]['claim_key'],'c1')
        self.assertIn('claims.c1',{e['field_key'] for e in ticket['evidence']})
        self.assertEqual(qa['answer_claims'][0]['claim_key'],'a1')
        self.assertIn('answer_claims.a1',{e['field_key'] for e in qa['evidence']})
        with connect() as db:
            self.assertEqual(one(db,'SELECT count(*) AS n FROM issues WHERE customer_id=%s',(self.customer['id'],))['n'],1)
            self.assertEqual(one(db,'SELECT count(*) AS n FROM qa_entries WHERE customer_id=%s AND current_revision_id IS NULL',(self.customer['id'],))['n'],1)
            self.assertEqual(one(db,"SELECT count(*) AS n FROM ticket_revisions WHERE customer_id=%s AND state='draft'",(self.customer['id'],))['n'],1)
        # Existing AI output only cites facts/status. It must be reviewable as a
        # whole record without manufacturing extra summary-field citations.
        ticket_object=self.req('GET','/tickets').json()[0]
        self.assertEqual(self.decision('tickets',ticket_object,ticket,'submit').json()['state'],'in_review')

    def test_08_parallel_dashboard_and_duplicate_writes(self):
        _,msg,_=self.imported()
        async def scenario():
            transport=httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,base_url='http://testserver',cookies=dict(self.client.cookies),headers=dict(self.client.headers)) as client:
                # These requests share one event loop, like a real ASGI server.
                responses=await asyncio.wait_for(asyncio.gather(*(client.get('/api/v1'+p) for p in ['/imports','/users','/tickets','/qa','/issues','/jobs','/integrations/dify'])),10)
                self.assertTrue(all(r.status_code==200 for r in responses))
                key=uid()
                results=await asyncio.wait_for(asyncio.gather(*(client.post('/api/v1/issues',json={'title':'并发幂等测试','messages':[{'message_id':msg[0]['id'],'relation':'question'}]},headers={'Idempotency-Key':key}) for _ in range(2))),10)
                self.assertEqual([r.status_code for r in results],[201,201])
                self.assertEqual(results[0].json()['issue']['id'],results[1].json()['issue']['id'])
        asyncio.run(scenario())

    def test_09_reviewer_role_and_competing_approved_versions(self):
        result,_,msg,_=self.issue();t=result['ticket'];r,_=self.ticket_draft(t,msg)
        clients={}
        for role in ['agent','reviewer']:
            username=role+'-'+uid()[:8]
            self.fixture_user({'username':username,'display_name':role,'password':'role-password-2026','role':role,'customer_ids':[self.customer['id']]})
            client=TestClient(app);self.login(client,username,'role-password-2026');clients[role]=client
        r=self.decision('tickets',t,r,'submit',client=clients['agent']).json()
        self.decision('tickets',t,r,'approve',client=clients['agent'],status=403)
        self.decision('tickets',t,r,'approve',client=clients['reviewer'])
        obj=self.req('GET','/tickets/'+t['id']).json()['object']
        candidate1,body=self.ticket_draft(obj,msg)
        candidate2=self.req('POST',f"/tickets/{obj['id']}/revisions",body,obj['version']).json()
        candidate1=self.decision('tickets',obj,candidate1,'submit').json()
        candidate2=self.decision('tickets',obj,candidate2,'submit').json()
        self.decision('tickets',obj,candidate1,'approve')
        self.decision('tickets',obj,candidate2,'approve',status=409)
        detail=self.req('GET','/tickets/'+t['id']).json()
        self.assertEqual(detail['object']['current_revision_id'],candidate1['id'])
        historical=next(x for x in detail['revisions'] if x['id']==r['id'])
        self.assertEqual(historical['state'],'approved')

    def test_10_draft_associations_frozen_and_scope_replay_revoked(self):
        result,_,msg,_=self.issue();t=result['ticket'];r,_=self.ticket_draft(t,msg)
        r=self.decision('tickets',t,r,'submit').json()
        eid=self.evidence(msg[0],QUESTION)
        with connect() as db:
            with self.assertRaises(psycopg.Error):
                db.execute('INSERT INTO revision_evidence(id,customer_id,ticket_revision_id,field_key,evidence_span_id,relation) VALUES(%s,%s,%s,%s,%s,%s)',(uid(),self.customer['id'],r['id'],'title',eid,'supports'))
        username='scope-'+uid()[:8]
        u=self.fixture_user({'username':username,'display_name':'权限测试','password':'scope-password-2026','role':'agent','customer_ids':[self.customer['id']]}).json()
        client=TestClient(app);self.login(client,username,'scope-password-2026')
        key=uid();body={'message_id':msg[0]['id'],'exact_excerpt':QUESTION,'occurrence':1}
        self.req('POST','/evidence-spans',body,client=client,key=key)
        self.fixture_scopes(u['id'],[])
        self.req('POST','/evidence-spans',body,client=client,key=key,status=409)
        self.req('POST','/evidence-spans',body,client=client,status=403)

    def test_11_runtime_role_cannot_disable_guards(self):
        with connect() as db:
            role=one(db,'SELECT current_user AS name')
            self.assertEqual(role['name'],'records_app')
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):db.execute('ALTER TABLE messages DISABLE TRIGGER messages_immutable')
        with connect() as db:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):db.execute('TRUNCATE auth_attempts')

    def test_12_resume_keeps_completed_batches_and_cross_batch_issue(self):
        text=''.join(f'2026-07-13 09:{i:02}:00:客户甲:{QUESTION}\n2026-07-14 10:{i:02}:00:客服乙:{ANSWER}\n' for i in range(10))
        batch,msg,people=self.imported(text)
        topic_calls=0;interrupted=False;first_run=None
        def fake(profile,stage,payload,on_started,run_id=None,client=None):
            nonlocal topic_calls,interrupted,first_run
            if stage=='topic_assignment':
                topic_calls+=1
                if topic_calls==2 and not interrupted:
                    interrupted=True
                    raise dify.DifyError('remote_transport','模拟一次中断')
                run='batch-'+str(topic_calls);on_started(run,'task')
                if first_run is None:first_run=run
                existing=payload['candidate_issues']
                return dict(schema_version='1.0',assignments=[dict(local_topic_key='topic',decision='link_existing' if existing else 'new_issue',
                    existing_issue_id=existing[0]['issue_id'] if existing else None,candidate_title='字段咨询',
                    message_links=[{'message_id':mid,'relation':'question' if next(m for m in payload['messages'] if m['message_id']==mid)['participant_id']==str(people[0]['id']) else 'answer'} for mid in payload['main_message_ids']],
                    decision_note='跨批次同一字段',risk_flags=[])],unassigned_messages=[])
            on_started('record-run','task')
            result=json.loads((config.WORKFLOW_DIR/'example.extraction.output.json').read_text())
            q=next(m for m in payload['messages'] if QUESTION in m['raw_text'])
            a=next(m for m in payload['messages'] if ANSWER in m['raw_text'])
            raw=json.dumps(result)
            for old,new in [('40000000-0000-4000-8000-000000000001',q['message_id']),('40000000-0000-4000-8000-000000000002',a['message_id']),('30000000-0000-4000-8000-000000000002',a['participant_id'])]:raw=raw.replace(old,new)
            return json.loads(raw)
        env={'DIFY_LOCAL_BASE_URL':'http://test/v1','DIFY_LOCAL_TOPIC_KEY':'topic','DIFY_LOCAL_RECORD_KEY':'record'}
        with patch.dict(os.environ,env),patch('app.dify.run_workflow',side_effect=fake):
            job=self.req('POST',f"/imports/{batch['id']}/extractions",{'profile':'local','mode':'both'}).json()
            run_job(job['id'])
            failed=self.req('GET','/jobs/'+job['id']).json()
            self.assertEqual(failed['state'],'partial_failed',failed)
            self.assertEqual(failed['checkpoint']['topic_batches'],1)
            self.req('POST','/jobs/'+job['id']+'/retry',version=failed['version'])
            run_job(job['id'])
        finished=self.req('GET','/jobs/'+job['id']).json()
        self.assertEqual(finished['state'],'succeeded',finished)
        self.assertEqual(finished['checkpoint']['messages_done'],20)
        self.assertEqual(topic_calls,3)
        self.assertEqual(finished['steps'][0]['dify_workflow_run_id'],first_run)
        self.assertEqual(finished['steps'][0]['attempt_count'],1)
        with connect() as db:
            self.assertEqual(one(db,'SELECT count(*) AS n FROM issues WHERE customer_id=%s',(self.customer['id'],))['n'],1)
            self.assertEqual(one(db,'SELECT count(*) AS n FROM issue_messages WHERE customer_id=%s AND active',(self.customer['id'],))['n'],20)

    def test_14_invalid_batches_bisect_and_single_message_keeps_review_state(self):
        text=''.join(f'2026-07-13 09:{i:02}:00:客户甲:字段咨询{i}？\n' for i in range(8))
        batch,messages,_=self.imported(text)
        problem=messages[0]['id'];sizes=[]
        def fake(profile,stage,payload,on_started,run_id=None,client=None):
            if stage=='record_extraction':
                on_started('empty-record','task')
                return dict(schema_version='1.0',ticket=None,qa_candidates=[],qa_assessment={'eligibility':'no_explicit_answer','reason':'暂无回答','unresolved_questions':[]},risk_flags=[])
            mids=payload['main_message_ids'];sizes.append(len(mids));on_started('batch-'+str(len(sizes)),'task')
            if len(mids)>3 or problem in mids:raise dify.DifyError('workflow_invalid','模拟归属校验失败')
            existing=payload['candidate_issues']
            return dict(schema_version='1.0',assignments=[dict(local_topic_key='topic',decision='link_existing' if existing else 'new_issue',
                existing_issue_id=existing[0]['issue_id'] if existing else None,candidate_title='字段咨询',
                message_links=[{'message_id':mid,'relation':'question'} for mid in mids],decision_note='同一主题',risk_flags=[])],unassigned_messages=[])
        env={'DIFY_LOCAL_BASE_URL':'http://test/v1','DIFY_LOCAL_TOPIC_KEY':'topic','DIFY_LOCAL_RECORD_KEY':'record'}
        with patch.dict(os.environ,env),patch('app.dify.run_workflow',side_effect=fake):
            job=self.req('POST',f"/imports/{batch['id']}/extractions",{'profile':'local','mode':'qa'}).json()
            run_job(job['id'])
        finished=self.req('GET','/jobs/'+job['id']).json()
        self.assertEqual(finished['state'],'succeeded',finished)
        self.assertEqual(finished['checkpoint']['messages_done'],8)
        self.assertIn(8,sizes);self.assertIn(1,sizes)
        with connect() as db:
            self.assertEqual(one(db,'SELECT state FROM message_dispositions WHERE message_id=%s',(problem,))['state'],'needs_review')
            self.assertEqual(one(db,'SELECT count(*) AS n FROM issue_messages WHERE customer_id=%s AND active',(self.customer['id'],))['n'],7)
            self.assertEqual(one(db,'SELECT count(*) AS n FROM messages WHERE batch_id=%s',(batch['id'],))['n'],8)

    def test_15_published_workflow_change_cannot_apply_to_existing_checkpoint(self):
        text=''.join(f'2026-07-13 09:{i:02}:00:客户甲:字段咨询{i}？\n' for i in range(15))
        batch,_,_=self.imported(text);calls=0
        def fake(profile,stage,payload,on_started,run_id=None,client=None):
            nonlocal calls
            calls+=1;on_started('run-'+str(calls),'task')
            on_started.check_workflow('published-first' if calls==1 else 'published-new-model')
            return dict(schema_version='1.0',assignments=[dict(local_topic_key='topic',decision='new_issue',existing_issue_id=None,
                candidate_title='字段咨询',message_links=[{'message_id':mid,'relation':'question'} for mid in payload['main_message_ids']],
                decision_note='字段主题',risk_flags=[])],unassigned_messages=[])
        env={'DIFY_LOCAL_BASE_URL':'http://test/v1','DIFY_LOCAL_TOPIC_KEY':'topic','DIFY_LOCAL_RECORD_KEY':'record'}
        with patch.dict(os.environ,env),patch('app.dify.run_workflow',side_effect=fake):
            job=self.req('POST',f"/imports/{batch['id']}/extractions",{'profile':'local','mode':'both'}).json()
            run_job(job['id'])
            changed=self.req('GET','/jobs/'+job['id']).json()
            self.req('POST','/jobs/'+job['id']+'/retry',version=changed['version'])
            run_job(job['id'])
            self.assertEqual(calls,2)
        finished=self.req('GET','/jobs/'+job['id']).json()
        self.assertEqual(finished['error_code'],'workflow_changed',finished)
        self.assertEqual(finished['checkpoint']['topic_batches'],1)
        self.assertEqual(finished['checkpoint']['messages_done'],11)
        self.assertEqual(finished['model_profile_snapshot']['workflow_ids']['topic_assignment'],'published-first')
        with connect() as db:
            self.assertEqual(one(db,'SELECT count(*) AS n FROM issues WHERE customer_id=%s',(self.customer['id'],))['n'],1)
            self.assertEqual(one(db,'SELECT count(*) AS n FROM issue_messages WHERE customer_id=%s AND active',(self.customer['id'],))['n'],11)

    def test_13_long_issue_maps_then_merges_real_source_evidence(self):
        text=f'2026-07-13 09:00:00:客户甲:{QUESTION}\n2026-07-14 10:00:00:客服乙:'+('SELECT 字段 FROM Demo WHERE 编号=12345;\n'*1400)+ANSWER+'\n'
        _,messages,people=self.imported(text)
        p=next(p for p in self.fixture_participants(self.group['id']) if p['display_name']=='客服乙')
        created=self.req('POST','/issues',{'group_id':self.group['id'],'title':'超长 SQL 字段咨询','messages':[{'message_id':m['id'],'relation':'question' if QUESTION in m['raw_text'] else 'answer'} for m in messages]}).json()
        calls=[]
        def fake(profile,stage,payload,on_started,run_id=None,client=None):
            calls.append(payload.get('processing',{}).get('phase','whole'));on_started('long-'+str(len(calls)),'task')
            result=json.loads((config.WORKFLOW_DIR/'example.extraction.output.json').read_text())
            q=next((m for m in payload['messages'] if QUESTION in m['raw_text']),None)
            a=next((m for m in payload['messages'] if ANSWER in m['raw_text']),None)
            first=payload['messages'][0]
            if payload.get('processing',{}).get('phase') in ('map','reduce_map'):
                proof=a or first;excerpt=ANSWER if a else proof['raw_text'][:24]
                result.update(qa_candidates=[],qa_assessment={'eligibility':'missing_context','reason':'分段事实','unresolved_questions':[]})
                t=result['ticket'];t.update(first_visible_message_id=first['message_id'],first_question_message_id=q['message_id'] if q else None,
                    date_basis='first_question' if q else 'first_visible_context',proposed_status='answered' if a else 'in_progress',
                    status_evidence=[],claims=[{'claim_key':'片段事实','text':excerpt,'evidence':[{'message_id':proof['message_id'],'exact_excerpt':excerpt,'occurrence':1}]}],timeline_events=[],next_actions=[])
                return result
            self.assertIsNotNone(q);self.assertIsNotNone(a)
            raw=json.dumps(result)
            for old,new in [('40000000-0000-4000-8000-000000000001',q['message_id']),('40000000-0000-4000-8000-000000000002',a['message_id']),('30000000-0000-4000-8000-000000000002',a['participant_id'])]:raw=raw.replace(old,new)
            return json.loads(raw)
        env={'DIFY_LOCAL_BASE_URL':'http://test/v1','DIFY_LOCAL_TOPIC_KEY':'topic','DIFY_LOCAL_RECORD_KEY':'record'}
        with patch.dict(os.environ,env),patch('app.dify.run_workflow',side_effect=fake):
            job=self.req('POST',f"/issues/{created['issue']['id']}/extractions",{'profile':'local','mode':'both'}).json()
            run_job(job['id'])
        finished=self.req('GET','/jobs/'+job['id']).json()
        self.assertEqual(finished['state'],'succeeded',finished)
        self.assertIn('map',calls);self.assertIn('reduce_final',calls)
        qa=self.req('GET','/qa').json()[0]['latest_revision']
        self.assertTrue(qa['contributors'][0]['identity_verified'])
        source={m['id']:m['raw_text'] for m in messages}
        for evidence in qa['evidence']:
            self.assertEqual(source[evidence['message_id']][evidence['start_cp']:evidence['end_cp']],evidence['excerpt'])
        self.assertEqual(self.req('GET','/tickets/'+created['ticket']['id']).json()['revisions'][0]['ticket_date'],'2026-07-13')


    def test_16_server_pagination_search_counts_and_customer_isolation(self):
        text=''.join(f"2026-07-13 {9+i//60:02d}:{i%60:02d}:00:客户甲:"+('独特分页目标' if i==201 else '字面%_检索' if i==7 else f'分页消息{i}')+'\n' for i in range(202))
        batch,msg,_=self.imported(text)
        def get(path,**params):return self.req('GET',path,params=params).json()
        a=get('/messages',group_id=self.group['id'],page=1)
        b=get('/messages',group_id=self.group['id'],page=2)
        last=get('/messages',group_id=self.group['id'],page=21)
        self.assertEqual((a['total'],a['page_size'],len(a['items']),len(b['items']),len(last['items'])),(202,10,10,10,2))
        self.assertFalse({m['id'] for m in a['items']} & {m['id'] for m in b['items']})
        self.assertEqual(get('/messages',group_id=self.group['id'],page=22)['items'],[])
        for q in ('独特分页目标','%_'):
            found=get('/messages',group_id=self.group['id'],page=1,q=q)
            self.assertEqual(found['total'],1,found)
        for m in msg[:2]:self.req('PUT',f"/messages/{m['id']}/disposition",{'state':'ignored','reason':'分页筛选测试'},m['disposition_version'])
        self.assertEqual(get('/messages',group_id=self.group['id'],page=1,state='ignored')['total'],2)
        self.assertEqual(get('/messages',group_id=self.group['id'],page=1,state='ignored',q='独特分页目标')['total'],0)
        self.assertEqual(len(get(f"/imports/{batch['id']}/preview",page=21)['records']),2)
        created=[]
        for i in range(12):
            created.append(self.req('POST','/issues',{'group_id':self.group['id'],'title':f'分页工单{i}','messages':[{'message_id':msg[i]['id'],'relation':'question'}]}).json())
        from app.services import watermark
        with connect() as db:
            db.execute("UPDATE message_dispositions d SET state='ignored',decision_source='rule',reason='分页测试辅助消息',version=version+1 FROM messages m WHERE m.id=d.message_id AND m.group_id=%s AND d.state='pending'",(self.group['id'],))
            watermark(db,self.group['id'])
        for i,item in enumerate(created):
            t=item['ticket'];m=msg[i];eid=self.evidence(m,m['raw_text'].strip())
            r=self.req('POST',f"/tickets/{t['id']}/revisions",{'expected_object_version':1,'base_revision_id':None,'content':{'title':f'分页工单{i}','problem':m['raw_text'],'first_visible_message_id':m['id'],'first_question_message_id':m['id'],'date_basis':'first_question'},'evidence':[{'evidence_span_id':eid,'field_key':'problem','relation':'supports'}]},1).json()
            self.decision('tickets',t,r,'submit')
            self.req('POST','/qa',{'issue_ids':[item['issue']['id']],'content':{'question':f'分页知识{i}','answer_state':'no_answer'},'evidence':[]})
            if i<11:self.req('POST','/imports',data={'group_id':self.group['id']},files={'file':(f'extra{i}.txt',f'2026-07-14 09:00:00:客户甲:附加导入{i}\n'.encode(),'text/plain')})
        env={'DIFY_LOCAL_BASE_URL':'http://test/v1','DIFY_LOCAL_TOPIC_KEY':'topic','DIFY_LOCAL_RECORD_KEY':'record'}
        with patch.dict(os.environ,env):
            for item in created:self.req('POST',f"/issues/{item['issue']['id']}/extractions",{'profile':'local','mode':'qa'})
        for path,scope in [('/tickets',{'customer_id':self.customer['id']}),('/qa',{'customer_id':self.customer['id']}),('/jobs',{'customer_id':self.customer['id']}),('/reviews',{'customer_id':self.customer['id']}),('/imports',{'group_id':self.group['id']})]:
            first=get(path,page=1,**scope);second=get(path,page=2,**scope)
            self.assertEqual((first['total'],len(first['items']),len(second['items'])),(12,10,2),(path,first))
            self.assertFalse({o['id'] for o in first['items']} & {o['id'] for o in second['items']})
        self.assertEqual(get('/tickets',page=1,customer_id=self.customer['id'],q='分页工单11')['total'],1)
        self.assertEqual(get('/qa',page=1,customer_id=self.customer['id'],q='分页知识11')['total'],1)
        stats=get('/overview',customer_id=self.customer['id'],group_id=self.group['id'])
        self.assertEqual((stats['tickets'],stats['qa'],stats['reviews']),(12,12,12))
        other=self.fixture_customer({'name':'不可见分页客户'})
        username='paging-'+uid()[:8]
        self.fixture_user({'username':username,'display_name':'分页客服','password':'paging-password-2026','role':'agent','customer_ids':[self.customer['id']]})
        agent=TestClient(app);self.login(agent,username,'paging-password-2026')
        for path in ('/tickets','/qa','/jobs','/reviews'):
            hidden=self.req('GET',path,client=agent,params={'page':1,'customer_id':other['id']}).json()
            self.assertEqual(hidden['total'],0)
        self.req('GET','/users?page=1',client=agent,status=403)
        self.req('GET','/tickets?page=0',status=422)
        self.req('GET','/jobs?page=1&page_size=101',status=422)

    def test_17_model_nontext_label_cannot_ignore_real_text(self):
        batch,_,_=self.imported(TEXT+'2026-07-14 11:00:00:客服乙:[图片]\n')
        def fake(profile,stage,payload,on_started,run_id=None,client=None):
            self.assertEqual(stage,'topic_assignment');on_started('mislabel-run','task')
            return dict(schema_version='1.0',assignments=[],unassigned_messages=[{'message_id':mid,'reason':'nontext_only','note':'模拟模型误判'} for mid in payload['main_message_ids']])
        env={'DIFY_LOCAL_BASE_URL':'http://test/v1','DIFY_LOCAL_TOPIC_KEY':'topic','DIFY_LOCAL_RECORD_KEY':'record'}
        with patch.dict(os.environ,env),patch('app.dify.run_workflow',side_effect=fake):
            job=self.req('POST',f"/imports/{batch['id']}/extractions",{'profile':'local','mode':'both'}).json()
            run_job(job['id'])
        data=self.req('GET',f"/messages?group_id={self.group['id']}").json()['items']
        for m in data:
            self.assertEqual(m['disposition'],'ignored' if m['kind']=='media_placeholder' else 'needs_review')
            if m['kind']=='text':
                self.assertEqual(m['disposition_source'],'rule')
                self.assertIn('明确业务内容',m['disposition_reason'])


    def test_18_direct_import_and_accounts_need_no_customer_or_group_setup(self):
        marker='直接导入-'+uid()
        text=f'2026-08-01 09:00:00:客户丁:{marker}字段怎么用？\n2026-08-01 09:01:00:客服丁:{marker}使用 EndDate。\n'
        filename='直接导入-'+uid()+'.txt'
        uploaded=self.req('POST','/imports',files={'file':(filename,text.encode(),'text/plain')}).json()
        batch=uploaded['batch'];self.assertFalse(uploaded['duplicate'])
        again=self.req('POST','/imports',files={'file':('另一个文件名.txt',text.encode(),'text/plain')}).json()
        self.assertTrue(again['duplicate']);self.assertEqual(again['batch']['id'],batch['id'])
        self.req('POST',f"/imports/{batch['id']}/confirm",{'parse_version':batch['parse_version'],'accept_warnings':True},batch['version'])
        found=self.req('GET','/messages?page=1&q='+marker).json()
        self.assertEqual(found['total'],2);self.assertTrue(all(m['source_filename']==filename for m in found['items']))
        issue=self.req('POST','/issues',{'title':marker,'messages':[{'message_id':m['id'],'relation':'question' if i==0 else 'answer'} for i,m in enumerate(found['items'])]}).json()
        self.assertEqual(issue['issue']['primary_group_id'],batch['group_id'])
        username='simple-'+uid()
        account=self.fixture_user({'username':username,'display_name':'客服丁','password':'simple-agent-password','role':'agent'}).json()
        agent=TestClient(app);self.login(agent,username,'simple-agent-password')
        allowed=self.req('GET','/messages?page=1&q='+marker,client=agent).json()
        self.assertEqual(allowed['total'],2)
        self.fixture_user({'username':'no-'+uid(),'display_name':'非法','password':'simple-agent-password','role':'admin'},client=agent,status=403)
        hidden=self.fixture_customer({'name':'独立旧数据范围'})
        hidden_group=self.fixture_group({'customer_id':hidden['id'],'name':'历史来源'})
        self.req('GET',f"/messages?group_id={hidden_group['id']}&page=1",client=agent,status=403)
        self.assertNotEqual(account['role'],'admin')

    def test_19_cross_file_issue_keeps_all_sources_participants_and_review_guards(self):
        result,batch,messages,_=self.issue();issue=result['issue'];ticket=result['ticket']
        second=self.fixture_group({'customer_id':self.customer['id'],'name':'后续文件来源'})
        text='2026-07-15 10:00:00:客服丙:已核实，同一个问题继续使用 EndDate。\n'
        b=self.req('POST','/imports',data={'group_id':second['id']},files={'file':('后续跟进.txt',text.encode(),'text/plain')}).json()['batch']
        self.req('POST',f"/imports/{b['id']}/confirm",{'parse_version':b['parse_version'],'accept_warnings':True},b['version'])
        follow=self.req('GET',f"/messages?group_id={second['id']}").json()['items'][0]
        participant=self.fixture_participants(second['id'])[0]
        account=self.fixture_user({'username':'follow-'+uid(),'display_name':'客服丙','password':'follow-agent-password','role':'agent'}).json()
        participant=self.fixture_participants(second['id'])[0]
        issue=self.req('PATCH',f"/issues/{issue['id']}/messages",{'messages':[{'message_id':m['id'],'relation':'question' if i==0 else 'answer'} for i,m in enumerate(messages)]+[{'message_id':follow['id'],'relation':'progress'}]},issue['version']).json()
        detail=self.req('GET','/tickets/'+ticket['id']).json()
        self.assertEqual(len(detail['source_messages']),3)
        self.assertIn(participant['id'],[p['id'] for p in detail['participants']])
        revision,_=self.ticket_draft(ticket,messages)
        self.assertEqual(set(revision['group_input_versions']),{self.group['id'],second['id']})
        from app.worker import extraction_payload,candidate_pool
        with connect() as db:
            payload=extraction_payload(db,{'id':uid(),'customer_id':self.customer['id'],'mode':'both','input_manifest':{'group_id':self.group['id']}},issue)
            self.assertIn(participant['id'],[p['participant_id'] for p in payload['participants']])
            self.assertIn(issue['id'],[i['issue_id'] for i in candidate_pool(db,second['id'])])
        self.req('PATCH','/users/'+account['id'],{'username':account['username'],'display_name':'后续客服改名','role':'agent'},account['version'])
        updated=self.req('GET','/tickets/'+ticket['id']).json()
        self.assertTrue(updated['revisions'][0]['stale'])
        self.decision('tickets',ticket,revision,'submit',status=409)


    def test_20_csrf_bootstrap_recovers_stale_cookie_without_relaxing_write_checks(self):
        self.client.cookies.set('sr_csrf','stale-csrf-cookie',domain='testserver.local',path='/')
        recovered=self.client.get('/api/v1/auth/csrf').json()['csrf_token']
        self.assertNotEqual(recovered,'stale-csrf-cookie')
        rejected=self.client.post('/api/v1/users',json={'name':'无效写入'},headers={'X-CSRF-Token':'stale-csrf-cookie','Idempotency-Key':uid()})
        self.assertEqual(rejected.status_code,403)
        self.client.headers['X-CSRF-Token']=recovered
        self.fixture_user({'username':'csrf-'+uid(),'display_name':'CSRF恢复账号','password':'csrf-password-2026','role':'agent'})


    def account(self,name=None,role='agent'):
        username='user-'+uid()
        user=self.fixture_user({'username':username,'display_name':name or username,'password':'permission-test-password','role':role,'customer_ids':[self.customer['id']]}).json()
        client=TestClient(app);self.login(client,username,'permission-test-password')
        return user,client

    def test_21_accounts_resolve_chat_roles_and_name_changes_invalidate_old_jobs(self):
        name='客服姓名-'+uid()
        staff,agent=self.account(name)
        text=''.join(f'2026-08-01 09:0{i}:00:{sender}:角色识别消息{i}\n' for i,sender in enumerate((staff['username'],name,'未登记的客服昵称')))
        batch=self.req('POST','/imports',data={'group_id':self.group['id']},files={'file':('roles.txt',text.encode(),'text/plain')}).json()['batch']
        self.req('POST',f"/imports/{batch['id']}/confirm",{'parse_version':batch['parse_version'],'accept_warnings':True},batch['version'])
        people=self.fixture_participants(self.group['id'])
        for p in people:
            expected=p['display_name']!='未登记的客服昵称'
            self.assertEqual(p['role'],'support' if expected else 'customer')
            self.assertEqual(p['linked_user_id'],staff['id'] if expected else None)
        env={'DIFY_LOCAL_BASE_URL':'http://test/v1','DIFY_LOCAL_TOPIC_KEY':'topic','DIFY_LOCAL_RECORD_KEY':'record'}
        update={'username':staff['username'],'display_name':name+'已修改','role':'agent'}
        with patch.dict(os.environ,env):
            job=self.req('POST',f"/imports/{batch['id']}/extractions",{'profile':'local','mode':'both'}).json()
            self.req('PATCH','/users/'+staff['id'],update,staff['version'])
            with patch('app.dify.run_workflow') as model:run_job(job['id']);model.assert_not_called()
        finished=self.req('GET','/jobs/'+job['id']).json();self.assertEqual(finished['error_code'],'identity_changed')
        self.req('POST','/jobs/'+job['id']+'/retry',version=finished['version'],status=409)
        changed=self.fixture_participants(self.group['id'])
        self.assertEqual(next(p for p in changed if p['display_name']==name)['role'],'customer')
        self.req('PATCH','/users/'+staff['id'],dict(update,display_name='客服乙'),staff['version']+1,status=422)
        self.req('PATCH','/users/'+staff['id'],update,staff['version']+1,client=agent,status=403)

    def test_22_only_admin_deletes_chat_imports_and_records_without_destroying_evidence(self):
        result,batch,msg,_=self.issue();ticket=result['ticket'];revision,_=self.ticket_draft(ticket,msg)
        qa=self.req('POST','/qa',{'issue_ids':[result['issue']['id']],'content':{'question':QUESTION,'answer_state':'no_answer'},'evidence':[]}).json()
        _,agent=self.account();_,reviewer=self.account(role='reviewer')
        for kind,item in [('message',msg[0]),('import',batch),('ticket',ticket),('qa',qa['object'])]:
            for client in (agent,reviewer):self.req('DELETE',f"/records/{kind}/{item['id']}",version=0,client=client,status=403)
        deleted=self.req('DELETE','/records/message/'+msg[0]['id'],version=0).json()
        self.assertEqual(self.req('GET',f"/messages?group_id={self.group['id']}").json()['total'],1)
        self.assertEqual(self.req('GET',f"/messages?group_id={self.group['id']}&deleted=true").json()['total'],1)
        self.req('GET','/messages?deleted=true',client=agent,status=403)
        self.req('DELETE','/records/message/'+msg[0]['id'],version=0,status=412)
        self.decision('tickets',ticket,revision,'submit',status=409)
        with connect() as db:
            self.assertEqual(one(db,'SELECT raw_text FROM messages WHERE id=%s',(msg[0]['id'],))['raw_text'],msg[0]['raw_text'])
            self.assertGreater(one(db,'SELECT count(*) AS n FROM evidence_spans WHERE message_id=%s',(msg[0]['id'],))['n'],0)
        self.req('POST','/records/message/'+msg[0]['id']+'/restore',version=deleted['delete_version'])
        gone=self.req('DELETE','/records/import/'+batch['id'],version=0).json()
        self.assertEqual(self.req('GET',f"/messages?group_id={self.group['id']}").json()['total'],0)
        self.req('POST','/records/import/'+batch['id']+'/restore',version=gone['delete_version'])
        self.assertEqual(self.req('GET',f"/messages?group_id={self.group['id']}").json()['total'],2)
        for kind,item in [('ticket',ticket),('qa',qa['object'])]:
            gone=self.req('DELETE',f"/records/{kind}/{item['id']}",version=0).json()
            path='/tickets' if kind=='ticket' else '/qa'
            self.assertEqual(self.req('GET',path,params={'page':1,'customer_id':self.customer['id']}).json()['total'],0)
            self.assertEqual(self.req('GET',path,params={'page':1,'customer_id':self.customer['id'],'deleted':True}).json()['total'],1)
            self.req('POST',f"/records/{kind}/{item['id']}/restore",version=gone['delete_version'])
        self.assertEqual(self.req('GET','/overview',params={'customer_id':self.customer['id']}).json()['tickets'],1)

    def test_23_only_owner_or_admin_deletes_drafts_and_official_version_survives(self):
        result,_,msg,_=self.issue();ticket=result['ticket'];initial,body=self.ticket_draft(ticket,msg)
        owner,client=self.account();_,stranger=self.account()
        body['replaces_revision_id']=initial['id']
        own=self.req('POST',f"/tickets/{ticket['id']}/revisions",body,1,client=client).json()
        self.assertEqual(own['created_by'],owner['id'])
        self.req('DELETE','/records/ticket_draft/'+own['id'],version=0,client=stranger,status=403)
        gone=self.req('DELETE','/records/ticket_draft/'+own['id'],version=0,client=client).json()
        self.req('POST','/records/ticket_draft/'+own['id']+'/restore',version=gone['delete_version'],client=client)
        current=self.req('GET','/tickets/'+ticket['id']).json()['object']
        body.update(expected_object_version=current['version'],replaces_revision_id=own['id'])
        own=self.req('POST',f"/tickets/{ticket['id']}/revisions",body,current['version'],client=client).json()
        own=self.decision('tickets',current,own,'submit',client=client).json()
        self.req('DELETE','/records/ticket_draft/'+own['id'],version=0,client=stranger,status=403)
        withdrawn=self.req('DELETE','/records/ticket_draft/'+own['id'],version=0,client=client).json()
        self.assertEqual(self.req('GET','/reviews',params={'customer_id':self.customer['id']}).json()['total'],0)
        self.req('POST','/records/ticket_draft/'+own['id']+'/restore',version=withdrawn['delete_version'],client=client)
        current=self.req('GET','/tickets/'+ticket['id']).json()['object']
        body.update(expected_object_version=current['version'],replaces_revision_id=own['id'])
        own=self.req('POST',f"/tickets/{ticket['id']}/revisions",body,current['version'],client=client).json()
        own=self.decision('tickets',current,own,'submit',client=client).json()
        self.decision('tickets',current,own,'approve')
        current=self.req('GET','/tickets/'+ticket['id']).json()['object']
        body.update(expected_object_version=current['version'],base_revision_id=current['current_revision_id'],replaces_revision_id=None)
        draft=self.req('POST',f"/tickets/{ticket['id']}/revisions",body,current['version'],client=client).json()
        self.req('DELETE','/records/ticket_draft/'+draft['id'],version=0,client=client)
        detail=self.req('GET','/tickets/'+ticket['id']).json()
        self.assertEqual(detail['object']['current_revision_id'],own['id'])
        self.assertNotIn(draft['id'],[r['id'] for r in detail['revisions']])
        self.req('DELETE','/records/ticket_draft/'+own['id'],version=2,status=409)

    def test_24_ai_repeat_requests_reuse_objects_versions_and_link_task_results(self):
        batch,msg,people=self.imported();owner,client=self.account()
        topic=json.loads((config.WORKFLOW_DIR/'example.topic.output.json').read_text())
        record=json.loads((config.WORKFLOW_DIR/'example.extraction.output.json').read_text())
        replacements={'40000000-0000-4000-8000-000000000001':msg[0]['id'],'40000000-0000-4000-8000-000000000002':msg[1]['id'],
            '30000000-0000-4000-8000-000000000002':next(p['id'] for p in people if p['display_name']=='客服乙')}
        def fake(profile,stage,payload,on_started,run_id=None,client=None):
            on_started('dedupe-'+uid(),'task')
            raw=json.dumps(topic if stage=='topic_assignment' else record)
            for a,b in replacements.items():raw=raw.replace(a,b)
            return json.loads(raw)
        env={'DIFY_LOCAL_BASE_URL':'http://test/v1','DIFY_LOCAL_TOPIC_KEY':'topic','DIFY_LOCAL_RECORD_KEY':'record'}
        with patch.dict(os.environ,env),patch('app.dify.run_workflow',side_effect=fake):
            job=self.req('POST',f"/imports/{batch['id']}/extractions",{'profile':'local','mode':'both'},client=client).json()
            same=self.req('POST',f"/imports/{batch['id']}/extractions",{'profile':'local','mode':'both'},client=client).json()
            self.assertEqual(job['id'],same['id']);self.assertTrue(same['reused_request'])
            run_job(job['id']);finished=self.req('GET','/jobs/'+job['id']).json();self.assertEqual(finished['state'],'succeeded',finished)
            first=self.req('GET','/jobs/'+job['id']+'/records').json();self.assertEqual(first['total'],2)
            self.assertTrue(all(r['created_by']==owner['id'] for r in first['items']))
            issue=finished['result_issue_ids'][0]
            second=self.req('POST',f'/issues/{issue}/extractions',{'profile':'local','mode':'both'},client=client).json()
            run_job(second['id'])
            repeated=self.req('GET','/jobs/'+second['id']+'/records').json()
            self.assertEqual(repeated['total'],2);self.assertTrue(all(r['action']=='reused' for r in repeated['items']),repeated)
            with connect() as db:
                self.assertEqual(one(db,'SELECT count(*) AS n FROM tickets WHERE customer_id=%s',(self.customer['id'],))['n'],1)
                self.assertEqual(one(db,'SELECT count(*) AS n FROM qa_entries WHERE customer_id=%s',(self.customer['id'],))['n'],1)
                self.assertEqual(one(db,'SELECT count(*) AS n FROM qa_revisions WHERE customer_id=%s',(self.customer['id'],))['n'],1)
                db.execute('DELETE FROM extraction_job_records WHERE job_id=%s',(job['id'],))
            self.assertEqual(self.req('GET','/jobs/'+job['id']+'/records').json()['total'],2)
            record['qa_candidates'][0]['question']='示例表 DemoRecord 截止日期字段是什么？'
            third=self.req('POST',f'/issues/{issue}/extractions',{'profile':'local','mode':'both'},client=client).json()
            run_job(third['id'])
            updated=self.req('GET','/jobs/'+third['id']+'/records').json()
            self.assertEqual(next(r for r in updated['items'] if r['record_kind']=='qa')['action'],'updated')
            with connect() as db:self.assertEqual(one(db,'SELECT count(*) AS n FROM qa_entries WHERE customer_id=%s',(self.customer['id'],))['n'],1)
            from app.ai_records import revision_content
            qa_item=self.req('GET','/qa',params={'page':1,'customer_id':self.customer['id']}).json()['items'][0]
            content=revision_content('qa',qa_item['latest_revision']);content['applicability']='人工维护的适用条件'
            human=self.req('POST',f"/qa/{qa_item['id']}/revisions",{'issue_ids':[issue],'content':plain(content),
                'evidence':[{k:e[k] for k in ('field_key','evidence_span_id','relation')} for e in qa_item['latest_revision']['evidence']],
                'expected_object_version':qa_item['version'],'base_revision_id':None,'replaces_revision_id':qa_item['latest_revision']['id']},qa_item['version']).json()
            fourth=self.req('POST',f'/issues/{issue}/extractions',{'profile':'local','mode':'both'},client=client).json();run_job(fourth['id'])
            protected=self.req('GET','/jobs/'+fourth['id']+'/records').json()
            protected_qa=next(r for r in protected['items'] if r['record_kind']=='qa')
            self.assertEqual((protected_qa['action'],protected_qa['revision_id']),('manual_review_required',human['id']))


    def test_25_overlapping_file_question_reuses_existing_issue_even_if_model_says_new(self):
        original,_,_,_=self.issue()
        group=self.fixture_group({'customer_id':self.customer['id'],'name':'重叠导出文件'})
        batch=self.req('POST','/imports',data={'group_id':group['id']},files={'file':('overlap.txt',TEXT.encode(),'text/plain')}).json()['batch']
        self.req('POST',f"/imports/{batch['id']}/confirm",{'parse_version':batch['parse_version'],'accept_warnings':True},batch['version'])
        def fake(profile,stage,payload,on_started,run_id=None,client=None):
            on_started('overlap-'+uid(),'task')
            if stage=='topic_assignment':
                return dict(schema_version='1.0',assignments=[dict(local_topic_key='new',decision='new_issue',existing_issue_id=None,candidate_title=QUESTION,
                    message_links=[dict(message_id=m['message_id'],relation='question' if QUESTION in m['raw_text'] else 'answer') for m in payload['messages'] if m['message_id'] in payload['main_message_ids']],decision_note='模拟重复新建',risk_flags=[])],unassigned_messages=[])
            result=json.loads((config.WORKFLOW_DIR/'example.extraction.output.json').read_text())
            question=next(m for m in payload['messages'] if QUESTION in m['raw_text']);answer=next(m for m in payload['messages'] if ANSWER in m['raw_text'])
            raw=json.dumps(result)
            for a,b in [('40000000-0000-4000-8000-000000000001',question['message_id']),('40000000-0000-4000-8000-000000000002',answer['message_id']),('30000000-0000-4000-8000-000000000002',answer['participant_id'])]:raw=raw.replace(a,b)
            return json.loads(raw)
        env={'DIFY_LOCAL_BASE_URL':'http://test/v1','DIFY_LOCAL_TOPIC_KEY':'topic','DIFY_LOCAL_RECORD_KEY':'record'}
        with patch.dict(os.environ,env),patch('app.dify.run_workflow',side_effect=fake):
            job=self.req('POST',f"/imports/{batch['id']}/extractions",{'profile':'local','mode':'both'}).json();run_job(job['id'])
        finished=self.req('GET','/jobs/'+job['id']).json();self.assertEqual(finished['state'],'succeeded',finished)
        self.assertEqual(finished['result_issue_ids'],[original['issue']['id']])
        self.assertEqual(self.req('GET','/tickets',params={'page':1,'customer_id':self.customer['id']}).json()['total'],1)

    def test_26_qa_owner_draft_deletion_hides_empty_record_and_restores_it(self):
        result,_,_,_=self.issue();owner,client=self.account();_,other=self.account()
        created=self.req('POST','/qa',{'issue_ids':[result['issue']['id']],'content':{'question':'自己的 QA 草稿','answer_state':'no_answer'},'evidence':[]},client=client).json()
        revision=created['revision'];self.assertEqual(revision['created_by'],owner['id'])
        self.req('DELETE','/records/qa_draft/'+revision['id'],version=0,client=other,status=403)
        gone=self.req('DELETE','/records/qa_draft/'+revision['id'],version=0,client=client).json()
        self.assertEqual(self.req('GET','/qa',params={'page':1,'customer_id':self.customer['id']}).json()['total'],0)
        self.assertEqual(self.req('GET','/qa',params={'page':1,'customer_id':self.customer['id'],'deleted':True}).json()['total'],1)
        self.req('POST','/records/qa_draft/'+revision['id']+'/restore',version=gone['delete_version'],client=client)
        self.assertEqual(self.req('GET','/qa',params={'page':1,'customer_id':self.customer['id']}).json()['total'],1)

    def test_27_deleted_message_stops_frozen_task_before_any_model_call(self):
        batch,msg,_=self.imported()
        env={'DIFY_LOCAL_BASE_URL':'http://test/v1','DIFY_LOCAL_TOPIC_KEY':'topic','DIFY_LOCAL_RECORD_KEY':'record'}
        with patch.dict(os.environ,env):
            job=self.req('POST',f"/imports/{batch['id']}/extractions",{'profile':'local','mode':'both'}).json()
            self.req('DELETE','/records/message/'+msg[0]['id'],version=0)
            with patch('app.dify.run_workflow') as model:run_job(job['id']);model.assert_not_called()
        self.assertEqual(self.req('GET','/jobs/'+job['id']).json()['error_code'],'source_changed')

    def test_28_uncertain_model_output_reviews_business_content_only(self):
        text='2026-08-01 10:00:00:客户甲:稍等\n2026-08-01 10:01:00:客服乙:已调整\n2026-08-01 10:02:00:客户甲:接口字段 EndDate 为什么为空？\n'
        batch,_,_=self.imported(text)
        def fake(profile,stage,payload,on_started,run_id=None,client=None):
            self.assertEqual(stage,'topic_assignment');on_started('triage-'+uid(),'task')
            return dict(schema_version='1.0',assignments=[dict(local_topic_key='t'+str(i),decision='needs_review',existing_issue_id=None,
                candidate_title='不确定',message_links=[dict(message_id=mid,relation='context')],decision_note='缺少上下文',risk_flags=['missing_history'])
                for i,mid in enumerate(payload['main_message_ids'])],unassigned_messages=[])
        env={'DIFY_LOCAL_BASE_URL':'http://test/v1','DIFY_LOCAL_TOPIC_KEY':'topic','DIFY_LOCAL_RECORD_KEY':'record'}
        with patch.dict(os.environ,env),patch('app.dify.run_workflow',side_effect=fake):
            job=self.req('POST',f"/imports/{batch['id']}/extractions",{'profile':'local','mode':'both'}).json();run_job(job['id'])
        finished=self.req('GET','/jobs/'+job['id']).json();self.assertEqual(finished['state'],'succeeded',finished)
        messages=self.req('GET',f"/messages?group_id={self.group['id']}").json()['items']
        self.assertEqual([m['disposition'] for m in messages],['ignored','ignored','needs_review'])

    def test_29_historical_reassessment_links_quotes_keeps_business_and_human_choices(self):
        original,_,_,_=self.issue()
        text=('2026-08-01 10:00:00:客服乙:稍等\n'
            f'2026-08-01 10:01:00:客服乙:这是一条引用/回复消息：\n"客户甲：{QUESTION}"\n------\n@客户甲 已调整\n'
            '2026-08-01 10:02:00:客户甲:证券发行信息为什么缺失？\n'
            '2026-08-01 10:03:00:客户甲:收到\n')
        batch,messages,_=self.imported(text)
        targets=[m for m in messages if m['batch_id']==batch['id']]
        with connect() as db:
            db.execute("UPDATE message_dispositions SET state='needs_review',decision_source='model_validated',reason='模拟历史误判' WHERE message_id=ANY(%s::uuid[])",([m['id'] for m in targets],))
            db.execute("UPDATE message_dispositions SET decision_source='human',decided_by=(SELECT id FROM users WHERE username='admin'),reason='人工明确保留' WHERE message_id=%s",(targets[-1]['id'],))
        _,agent=self.account();self.req('POST','/messages/reassess?dry_run=false',client=agent,status=403)
        report=self.req('POST','/messages/reassess').json();self.assertTrue(report['dry_run']);self.assertGreaterEqual(report['linked'],1)
        self.assertTrue(all(m['disposition']=='needs_review' for m in self.req('GET',f"/messages?group_id={self.group['id']}").json()['items'] if m['batch_id']==batch['id']))
        self.req('POST','/messages/reassess?dry_run=false')
        updated=[m for m in self.req('GET',f"/messages?group_id={self.group['id']}").json()['items'] if m['batch_id']==batch['id']]
        self.assertEqual([m['disposition'] for m in updated],['ignored','assigned','needs_review','needs_review'])
        self.assertEqual([m['raw_text'] for m in updated],[m['raw_text'] for m in targets])
        self.assertEqual(updated[-1]['disposition_reason'],'人工明确保留')
        with connect() as db:
            link=one(db,'SELECT issue_id,relation FROM issue_messages WHERE message_id=%s AND active',(targets[1]['id'],))
            self.assertEqual(str(link['issue_id']),original['issue']['id']);self.assertEqual(link['relation'],'progress')
        self.req('POST','/messages/reassess?dry_run=false')
        self.assertEqual([m['disposition'] for m in self.req('GET',f"/messages?group_id={self.group['id']}").json()['items'] if m['batch_id']==batch['id']],['ignored','assigned','needs_review','needs_review'])


    def test_30_ignored_recovery_matches_reverse_quote_and_preserves_author_and_human_choice(self):
        text=(f'2026-08-01 10:00:00:客户甲:{QUESTION}\n'
            f'2026-08-01 10:01:00:客服乙:这是一条引用/回复消息：\n"客户甲：{QUESTION}"\n------\n{ANSWER}\n'
            f'2026-08-01 10:02:00:客户丙:{QUESTION}\n'
            '2026-08-01 10:03:00:客户甲:稍等\n')
        _,messages,_=self.imported(text)
        result=self.req('POST','/issues',{'title':'引用中的日期字段问题','messages':[{'message_id':messages[1]['id'],'relation':'answer'}]}).json()
        with connect() as db:
            from app.ai_records import existing_issue
            recovered=existing_issue(db,self.customer['id'],[{'message_id':messages[0]['id'],'relation':'question'}])
            self.assertEqual(str(recovered['id']),result['issue']['id'])
            db.execute("UPDATE message_dispositions SET state='ignored',decision_source='model_validated',reason='nontext_only' WHERE message_id=ANY(%s::uuid[])",([messages[i]['id'] for i in (0,2,3)],))
            db.execute("UPDATE message_dispositions SET decision_source='human',decided_by=(SELECT id FROM users WHERE username='admin'),reason='人工忽略' WHERE message_id=%s",(messages[3]['id'],))
        dry=self.req('POST','/messages/reassess?state=ignored').json();self.assertGreaterEqual(dry['linked'],1)
        self.req('POST','/messages/reassess?state=ignored&dry_run=false')
        found=self.req('GET',f"/messages?group_id={self.group['id']}").json()['items']
        self.assertEqual([m['disposition'] for m in found],['assigned','assigned','needs_review','ignored'])
        self.assertEqual(found[-1]['disposition_reason'],'人工忽略')
        with connect() as db:
            link=one(db,'SELECT issue_id,relation FROM issue_messages WHERE message_id=%s AND active',(messages[0]['id'],))
            self.assertEqual(str(link['issue_id']),result['issue']['id']);self.assertEqual(link['relation'],'question')
        self.req('POST','/messages/reassess?state=assigned',status=422)

    def test_31_unanswered_human_qa_does_not_break_extraction_and_question_proof_dedupes(self):
        result,_,messages,_=self.issue();issue=result['issue']
        evidence=self.evidence(messages[0],QUESTION)
        created=self.req('POST','/qa',{'issue_ids':[issue['id']],'content':{'question':QUESTION,'answer_state':'no_answer'},
            'evidence':[{'evidence_span_id':evidence,'field_key':'question','relation':'supports'}]}).json()
        env={'DIFY_LOCAL_BASE_URL':'http://test/v1','DIFY_LOCAL_TOPIC_KEY':'topic','DIFY_LOCAL_RECORD_KEY':'record'}
        with patch.dict(os.environ,env):
            job=self.req('POST',f"/issues/{issue['id']}/extractions",{'profile':'local','mode':'ticket'}).json()
        from app import worker as W,ai_records as A
        with connect() as db:
            payload=W.extraction_payload(db,job,issue)
            self.assertEqual(payload['related_qa'],[])
            dify.validate_schema('record_extraction.input',payload)
            matched=A.find_qa(db,issue['id'],'换个说法问截止日期',[{'evidence_span_id':evidence,'field_key':'question','relation':'supports'}])
            self.assertEqual(str(matched['id']),created['object']['id'])

    def test_32_file_library_search_and_message_scope(self):
        marker='分文件-'+uid()[:8]
        filename=marker+'%_同名.txt'
        def upload_file(name,text,group=None,confirm=True):
            batch=self.req('POST','/imports',data={'group_id':(group or self.group)['id']},
                files={'file':(name,text.encode(),'text/plain')}).json()['batch']
            if confirm:self.req('POST',f"/imports/{batch['id']}/confirm",{'parse_version':batch['parse_version'],'accept_warnings':True},batch['version'])
            return batch
        first=upload_file(filename,''.join(f'2026-07-13 09:{i:02d}:00:客户甲:共有关键词 '+('文件一独特目标' if i==11 else str(i))+'\n' for i in range(12)))
        second=upload_file(filename,'2026-07-14 09:00:00:客户甲:共有关键词 文件二专有内容\n')
        pending=upload_file(marker+'-待确认.txt','2026-07-15 09:00:00:客户甲:待确认内容\n',confirm=False)
        def get(path,**params):return self.req('GET',path,params=params).json()
        a=get('/messages',batch_id=first['id'],page=1)
        b=get('/messages',batch_id=first['id'],page=2)
        self.assertEqual((a['total'],len(a['items']),len(b['items'])),(12,10,2))
        self.assertFalse({m['id'] for m in a['items']} & {m['id'] for m in b['items']})
        self.assertTrue(all(m['batch_id']==first['id'] for m in a['items']+b['items']))
        self.assertEqual(get('/messages',batch_id=second['id'],page=1,q='共有关键词')['total'],1)
        self.assertEqual(get('/messages',batch_id=second['id'],page=1,q='文件一独特目标')['total'],0)
        self.assertEqual(get('/messages',batch_id=pending['id'],page=1)['total'],0)
        ignored=a['items'][0]
        self.req('PUT',f"/messages/{ignored['id']}/disposition",{'state':'ignored','reason':'分文件筛选测试'},ignored['disposition_version'])
        self.assertEqual(get('/messages',batch_id=first['id'],page=1,state='ignored',q='共有关键词')['total'],1)
        self.assertEqual(get('/messages',batch_id=first['id'],page=1,state='pending',q='文件一独特目标')['total'],1)
        removed=a['items'][1]
        self.req('DELETE',f"/records/message/{removed['id']}",version=removed['delete_version'])
        detail=get('/imports/'+first['id'])
        self.assertEqual(detail['message_counts'],dict(active=11,deleted=1,pending=10,needs_review=0,assigned=0,ignored=1))
        same=get('/imports',group_id=self.group['id'],page=1,q='%_')
        self.assertEqual(same['total'],2)
        self.assertEqual({f['id'] for f in same['items']},{first['id'],second['id']})
        self.assertEqual(get('/imports',group_id=self.group['id'],page=1,q=marker,status='confirmed')['total'],2)
        self.assertEqual(get('/imports',group_id=self.group['id'],page=1,q=marker,status='pending')['total'],1)
        for i in range(9):upload_file(marker+f'-额外{i}.txt',f'2026-07-16 09:00:00:客户甲:额外文件{i}\n',confirm=False)
        files_a=get('/imports',group_id=self.group['id'],page=1,q=marker)
        files_b=get('/imports',group_id=self.group['id'],page=2,q=marker)
        self.assertEqual((files_a['total'],len(files_a['items']),len(files_b['items'])),(12,10,2))
        self.assertFalse({f['id'] for f in files_a['items']} & {f['id'] for f in files_b['items']})
        hidden_customer=self.fixture_customer({'name':'分文件权限范围'})
        hidden_group=self.fixture_group({'customer_id':hidden_customer['id'],'name':'隐藏来源'})
        hidden=upload_file(marker+'-无权限.txt','2026-07-17 09:00:00:客户甲:无权限消息\n',hidden_group)
        username='files-'+uid()[:8]
        self.fixture_user({'username':username,'display_name':'文件查询客服','password':'file-query-password','role':'agent','customer_ids':[self.customer['id']]})
        agent=TestClient(app);self.login(agent,username,'file-query-password')
        allowed=self.req('GET','/imports',client=agent,params={'page':1,'q':marker}).json()
        self.assertEqual(allowed['total'],12)
        self.assertNotIn(hidden['id'],{f['id'] for f in allowed['items']})
        self.req('GET','/imports/'+hidden['id'],client=agent,status=403)
        self.req('GET','/messages',client=agent,params={'batch_id':hidden['id'],'page':1},status=403)
        self.req('GET','/imports/'+uid(),status=404)
        self.req('GET','/messages',params={'batch_id':uid(),'page':1},status=404)
        self.req('GET','/messages?batch_id=invalid',status=422)
        self.req('DELETE','/records/import/'+first['id'],version=detail['delete_version'])
        deleted=get('/imports/'+first['id'])
        self.assertEqual((deleted['message_counts']['active'],deleted['message_counts']['deleted']),(0,12))
        self.assertEqual(get('/messages',batch_id=first['id'],page=1,deleted=True)['total'],12)
        self.assertEqual(get('/messages',batch_id=second['id'],page=1)['total'],1)
        self.req('GET','/imports/'+first['id'],client=agent,status=403)
        self.req('GET','/messages',client=agent,params={'batch_id':first['id'],'page':1},status=403)
        self.req('GET','/imports?deleted=true&page=1',client=agent,status=403)


    def test_file_review_counts_follow_manual_processing_and_exclude_deleted_messages(self):
        batch,messages,_=self.imported(TEXT+'2026-07-14 11:00:00:客户甲:另一个接口的日期字段为何为空？\n')
        other,_,_=self.imported(TEXT.replace('DemoRecord','AnotherRecord'))
        def count(batch_id=batch['id']):
            return self.req('GET','/imports/'+batch_id).json()['message_counts']
        def mark(message,state):
            fresh=self.req('GET','/messages',params={'batch_id':message['batch_id'],'page':1}).json()['items']
            current=next(m for m in fresh if m['id']==message['id'])
            self.req('PUT',f"/messages/{message['id']}/disposition",{'state':state,'reason':'核对当前文件待人工归属统计'},current['disposition_version'])
        self.assertEqual(count()['needs_review'],0)
        self.assertEqual(count()['pending'],3)
        for message in messages[:2]:mark(message,'needs_review')
        other_message=self.req('GET','/messages',params={'batch_id':other['id'],'page':1}).json()['items'][0]
        mark(other_message,'needs_review')
        self.assertEqual((count()['needs_review'],count(other['id'])['needs_review']),(2,1))
        files=self.req('GET','/imports',params={'page':1,'group_id':self.group['id']}).json()['items']
        self.assertEqual(next(f for f in files if f['id']==batch['id'])['message_counts']['needs_review'],2)
        mark(messages[0],'ignored')
        self.assertEqual((count()['needs_review'],count()['pending']),(1,2))
        self.req('POST','/issues',{'title':'人工确认日期字段问题','messages':[{'message_id':messages[1]['id'],'relation':'answer'}]})
        self.assertEqual((count()['needs_review'],count()['pending'],count()['assigned']),(0,1,1))
        mark(messages[2],'needs_review')
        self.assertEqual(count()['needs_review'],1)
        message=self.req('GET','/messages',params={'batch_id':batch['id'],'state':'needs_review','page':1}).json()['items'][0]
        deleted=self.req('DELETE',f"/records/message/{message['id']}",version=message['delete_version']).json()
        self.assertEqual((count()['needs_review'],count()['deleted']),(0,1))
        self.req('POST',f"/records/message/{message['id']}/restore",version=deleted['delete_version'])
        self.assertEqual(count()['needs_review'],1)
        mark(messages[2],'ignored')
        self.assertEqual(count()['needs_review'],0)
        self.assertEqual(count(other['id'])['needs_review'],1)

    def test_admin_users_search_pagination_and_public_details(self):
        marker='accounts-'+uid()[:8]
        created=[]
        for i in range(12):
            created.append(self.fixture_user({'username':marker+f'-{i:02d}','display_name':marker+f'姓名{i}%_',
                'password':'account-list-password','role':'reviewer' if i%2 else 'agent'}).json())
        first=self.req('GET','/users',params={'page':1,'q':marker}).json()
        second=self.req('GET','/users',params={'page':2,'q':marker}).json()
        self.assertEqual((first['total'],len(first['items']),len(second['items'])),(12,10,2))
        self.assertFalse({u['id'] for u in first['items']} & {u['id'] for u in second['items']})
        self.assertEqual(self.req('GET','/users',params={'page':1,'q':marker,'role':'reviewer'}).json()['total'],6)
        exact=self.req('GET','/users',params={'page':1,'q':marker+'姓名11%_'}).json()
        self.assertEqual(exact['total'],1)
        detail=self.req('GET','/users/'+created[0]['id']).json()
        for item in first['items']+[detail]:
            self.assertNotIn('password_hash',item);self.assertNotIn('wechat_nicknames',item)
            self.assertIn('last_login_at',item);self.assertIn('created_at',item)
        _,agent=self.account();_,reviewer=self.account(role='reviewer')
        for client in (agent,reviewer):
            self.req('GET','/users?page=1',client=client,status=403)
            self.req('GET','/users/'+created[0]['id'],client=client,status=403)
            self.req('PATCH','/users/'+created[0]['id'],{'username':'forbidden','display_name':'禁止修改','role':'admin'},1,client=client,status=403)
            self.req('DELETE','/users/'+created[0]['id'],version=1,client=client,status=403)
            self.req('POST','/users/'+created[0]['id']+'/restore',version=1,client=client,status=403)
        self.req('GET','/users/'+uid(),status=404)

    def test_admin_users_edit_delete_restore_revokes_sessions_and_preserves_history(self):
        account,agent=self.account()
        result,_,messages,_=self.issue();ticket=result['ticket'];_,draft=self.ticket_draft(ticket,messages)
        revision=self.req('POST',f"/tickets/{ticket['id']}/revisions",draft,1,client=agent).json()
        detail=self.req('GET','/users/'+account['id']).json()
        body={'username':account['username'],'display_name':'改名-'+uid()[:8],'role':'reviewer'}
        changed=self.req('PATCH','/users/'+account['id'],body,detail['version']).json()
        self.assertEqual(changed['version'],detail['version']+1)
        self.req('GET','/overview',client=agent,status=401)
        self.req('PATCH','/users/'+account['id'],body,detail['version'],status=412)
        reviewer=TestClient(app);self.login(reviewer,changed['username'],'permission-test-password')
        password_body=dict(body,password='replacement-password-2026')
        changed=self.req('PATCH','/users/'+account['id'],password_body,changed['version']).json()
        self.req('GET','/overview',client=reviewer,status=401)
        self.req('POST','/auth/login',{'username':changed['username'],'password':'permission-test-password'},client=reviewer,status=401)
        session=TestClient(app);self.login(session,changed['username'],'replacement-password-2026')
        deleted=self.req('DELETE','/users/'+account['id'],version=changed['version']).json()
        self.assertTrue(deleted['disabled_at'])
        self.req('GET','/overview',client=session,status=401)
        self.req('POST','/auth/login',{'username':changed['username'],'password':'replacement-password-2026'},client=session,status=401)
        self.assertEqual(self.req('GET','/users',params={'page':1,'q':changed['username']}).json()['total'],0)
        self.assertEqual(self.req('GET','/users',params={'page':1,'q':changed['username'],'status':'deleted'}).json()['total'],1)
        self.req('PATCH','/users/'+account['id'],body,deleted['version'],status=409)
        self.fixture_user({'username':changed['username'],'display_name':'不可重用已删除用户名','password':'valid-password-2026','role':'agent'},status=409)
        history=self.req('GET','/tickets/'+ticket['id']).json()
        self.assertEqual(next(r for r in history['revisions'] if r['id']==revision['id'])['created_by'],account['id'])
        restored=self.req('POST','/users/'+account['id']+'/restore',version=deleted['version']).json()
        self.assertIsNone(restored['disabled_at'])
        self.req('GET','/overview',client=session,status=401)
        fresh=TestClient(app);self.login(fresh,changed['username'],'replacement-password-2026')
        self.req('GET','/overview',client=fresh,status=200)
        with connect() as db:
            self.assertEqual(one(db,"SELECT count(*) AS n FROM audit_logs WHERE object_type='user' AND object_id=%s AND action IN ('update','delete','restore')",(account['id'],))['n'],4)

    def test_admin_users_protect_self_reject_blanks_and_do_not_reset_password_on_name_edit(self):
        own=self.req('GET','/auth/me').json()
        self.req('DELETE','/users/'+own['id'],version=own['version'],status=409)
        self.req('PATCH','/users/'+own['id'],{'username':own['username'],'display_name':own['display_name'],'role':'agent'},own['version'],status=409)
        self.assertEqual(self.req('GET','/auth/me').json()['role'],'admin')
        account,agent=self.account()
        changed=self.req('PATCH','/users/'+account['id'],{'username':account['username'],'display_name':'  新姓名-'+uid()[:8]+'  ','role':'agent'},account['version']).json()
        self.assertEqual(changed['display_name'],changed['display_name'].strip())
        self.req('GET','/overview',client=agent,status=200)
        self.req('PATCH','/users/'+account['id'],{'username':'  ','display_name':'有效姓名','role':'agent'},changed['version'],status=422)
        self.req('PATCH','/users/'+account['id'],{'username':account['username'],'display_name':'  ','role':'agent'},changed['version'],status=422)
        self.req('PATCH','/users/'+account['id'],{'username':account['username'],'display_name':changed['display_name'],'role':'agent','password':'short'},changed['version'],status=422)
        self.req('PATCH','/users/'+account['id'],{'username':own['username'],'display_name':changed['display_name'],'role':'agent'},changed['version'],status=409)
        with connect() as db:
            self.assertEqual(one(db,'SELECT role FROM users WHERE id=%s',(own['id'],))['role'],'admin')

    def test_33_file_job_history_filters_paginates_and_preserves_scope(self):
        first,messages,_=self.imported()
        second,_,_=self.imported(TEXT.replace('DemoRecord','OtherRecord'))
        hidden_customer=self.fixture_customer({'name':'任务权限范围'})
        hidden_group=self.fixture_group({'customer_id':hidden_customer['id'],'name':'隐藏任务来源'})
        hidden=self.req('POST','/imports',data={'group_id':hidden_group['id']},
            files={'file':('hidden.txt',TEXT.encode(),'text/plain')}).json()['batch']
        self.req('POST',f"/imports/{hidden['id']}/confirm",{'parse_version':hidden['parse_version'],'accept_warnings':True},hidden['version'])
        env={'DIFY_LOCAL_BASE_URL':'http://test/v1','DIFY_LOCAL_TOPIC_KEY':'topic','DIFY_LOCAL_RECORD_KEY':'record'}
        with patch.dict(os.environ,env),patch('app.dify.run_workflow') as model:
            older=self.req('POST',f"/imports/{first['id']}/extractions",{'profile':'local','mode':'both'}).json()
            latest=self.req('POST',f"/imports/{first['id']}/extractions",{'profile':'local','mode':'ticket'}).json()
            other=self.req('POST',f"/imports/{second['id']}/extractions",{'profile':'local','mode':'both'}).json()
            hidden_job=self.req('POST',f"/imports/{hidden['id']}/extractions",{'profile':'local','mode':'both'}).json()
            issue=self.req('POST','/issues',{'group_id':self.group['id'],'title':'单问题任务',
                'messages':[{'message_id':messages[0]['id'],'relation':'question'},{'message_id':messages[1]['id'],'relation':'answer'}]}).json()['issue']
            issue_job=self.req('POST',f"/issues/{issue['id']}/extractions",{'profile':'local','mode':'both'}).json()
            model.assert_not_called()
        username='jobs-'+uid()[:8]
        self.fixture_user({'username':username,'display_name':'任务查询客服','password':'file-jobs-password',
            'role':'agent','customer_ids':[self.customer['id']]})
        agent=TestClient(app);self.login(agent,username,'file-jobs-password')
        def get(**params):return self.req('GET','/jobs',client=agent,params=params).json()
        first_page=get(batch_id=first['id'],page=1,page_size=1)
        second_page=get(batch_id=first['id'],page=2,page_size=1)
        self.assertEqual((first_page['total'],first_page['page_size'],len(first_page['items'])),(2,1,1))
        self.assertEqual(first_page['items'][0]['id'],latest['id'])
        self.assertEqual(second_page['items'][0]['id'],older['id'])
        self.assertEqual(get(batch_id=first['id'],page=3,page_size=1)['items'],[])
        self.assertEqual(get(batch_id=second['id'],page=1)['items'][0]['id'],other['id'])
        self.assertEqual(get(batch_id=first['id'],customer_id=hidden_customer['id'],page=1)['total'],0)
        legacy=get()
        self.assertIsInstance(legacy,list)
        expected={older['id'],latest['id'],other['id'],issue_job['id']}
        self.assertEqual({j['id'] for j in legacy},expected)
        self.assertEqual({j['id'] for j in get(page=1)['items']},expected)
        self.assertEqual([j['id'] for j in get(batch_id=first['id'])],[latest['id'],older['id']])
        self.assertEqual(get(customer_id=hidden_customer['id']),[])
        self.assertTrue(all('topic_plan' not in j for j in legacy))
        for params in ({'batch_id':hidden['id']},{'batch_id':hidden['id'],'page':1}):
            self.req('GET','/jobs',client=agent,params=params,status=403)
        self.req('GET','/jobs/'+hidden_job['id'],client=agent,status=403)
        self.req('GET','/jobs/'+hidden_job['id']+'/records',client=agent,status=403)
        self.req('GET','/jobs',client=agent,params={'batch_id':uid(),'page':1},status=404)
        self.req('GET','/jobs?batch_id=invalid',status=422)


class DifyTransportTests(unittest.TestCase):
    def test_known_run_recovery_checks_published_revision(self):
        def started(run,task):pass
        def check(version):
            if version!='original':raise dify.DifyError('workflow_changed','发布版本变化')
        started.check_workflow=check
        transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'status':'succeeded','workflow_id':'new-model','outputs':{'result_json':'{}'}}))
        with patch.dict(os.environ,{'DIFY_LOCAL_BASE_URL':'http://test/v1','DIFY_LOCAL_RECORD_KEY':'test'}),httpx.Client(transport=transport) as client:
            with self.assertRaises(dify.DifyError) as error:
                dify.run_workflow('local','record_extraction',{'scope':{'customer_id':uid()}},started,run_id='existing-run',client=client)
            self.assertEqual(error.exception.code,'workflow_changed')

    def test_stream_and_known_run_recovery(self):
        events=[{'event':'workflow_started','workflow_run_id':'run-1','task_id':'task-1','data':{}},{'event':'workflow_finished','data':{'status':'succeeded','outputs':{'validation_status':'valid','result_json':'{"ok":true}'}}}]
        requests=[]
        def handle(request):
            requests.append(request)
            if request.method=='GET':return httpx.Response(200,json={'status':'succeeded','outputs':{'result_json':'{"recovered":true}'}})
            return httpx.Response(200,text=''.join('data: '+json.dumps(e)+'\n\n' for e in events),headers={'Content-Type':'text/event-stream'})
        payload={'scope':{'customer_id':uid()}}
        with patch.dict(os.environ,{'DIFY_LOCAL_BASE_URL':'http://test/v1','DIFY_LOCAL_RECORD_KEY':'test'}),httpx.Client(transport=httpx.MockTransport(handle)) as client:
            seen=[];result=dify.run_workflow('local','record_extraction',payload,lambda r,t:seen.append(r),client=client)
            self.assertTrue(result['ok']);self.assertEqual(seen,['run-1'])
            result=dify.run_workflow('local','record_extraction',payload,lambda r,t:None,run_id='run-1',client=client)
            self.assertTrue(result['recovered']);self.assertEqual([r.method for r in requests],['POST','GET'])

    def test_hallucinated_evidence_and_quoted_contributor_rejected(self):
        inp=json.loads((config.WORKFLOW_DIR/'example.extraction.input.json').read_text(encoding='utf-8'))
        out=json.loads((config.WORKFLOW_DIR/'example.extraction.output.json').read_text(encoding='utf-8'))
        dify.validate_extraction(inp,out)
        fake=copy.deepcopy(out);fake['ticket']['claims'][0]['evidence'][0]['exact_excerpt']='不存在的内容'
        with self.assertRaises(dify.DifyError):dify.validate_extraction(inp,fake)
        inp['messages'][1]['direct_body_spans']=[]
        with self.assertRaises(dify.DifyError):dify.validate_extraction(inp,out)


class ContractTests(unittest.TestCase):
    def test_removed_management_routes_and_fields_are_absent(self):
        paths=app.openapi()['paths']
        for path in ['/customers','/groups','/groups/{group_id}/participants','/participants','/participants/{participant_id}',
                     '/users/{user_id}/chat-names','/users/{user_id}/customer-scopes']:
            self.assertNotIn('/api/v1'+path,paths)
        fields=app.openapi()['components']['schemas']['UserCreate']['properties']
        self.assertNotIn('customer_ids',fields)
        self.assertNotIn('wechat_nicknames',fields)


if __name__=='__main__':unittest.main()
