from __future__ import annotations
import json,tempfile,unittest,zipfile
from pathlib import Path
from tests.diagnostics.support import load_script
MODULE_PATH=Path(__file__).resolve().parents[2]/'scripts'/'diagnostics'/'report_builder.py'
def load_module():
    return load_script(MODULE_PATH)

def _base_run(root:Path, stage_line:str)->None:
    (root/'stages.tsv').write_text('name\tstatus\texit_code\tduration_seconds\tlog\n'+stage_line,encoding='utf-8')
    (root/'issues.json').write_text('[]',encoding='utf-8')
    (root/'endpoint-results.tsv').write_text('method\tpath\tstatus\tduration_ms\ttest_id\n',encoding='utf-8')

class ActorReportTests(unittest.TestCase):
    def test_report_summarizes_actor_journeys(self):
        m=load_module()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'pytest').mkdir(); _base_run(root,'pytest-api\tPASS\t0\t2.0\tlogs/pytest.log\n')
            (root/'pytest'/'summary.json').write_text(json.dumps({
                'summary': {'total': 2, 'passed': 1, 'failed': 0, 'skipped': 1},
                'tests': [
                    {'nodeid':'test_28_user_actor_journeys.py::test_user_engagement_journey','outcome':'passed','duration_seconds':1.2,'message':None},
                    {'nodeid':'test_30_external_actor_journeys.py::test_supplied_scraper_series_url','outcome':'skipped','duration_seconds':0.1,'message':'MREADER_DIAGNOSTICS_SERIES_URL is not set'},
                ],
                'modules': {},
            }),encoding='utf-8')
            (root/'pytest'/'journey_actions.jsonl').write_text(json.dumps({
                'nodeid':'test_28_user_actor_journeys.py::test_user_engagement_journey','action':'bookmark-series',
                'intended':'bookmark is persisted and visible in the library','expected':True,'observed':True,'passed':True,
            })+'\n',encoding='utf-8')
            result=m.build_report(root,'v-test')
            self.assertEqual((2,1,1),(result['actor_journeys']['total'],result['actor_journeys']['passed'],result['actor_journeys']['skipped']))
            self.assertEqual('bookmark-series',result['actor_journeys']['actions']['items'][0]['action'])
            report=(root/'REPORT.md').read_text(encoding='utf-8')
            for text in ('Actor journeys','test_user_engagement_journey','MREADER_DIAGNOSTICS_SERIES_URL','bookmark-series'):
                self.assertIn(text,report)

    def test_report_summarizes_playwright_browser_journeys(self):
        m=load_module()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'browser').mkdir(); _base_run(root,'browser-ui\tFAIL\t1\t4.0\tlogs/browser-ui.log\n')
            (root/'browser'/'playwright-reader.json').write_text(json.dumps({
                'stats': {'expected': 1, 'unexpected': 1, 'skipped': 0, 'flaky': 0},
                'suites': [{'title':'actor journeys','specs':[
                    {'title':'user can bookmark and read','ok':True,'tests':[{'results':[{'status':'passed','duration':1200}]}]},
                    {'title':'admin can publish chapter','ok':False,'tests':[{'results':[{'status':'failed','duration':800,'error':{'message':'permission denied'}}]}]},
                ]}],
            }),encoding='utf-8')
            result=m.build_report(root,'v-test')
            self.assertEqual((2,1,1),(result['browser_journeys']['total'],result['browser_journeys']['passed'],result['browser_journeys']['failed']))
            report=(root/'REPORT.md').read_text(encoding='utf-8')
            self.assertIn('Browser journeys',report); self.assertIn('admin can publish chapter',report)

