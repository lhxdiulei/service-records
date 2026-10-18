"""Repair only the two existing records apps using Dify 1.17.1 services.

Run inside the Dify API container after copying this script and the System
files to /tmp/records-repair/. Credentials are never printed or exported.
Published versions remain available for rollback and API keys are unchanged.
"""
import argparse
import json
from pathlib import Path
import yaml


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--base-url',default='http://records-ollama:11434')
    parser.add_argument('--model',default='qwen3-vl:4b-instruct-q4_K_M')
    parser.add_argument('--prompt-dir',default='/tmp/records-repair')
    args=parser.parse_args()
    from app_factory import create_app
    _,app=create_app()
    with app.app_context():
        from extensions.ext_database import db
        from models import App
        from models.account import Account
        from models.provider import ProviderModel
        from models.workflow import Workflow
        from services.model_provider_service import ModelProviderService
        from services.workflow_service import WorkflowService
        from sqlalchemy import select
        from sqlalchemy.orm import Session
        provider='langgenius/ollama/ollama'
        names=('topic_assignment_v1','record_extraction_v1')
        with Session(db.engine) as session:
            apps=list(session.scalars(select(App).where(App.name.in_(names))))
            if len(apps)!=2 or len({a.tenant_id for a in apps})!=1:
                raise RuntimeError('Expected exactly two target apps in one workspace')
            tenant=apps[0].tenant_id
            model=session.scalar(select(ProviderModel).where(ProviderModel.tenant_id==tenant,
                ProviderModel.provider_name==provider,ProviderModel.model_name==args.model,
                ProviderModel.model_type=='llm'))
            if not model or not model.credential_id:
                raise RuntimeError('Expected an existing local Qwen LLM credential')
            svc=ModelProviderService()
            current=svc.get_model_credential(tenant_id=tenant,provider=provider,model_type='llm',
                model=args.model,credential_id=model.credential_id)
            credentials=current['credentials'].copy()
            changed=credentials.get('base_url')!=args.base_url or str(credentials.get('max_tokens'))!='4096'
            print(json.dumps({'event':'model_config','old_base_url':credentials.get('base_url'),
                'new_base_url':args.base_url,'model':args.model,'apply':args.apply}),flush=True)
            credentials.update(base_url=args.base_url,context_size='8192',max_tokens='4096')
            if args.apply and changed:
                svc.update_model_credential(tenant_id=tenant,provider=provider,model_type='llm',
                    model=args.model,credentials=credentials,credential_id=model.credential_id,
                    credential_name=current.get('current_credential_name'))
            workflows=WorkflowService()
            for target in apps:
                draft=session.scalar(select(Workflow).where(Workflow.app_id==target.id,Workflow.version=='draft'))
                if draft is None:
                    raise RuntimeError('Target app has no draft')
                old_nodes={n['id']:n['data'] for n in draft.graph_dict['nodes']}
                selected=old_nodes['extract']['model']
                if selected['provider']!=provider or selected['name']!=args.model:
                    raise RuntimeError('Unexpected selected model; refusing to replace it')
                source=yaml.safe_load((Path(args.prompt_dir)/(target.name+'.yml')).read_text(encoding='utf-8'))
                graph=source['workflow']['graph']
                prompt=(Path(args.prompt_dir)/(target.name+'.system.txt')).read_text(encoding='utf-8').strip()
                for node in graph['nodes']:
                    if node['data']['type']=='llm':
                        params=node['data']['model']['completion_params']
                        node['data']['model']={**selected,'completion_params':params}
                published=session.get(Workflow,target.workflow_id)
                needs_publish=published is None or published.graph_dict!=graph
                previous=target.workflow_id
                if args.apply and (draft.graph_dict!=graph or needs_publish):
                    account=session.get(Account,draft.updated_by or draft.created_by)
                    if account is None:
                        raise RuntimeError('Original editor account not found')
                    workflows.sync_draft_workflow(app_model=target,graph=graph,features=draft.features_dict,
                        unique_hash=draft.unique_hash,account=account,environment_variables=draft.environment_variables,
                        conversation_variables=draft.conversation_variables,session=session,graph_only=True,commit=False)
                    if needs_publish:
                        new=workflows.publish_workflow(session=session,app_model=target,account=account,
                            marked_name='Local Qwen connection repair',marked_comment='Local model endpoint, explicit context/output limits and current System prompt')
                        session.flush()
                        target.workflow_id=new.id
                        target.updated_by=account.id
                    session.commit()
                print(json.dumps({'event':'workflow','name':target.name,'app_id':target.id,
                    'previous_workflow_id':previous,'workflow_id':target.workflow_id,
                    'system_chars':len(prompt),'needs_publish':needs_publish,'applied':args.apply}),flush=True)


if __name__=='__main__':
    main()
