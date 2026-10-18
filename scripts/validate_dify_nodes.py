"""Read-only validation within an existing Dify 1.17.1 API container.

PowerShell: Get-Content -Raw dify/topic_assignment_v1.yml |
 docker exec -i dify-local-api-1 /app/api/.venv/bin/python -c (Get-Content -Raw scripts/validate_dify_nodes.py)
"""
import json
import sys
import yaml
from graphon.nodes.llm.entities import LLMNodeData
from graphon.nodes.code.entities import CodeNodeData
from graphon.nodes.start.entities import StartNodeData
from graphon.nodes.end.entities import EndNodeData
from graphon.nodes.if_else.entities import IfElseNodeData

document=yaml.safe_load(sys.stdin.read())
validators={'start':StartNodeData,'code':CodeNodeData,'llm':LLMNodeData,'end':EndNodeData,'if-else':IfElseNodeData}
for node in document['workflow']['graph']['nodes']:
    validators[node['data']['type']].model_validate(node['data'])
    if node['data']['type']=='code':
        namespace={}
        exec(compile(node['data']['code'],node['id'],'exec'),namespace)
        if node['id']=='prepare':
            try:namespace['main']('{bad-json')
            except ValueError:pass
            else:raise AssertionError('Malformed input accepted')
        if node['id']=='check':
            assert namespace['main']('{bad-json')['validation_status']=='invalid'
            assert namespace['main']('{"schema_version":"1.0"}')['validation_status']=='invalid'
print(json.dumps({'app':document['app']['name'],'nodes_validated':len(document['workflow']['graph']['nodes']),'status':'passed'}))
