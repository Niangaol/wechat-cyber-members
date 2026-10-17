import json, unittest
from test_integration import BASE_CFG,FakeModel,make_resident,stop_patches

class LearningTests(unittest.TestCase):
    def setUp(self):
        self.r=make_resident(BASE_CFG)
        self.addCleanup(stop_patches,self.r);self.addCleanup(self.r.db.close)
        self.ck='direct:很帅的年糕'
        self.model=FakeModel()
        self.r.memory.note_messages(self.ck,20)
    def test_pending_without_samples_costs_nothing(self):
        self.r.learn_cycle(BASE_CFG,self.model)
        self.assertEqual(self.model.calls,[])
        self.assertEqual(self.r.quota.status()['used_5h'],0)
        self.assertTrue(self.r.memory.needs_learn(self.ck))
    def test_samples_include_only_own_user_turns(self):
        self.r.memory.record_turn(self.ck,'user','我喜欢塞尔达')
        self.r.memory.record_turn(self.ck,'assistant','助手口头禅')
        self.r.memory.record_turn('direct:别人','user','别人的偏好')
        sample=self.r.memory.learning_sample(self.ck)
        self.assertEqual([x['text'] for x in sample],['我喜欢塞尔达'])
    def test_sensitive_sample_not_sent_to_model(self):
        self.r.memory.record_turn(self.ck,'user','sk-example_secret_123456')
        self.assertEqual(self.r.memory.learning_sample(self.ck),[])
        self.r.learn_cycle(BASE_CFG,self.model)
        self.assertEqual(self.model.calls,[])
    def test_failure_has_cooldown_and_keeps_pending(self):
        self.r.memory.record_turn(self.ck,'user','今天拍照很好看')
        calls=[]
        def fail(*args):calls.append(True);return 'not json'
        self.model.call=fail
        self.r.learn_cycle(BASE_CFG,self.model)
        self.r.learn_cycle(BASE_CFG,self.model)
        self.assertEqual(len(calls),1)
        self.assertTrue(self.r.memory.needs_learn(self.ck))
    def test_private_fact_never_persisted(self):
        self.model.call=lambda *args:json.dumps({'style':'简短','facts':['13800138000']})
        self.assertFalse(self.r.memory.learn(self.ck,[{'text':'hi'}],self.model))
        self.assertEqual(self.r.memory.context_for(self.ck)['facts'],[])

if __name__=='__main__':unittest.main()
