"""Kiểm tra agent với tools bonus mà không gọi LLM API."""
import json
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from agent import run_agent
from bonus.tools import BonusTools


def call(call_id,name,args):
    raw=json.dumps(args)
    c={'id':call_id,'name':name,'arguments':raw}
    m={'role':'assistant','content':None,'tool_calls':[{'id':call_id,'type':'function','function':{'name':name,'arguments':raw}}]}
    return {'message':m,'calls':[c],'finish':'tool_calls','usage':{}}

def final(answer='Đã kiểm tra'):
    return {'message':{'role':'assistant','content':answer},'calls':[],'finish':'stop','usage':{}}


class ScriptedProvider:
    def __init__(self,responses): self.responses=iter(responses); self.histories=[]; self.schemas=[]
    def complete(self,messages,schemas):
        self.histories.append(list(messages));self.schemas.append(schemas)
        return next(self.responses)


class BonusAgentTests(unittest.TestCase):
    def test_bonus_schemas_and_system_prompt(self):
        t=BonusTools();p=ScriptedProvider([final()])
        self.assertEqual(run_agent('Kiểm tra',p,t)['status'],'completed')
        names={x['function']['name'] for x in p.schemas[0]}
        self.assertTrue({'get_github_status','get_cloudflare_status','get_vercel_status','get_npm_status','get_digitalocean_status'}.issubset(names))
        self.assertIn('DigitalOcean',p.histories[0][0]['content'])
    def test_429_observation_returns_to_model(self):
        t=BonusTools(scenario='rate_limit_once')
        p=ScriptedProvider([call('a','get_vercel_status',{}),call('b','get_vercel_status',{}),final()])
        result=run_agent('Kiểm tra',p,t,max_steps=5)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(json.loads(p.histories[1][-1]['content'])['error'],'RATE_LIMITED')
        self.assertEqual(json.loads(p.histories[2][-1]['content'])['provider'],'vercel')
    def test_invalid_arguments_observation_returns_to_model(self):
        t=BonusTools()
        bad={'provider':'npm','incident_id':'cc0t2r4403sy','offset':'zero'}
        good={'provider':'npm','incident_id':'cc0t2r4403sy','offset':0}
        details=t.execute('get_incident_details',good)
        p=ScriptedProvider([call('a','get_incident_details',bad),call('b','get_incident_details',good),final('Nguồn: '+details['url'])])
        result=run_agent('Kiểm tra',p,t,max_steps=5)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(json.loads(p.histories[1][-1]['content'])['error'],'INVALID_ARGUMENTS')
        self.assertTrue(json.loads(p.histories[2][-1]['content'])['ok'])

    def test_persistent_429_is_bounded_to_three_attempts(self):
        t=BonusTools(scenario='rate_limit_always')
        p=ScriptedProvider([call(str(i),'get_vercel_status',{}) for i in range(3)] + [final('Vercel chưa xác minh được do rate limit.')])
        result=run_agent('Kiểm tra Vercel',p,t,max_steps=5)
        events=[x for x in result['trace'] if x['event']=='tool']
        self.assertEqual(len(events),3)
        self.assertTrue(events[-1]['result']['retry_exhausted'])
        self.assertEqual(result['status'],'completed')

    def test_unrequested_incident_lists_are_compacted_only_for_model(self):
        p=ScriptedProvider([call('a','get_github_status',{}),final()])
        result=run_agent('Tổng hợp trạng thái và timestamp, không cần lịch sử.',p,BonusTools())
        observation=json.loads(p.histories[1][-1]['content'])
        trace_result=next(x['result'] for x in result['trace'] if x['event']=='tool')
        self.assertEqual(observation['incidents'],[])
        self.assertGreater(len(trace_result['incidents']),0)
        self.assertGreater(observation['incident_context']['returned_by_tool'],0)

    def test_common_cause_caveat_does_not_request_incident_history(self):
        p=ScriptedProvider([call('a','get_github_status',{}),final()])
        run_agent('Tổng hợp status, không suy luận sự cố có chung nguyên nhân.',p,BonusTools())
        observation=json.loads(p.histories[1][-1]['content'])
        self.assertEqual(observation['incidents'],[])
        self.assertIn('Không suy ra không có incident',observation['incident_context']['note'])

if __name__=='__main__': unittest.main()
