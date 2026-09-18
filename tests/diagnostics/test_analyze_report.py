from __future__ import annotations
import json, tempfile, unittest
from pathlib import Path
from tests.diagnostics.support import load_script
MODULE_PATH=Path(__file__).resolve().parents[2]/'scripts'/'diagnostics'/'analyze_report.py'
def load_module():
    return load_script(MODULE_PATH)

class AnalyzeReportTests(unittest.TestCase):
    def test_classifies_circular_import_with_direct_evidence(self):
        m=load_module(); issues=m.classify_text('logs/pods/image/current.log',"ImportError: cannot import name '_submit_thumbnail_job' from partially initialized module 'app.routers.jobs' (most likely due to a circular import)")
        self.assertTrue(any(i['category']=='python-import' and 'circular import' in i['reason'].lower() for i in issues))
    def test_classifies_crashloop_oom_probe_and_connection_without_overclaim(self):
        m=load_module(); text='\n'.join(['Reason: CrashLoopBackOff','Reason: OOMKilled','Readiness probe failed: dial tcp 10.1.0.4:8000: connect: connection refused'])
        issues=m.classify_text('snapshot/after/pod.txt',text); cats={i['category'] for i in issues}
        self.assertTrue({'crashloop','oom','probe','connectivity'} <= cats); self.assertFalse(any('database' in i['reason'].lower() for i in issues))
    def test_does_not_classify_false_oom_state(self):
        m=load_module(); text='state={"Status":"running","OOMKilled":false,"ExitCode":0}'
        issues=m.classify_text('snapshot/after/docker-inspect-api.txt',text)
        self.assertFalse(any(i['category']=='oom' for i in issues))
    def test_ready_pod_does_not_promote_historical_probe_or_refusal_to_error(self):
        m=load_module(); text='''State: Running\nReady: True\nContainersReady: True\nEvents:\n  Warning Unhealthy Readiness probe failed: Get "http://10.1.0.4:8000/health": dial tcp 10.1.0.4:8000: connect: connection refused\n'''
        issues=m.classify_text('logs/pods/after/mreader-user/api-123/describe.txt',text)
        self.assertFalse(any(i['category'] in {'probe','connectivity'} and i['severity']=='error' for i in issues))
    def test_rabbitmq_success_line_with_failed_word_is_not_failure(self):
        m=load_module(); text="ra: started cluster 'mreader.media.thumbnail' with 1 servers. 0 servers failed to start: []. Leader: {'mreader',rabbit@node}"
        issues=m.classify_text('snapshot/after/compose-logs.txt',text)
        self.assertFalse(any(i['category']=='rabbitmq' for i in issues))
    def test_classifies_postgres_permission_and_auth(self):
        m=load_module(); issues=m.classify_text('logs/db.log','permission denied for relation reading_state_v1\npassword authentication failed for user "progress_runtime"'); cats={i['category'] for i in issues}
        self.assertIn('postgres-permission',cats); self.assertIn('postgres-auth',cats)
    def test_redacts_headers_password_db_urls_and_tokens(self):
        m=load_module(); source='Authorization: Bearer abc.def.ghi\nCookie: session=secret-cookie\npassword=Sup3rSecret!\nDATABASE_URL=postgresql://admin:dbpass@db:5432/manhwa\ntoken=abcdefghijklmnopqrstuvwx123456\n'
        redacted=m.redact_text(source,known_secrets=['Sup3rSecret!','secret-cookie'])
        for secret in ['abc.def.ghi','secret-cookie','Sup3rSecret!','dbpass','abcdefghijklmnopqrstuvwx123456']: self.assertNotIn(secret,redacted)
        self.assertIn('***',redacted)
    def test_collector_errors_become_findings(self):
        m=load_module()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); snap=root/'snapshot'/'after'; snap.mkdir(parents=True)
            (snap/'collector-errors.tsv').write_text('collector\texit_code\tmessage\npostgres-connectivity\t1\tsee postgres-connectivity.txt\nkubectl-admin-hpa\t1\tmissing CRD\n',encoding='utf-8')
            (root/'stages.tsv').write_text('name\tstatus\texit_code\tduration_seconds\tlog\n',encoding='utf-8')
            result=m.analyze_run(root)
            self.assertTrue(any(i['category']=='collector' and i['severity']=='error' and i['component']=='postgres-connectivity' for i in result['issues']))
            self.assertTrue(any(i['category']=='collector' and i['severity']=='warning' for i in result['issues']))

class AnalyzeRunIntegrationTests(unittest.TestCase):
    def test_analyze_run_merges_http_exchanges_from_layer_subdirectories(self):
        m=load_module()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for layer,status in [('permissions',200),('boundary',503)]:
                path=root/'pytest'/layer; path.mkdir(parents=True)
                (path/'http_exchanges.jsonl').write_text(json.dumps({'method':'OPTIONS','url':f'http://host/{layer}','status':status,'duration_ms':1})+'\n',encoding='utf-8')
            (root/'stages.tsv').write_text('name\tstatus\texit_code\tduration_seconds\tlog\n',encoding='utf-8')
            result=m.analyze_run(root)
            self.assertEqual(2,len(result['endpoints']))
            self.assertEqual({'permissions','boundary'},{row['layer'] for row in result['endpoints']})
            self.assertTrue(any(i['category']=='http-5xx' and i['component']=='/boundary' and i.get('layer')=='boundary' for i in result['issues']))
            table=(root/'endpoint-results.tsv').read_text(encoding='utf-8')
            self.assertTrue(table.startswith('layer\tmethod\tpath\tstatus'))

    def test_analyze_run_writes_endpoint_results_and_issues(self):
        m=load_module()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'pytest').mkdir(); (root/'logs').mkdir()
            (root/'pytest'/'http_exchanges.jsonl').write_text(json.dumps({'method':'GET','url':'http://host.docker.internal:8080/api/catalog/search?q=x','status':500,'duration_ms':12.5,'request_json':{'password':'secret'}})+'\n',encoding='utf-8')
            (root/'logs'/'pod.log').write_text('Traceback (most recent call last):\nImportError: circular import\n',encoding='utf-8')
            (root/'stages.tsv').write_text('name\tstatus\texit_code\tduration_seconds\tlog\npytest-api\tFAIL\t1\t1.0\tlogs/pytest.log\n',encoding='utf-8')
            result=m.analyze_run(root,known_secrets=['secret']); self.assertGreaterEqual(len(result['issues']),2)
            endpoint=(root/'endpoint-results.tsv').read_text(encoding='utf-8'); self.assertIn('/api/catalog/search',endpoint); self.assertIn('\t500\t',endpoint)
            self.assertNotIn('secret',(root/'pytest'/'http_exchanges.jsonl').read_text(encoding='utf-8')); issues=json.loads((root/'issues.json').read_text(encoding='utf-8')); self.assertTrue(any(i['category']=='http-5xx' for i in issues))

if __name__=='__main__': unittest.main()
