"""Regression checks for the generated prompt's compact output contract."""
import copy
import json
import unittest
from jsonschema import Draft202012Validator
import yaml
from build_dify_dsl import ROOT,build,compact_output_schema,strip_annotations,system_prompt,user_prompt,model_schema


def expand(schema):
    definitions=schema.get('$defs',{})

    def visit(value):
        if isinstance(value,list):
            return [visit(v) for v in value]
        if not isinstance(value,dict):
            return value
        if '$ref' in value:
            assert len(value)==1 and value['$ref'].startswith('#/$defs/')
            return visit(definitions[value['$ref'].split('/')[-1]])
        return {k:visit(v) for k,v in value.items() if k!='$defs'}

    return visit(schema)


class PromptTests(unittest.TestCase):
    def test_exact_validation_constraints_preserved(self):
        for stage in ['topic_assignment','record_extraction']:
            with self.subTest(stage=stage):
                original=json.loads((ROOT/'backend/workflows'/f'{stage}.output.schema.json').read_text(encoding='utf-8'))
                compact=compact_output_schema(original)
                Draft202012Validator.check_schema(compact)
                self.assertEqual(expand(compact),strip_annotations(original))
                # 'title' is a business field and must not be lost when removing
                # JSON Schema annotation keys with the same spelling.
                if stage=='record_extraction':
                    self.assertIn('title',expand(compact)['properties']['ticket']['anyOf'][0]['properties'])

    def test_positive_and_negative_examples_match_backend_schema(self):
        for stage,example in [('topic_assignment','topic'),('record_extraction','extraction')]:
            original=json.loads((ROOT/'backend/workflows'/f'{stage}.output.schema.json').read_text(encoding='utf-8'))
            fixture=json.loads((ROOT/'backend/workflows'/f'example.{example}.output.json').read_text(encoding='utf-8'))
            compact=compact_output_schema(original)
            variants=[fixture,{},dict(fixture,unexpected='not allowed'),dict(fixture,schema_version='2.0')]
            if stage=='record_extraction':
                for field in list(fixture['ticket']):
                    invalid=copy.deepcopy(fixture);del invalid['ticket'][field];variants.append(invalid)
                for key,value in [('message_id','invalid-uuid'),('exact_excerpt',''),('occurrence',0),('extra','unexpected')]:
                    invalid=copy.deepcopy(fixture);invalid['ticket']['claims'][0]['evidence'][0][key]=value;variants.append(invalid)
                invalid=copy.deepcopy(fixture);invalid['qa_candidates'][0]['contributors']=[];variants.append(invalid)
                invalid=copy.deepcopy(fixture);invalid['risk_flags']=['unsupported'];variants.append(invalid)
                invalid=copy.deepcopy(fixture);invalid['ticket']=None;variants.append(invalid)
            old=Draft202012Validator(original,format_checker=Draft202012Validator.FORMAT_CHECKER)
            new=Draft202012Validator(compact,format_checker=Draft202012Validator.FORMAT_CHECKER)
            for candidate in variants:
                self.assertEqual(old.is_valid(candidate),new.is_valid(candidate))
            self.assertTrue(new.is_valid(fixture))

    def test_shared_evidence_defined_once(self):
        schema=json.loads((ROOT/'backend/workflows/record_extraction.output.schema.json').read_text(encoding='utf-8'))
        compact=compact_output_schema(schema)
        text=json.dumps(compact,ensure_ascii=False)
        self.assertEqual(text.count('"exact_excerpt"'),2)  # property + required entry
        self.assertEqual(text.count('"#/$defs/Evidence"'),6)  # Claim shared by two consumers
        self.assertIn('Claim',compact['$defs'])
        self.assertIn('RiskFlag',compact['$defs'])
        self.assertNotIn('原文定位请求',system_prompt('record_extraction'))

    def test_generated_artifacts_match_builder(self):
        for stage in ['topic_assignment','record_extraction']:
            document=yaml.safe_load((ROOT/'dify'/f'{stage}_v1.yml').read_text(encoding='utf-8'))
            expected=system_prompt(stage)
            prompts=next(n for n in document['workflow']['graph']['nodes'] if n['id']=='extract')['data']['prompt_template']
            self.assertEqual(len([p for p in prompts if p['role']=='system']),1)
            self.assertEqual(prompts[0]['text'],expected)
            self.assertEqual((ROOT/'dify'/f'{stage}_v1.system.txt').read_text(encoding='utf-8').strip(),expected)
            self.assertEqual(prompts[1]['text'],user_prompt(stage))
            self.assertEqual(prompts[1]['text'].count('{{#prepare.compact_payload_json#}}'),1)
            self.assertEqual((ROOT/'dify'/f'{stage}_v1.user.txt').read_text(encoding='utf-8').strip(),user_prompt(stage))

    def test_prompt_budget_and_readable_contract(self):
        self.assertLess(len(system_prompt('record_extraction')),7600)
        self.assertLess(len(system_prompt('topic_assignment')),2823)
        for stage in ['topic_assignment','record_extraction']:
            text=system_prompt(stage)
            self.assertEqual(text.count('输出格式（JSON Schema）：'),1)
            json_part=text.split('输出格式（JSON Schema）：\n',1)[1].split('\n',1)[1]
            schema=json.loads(json_part)
            Draft202012Validator.check_schema(schema)

    def test_native_schema_is_literal_and_matches_backend(self):
        # Dify 1.17.1 truncates resolved completion-parameter variables at
        # 1024 chars. A literal schema must reach Ollama without that path.
        for stage,example in [('topic_assignment','topic'),('record_extraction','extraction')]:
            document=build(stage,'langgenius/ollama/ollama','local-qwen')
            nodes={n['id']:n['data'] for n in document['workflow']['graph']['nodes']}
            value=nodes['extract']['model']['completion_params']['json_schema']
            self.assertNotIn('{{#',value)
            original=json.loads((ROOT/'backend/workflows'/f'{stage}.output.schema.json').read_text(encoding='utf-8'))
            schema=json.loads(value)
            self.assertEqual(expand(schema),expand(model_schema(original)))
            namespace={}
            exec(nodes['prepare']['code'],namespace)
            payload=json.loads((ROOT/'backend/workflows'/f'example.{example}.input.json').read_text(encoding='utf-8'))
            prepared=json.loads(namespace['main'](json.dumps(payload))['compact_payload_json'])
            self.assertEqual([m['raw_text'] for m in prepared['messages']],[m['raw_text'] for m in payload['messages']])
            self.assertEqual(prepared['messages'][0]['message_id'],'m1')

    def test_workflow_feedback_rejects_semantic_errors(self):
        for stage,example in [('topic_assignment','topic'),('record_extraction','extraction')]:
            document=build(stage,'langgenius/ollama/ollama','local-qwen')
            nodes={n['id']:n['data'] for n in document['workflow']['graph']['nodes']}
            namespace={};exec(nodes['check']['code'],namespace)
            check=namespace['main']
            payload=json.loads((ROOT/'backend/workflows'/f'example.{example}.input.json').read_text(encoding='utf-8'))
            output=json.loads((ROOT/'backend/workflows'/f'example.{example}.output.json').read_text(encoding='utf-8'))
            self.assertEqual(check(json.dumps(output),json.dumps(payload))['validation_status'],'valid')
            invalid=copy.deepcopy(output)
            if stage=='topic_assignment':
                invalid['assignments'][0]['message_links'].pop()
                self.assertIn('Missing main_message_ids',check(json.dumps(invalid),json.dumps(payload))['feedback'])
                invalid=copy.deepcopy(output);invalid['assignments'][0]['decision']='link_existing'
            else:
                invalid['qa_candidates']=[]
                self.assertIn('eligible requires',check(json.dumps(invalid),json.dumps(payload))['feedback'])
                invalid=copy.deepcopy(output);invalid['ticket']=None
            self.assertEqual(check(json.dumps(invalid),json.dumps(payload))['validation_status'],'invalid')
            edges=document['workflow']['graph']['edges']
            self.assertEqual([(e['source'],e['target']) for e in edges if e['target']=='repair'],[('validity','repair')])
            self.assertEqual([(e['source'],e['target']) for e in edges if e['source']=='recheck'],[('recheck','repaired_end')])


if __name__=='__main__':
    unittest.main()