class LayeredDiagnosticsReportTests(unittest.TestCase):
    def test_report_summarizes_permission_boundary_and_api_layers(self):
        m=load_module()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); _base_run(root,'pytest-permissions\tFAIL\t1\t1.0\tlogs/permissions.log\npytest-boundary\tPASS\t0\t1.0\tlogs/boundary.log\npytest-api\tPASS\t0\t2.0\tlogs/api.log\n')
            for layer, summary in {
                'permissions': {'total': 562, 'passed': 560, 'failed': 2, 'skipped': 0},
                'boundary': {'total': 272, 'passed': 272, 'failed': 0, 'skipped': 0},
            }.items():
                path=root/'pytest'/layer; path.mkdir(parents=True,exist_ok=True)
                (path/'summary.json').write_text(json.dumps({'summary':summary,'tests':[],'modules':{}}),encoding='utf-8')
            api=root/'pytest'; api.mkdir(exist_ok=True)
            (api/'summary.json').write_text(json.dumps({'summary':{'total':151,'passed':151,'failed':0,'skipped':0},'tests':[],'modules':{}}),encoding='utf-8')
            result=m.build_report(root,'v-test')
            self.assertEqual(562,result['test_layers']['permissions']['total'])
            self.assertEqual(2,result['test_layers']['permissions']['failed'])
            self.assertEqual(272,result['test_layers']['boundary']['passed'])
            report=(root/'REPORT.md').read_text(encoding='utf-8')
            self.assertIn('Diagnostic test layers',report)
            self.assertIn('permissions',report)
            self.assertIn('boundary',report)
            self.assertEqual('permissions', result['cascade_analysis'][0]['source_layer'])
            self.assertIn('downstream', result['cascade_analysis'][0]['guidance'].lower())
            self.assertIn('Failure cascade guidance', report)


class ReportBundleTests(unittest.TestCase):
    def test_report_survives_missing_pytest_summary_and_failed_collectors(self):
        m=load_module()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'snapshot'/'after').mkdir(parents=True)
            (root/'stages.tsv').write_text('name\tstatus\texit_code\tduration_seconds\tlog\napi-route-audit\tPASS\t0\t0.1\tlogs/route.log\npytest-api\tFAIL\t1\t2.0\tlogs/pytest.log\n',encoding='utf-8')
            (root/'issues.json').write_text(json.dumps([{'severity':'error','category':'test-stage','component':'pytest-api','reason':'failed','evidence':'logs/pytest.log'},{'severity':'warning','category':'collector','component':'rabbitmq','reason':'unavailable','evidence':'snapshot/after/collector-errors.tsv'}]),encoding='utf-8')
            (root/'endpoint-results.tsv').write_text('method\tpath\tstatus\tduration_ms\ttest_id\n',encoding='utf-8')
            result=m.build_report(root,'v-test'); self.assertEqual('FAIL',result['overall']); self.assertTrue((root/'REPORT.md').exists()); self.assertTrue((root/'REPORT.json').exists()); self.assertTrue((root/'REPORT_BUNDLE.zip').exists()); self.assertIn('pytest-api',(root/'REPORT.md').read_text(encoding='utf-8'))

    def test_bundle_contains_evidence_and_excludes_secret_temp_files(self):
        m=load_module()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'logs').mkdir(); (root/'stages.tsv').write_text('name\tstatus\texit_code\tduration_seconds\tlog\nsmoke\tPASS\t0\t0.1\tlogs/smoke.log\n',encoding='utf-8'); (root/'issues.json').write_text('[]',encoding='utf-8'); (root/'endpoint-results.tsv').write_text('method\tpath\tstatus\tduration_ms\ttest_id\nGET\t/healthz\t200\t1.0\t\n',encoding='utf-8'); (root/'logs'/'smoke.log').write_text('ok\n',encoding='utf-8'); (root/'.raw-secrets.tmp').write_text('password=secret\n',encoding='utf-8')
            result=m.build_report(root,'v-test'); self.assertEqual('PASS',result['overall'])
            with zipfile.ZipFile(root/'REPORT_BUNDLE.zip') as zf: names=set(zf.namelist())
            self.assertIn('REPORT.md',names); self.assertIn('logs/smoke.log',names); self.assertNotIn('.raw-secrets.tmp',names); self.assertNotIn('REPORT_BUNDLE.zip',names)
if __name__=='__main__': unittest.main()
