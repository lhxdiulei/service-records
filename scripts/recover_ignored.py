"""Apply a reviewed source-anchored recovery plan, then use durable Dify jobs.

Default is read-only. Plan entries require exact message hashes; repeated runs
reuse issue anchors and the same recovery job. No raw text or formal content is
rewritten. Run inside the project API container with the plan mounted read-only.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))

from psycopg.types.json import Jsonb
from app.db import connect,rows,one,plain,digest,audit
from app import services as S,ai_records as A,triage as T,worker as W,models as M,deletions as D


def snapshot(db):
    source=rows(db,'SELECT id,raw_text,text_sha256,sender_name_raw,sent_at FROM messages ORDER BY id')
    protected=[]
    for table in ('ticket_revisions','qa_revisions'):
        protected+=rows(db,f"SELECT row_to_json(r) AS content FROM {table} r WHERE origin='human' OR state IN ('in_review','approved') ORDER BY id")
    return dict(raw_hash=digest(source),raw_count=len(source),protected_hash=digest(protected))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--plan',required=True);parser.add_argument('--apply',action='store_true')
    parser.add_argument('--output',required=True,type=Path,help='恢复报告路径，容器运行时需指定可写挂载目录');args=parser.parse_args()
    plan=json.loads(Path(args.plan).read_text(encoding='utf-8'));report=dict(applied=args.apply,groups=[],new_issues=0,changed_links=0)
    with connect() as db:
        user=one(db,"SELECT * FROM users WHERE role='admin' AND disabled_at IS NULL ORDER BY created_at LIMIT 1")
        before=snapshot(db);report['before']=before
        if args.apply:
            db.execute('SELECT pg_advisory_xact_lock(671904524)')
            if one(db,"SELECT 1 FROM extraction_jobs WHERE state IN ('queued','running','cancel_requested') LIMIT 1"):
                raise RuntimeError('Wait for active jobs before changing their source associations')
            rows(db,'SELECT id FROM chat_groups ORDER BY id FOR UPDATE')
        for item in plan['groups']:
            links=[]
            for entry in item['messages']:
                message=S.entity(db,'messages',entry['message_id'],user);D.active(db,'message',message['id'])
                if message['text_sha256']!=entry['raw_sha']:raise RuntimeError('Source hash changed')
                disposition=one(db,'SELECT * FROM message_dispositions WHERE message_id=%s',(message['id'],))
                if disposition['decision_source']=='human' and disposition['state']=='ignored':
                    raise RuntimeError('Plan cannot override an explicitly ignored human decision')
                links.append(dict(message_id=entry['message_id'],relation=entry['relation']))
            issue=S.entity(db,'issues',item['issue_id'],user) if item['issue_id'] else A.existing_issue(db,message['customer_id'],links)
            result=dict(key=item['key'],title=item['title'],mode=item['mode'],issue_id=str(issue['id']) if issue else None,new_issue=issue is None)
            if args.apply:
                if issue is None:
                    group=S.entity(db,'chat_groups',message['group_id'],user,True)
                    issue=S.create_issue(db,user,group,item['title'],links,ai=True)['issue'];report['new_issues']+=1
                    changed=links
                else:
                    changed=[a for a in links if not one(db,'SELECT 1 FROM issue_messages WHERE issue_id=%s AND message_id=%s AND active AND relation=%s',(issue['id'],a['message_id'],a['relation']))]
                    if changed:
                        S.lock_sources(db,[str(issue['id'])],user,[a['message_id'] for a in changed])
                        S.assign_messages(db,user,issue,changed,ai=True)
                report['changed_links']+=len(changed);result['issue_id']=str(issue['id'])
                for entry in item['messages']:
                    db.execute("UPDATE message_dispositions SET decision_source='rule',reason=%s WHERE message_id=%s",('忽略记录复核：'+entry['reason'],entry['message_id']))
                audit(db,user['id'],'recover_ignored','issue',issue['id'],issue['customer_id'],dict(plan_key=item['key'],message_ids=[a['message_id'] for a in links],changed=len(changed)))
            report['groups'].append(result)
        report['reassessment']=T.reassess(db,user,dry_run=not args.apply,state='ignored')
        if args.apply:
            for item in report['groups']:
                issue=S.entity(db,'issues',item['issue_id'],user)
                key=digest(dict(plan=plan,issue_id=item['issue_id'],message_version=issue['message_version'],mode=item['mode']))
                job=one(db,"SELECT * FROM extraction_jobs WHERE target_issue_id=%s AND input_manifest->>'recovery_key'=%s ORDER BY created_at LIMIT 1",(issue['id'],key))
                if not job:
                    job=W.enqueue(db,user,M.Extract(profile='local',mode=item['mode']),issue=issue)
                    manifest=dict(job['input_manifest'],recovery_key=key)
                    db.execute('UPDATE extraction_jobs SET input_manifest=%s,input_hash=%s WHERE id=%s',(Jsonb(manifest),digest(manifest),job['id']))
                item['job_id']=str(job['id']);item['job_state']=job['state']
        after=snapshot(db)
        if before!=after:raise RuntimeError('Raw source or protected revisions changed')
        report.update(raw_source_unchanged=True,protected_revisions_unchanged=True,status='passed')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(plain(report),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(plain(report),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
