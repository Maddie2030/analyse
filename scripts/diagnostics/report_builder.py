#!/usr/bin/env python3
from __future__ import annotations
import csv,json,sys,zipfile
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

def _read_json(path:Path,default:Any):
    if not path.exists(): return default
    try: return json.loads(path.read_text(encoding='utf-8'))
    except Exception: return default

def _read_stages(path:Path)->list[dict[str,Any]]:
    if not path.exists(): return []
    rows=[]
    with path.open(encoding='utf-8') as handle:
        for row in csv.DictReader(handle,delimiter='\t'):
            row['exit_code']=int(row.get('exit_code') or 0); row['duration_seconds']=float(row.get('duration_seconds') or 0); rows.append(row)
    return rows

def _read_endpoints(path:Path)->list[dict[str,str]]:
    if not path.exists(): return []
    with path.open(encoding='utf-8') as handle: return list(csv.DictReader(handle,delimiter='\t'))

def _actor_journey_summary(pytest_summary:dict[str,Any]|None)->dict[str,Any]:
    rows=[]
    if pytest_summary:
        for item in pytest_summary.get('tests') or []:
            nodeid=str(item.get('nodeid') or '')
            if '_actor_journeys.py::' not in nodeid:
                continue
            message=str(item.get('message') or '').strip().replace('\n',' ')
            if len(message)>500:
                message=message[:497]+'...'
            rows.append({
                'nodeid':nodeid,
                'outcome':str(item.get('outcome') or 'unknown'),
                'duration_seconds':float(item.get('duration_seconds') or 0),
                'message':message or None,
            })
    return {
        'total':len(rows),
        'passed':sum(x['outcome']=='passed' for x in rows),
        'failed':sum(x['outcome']=='failed' for x in rows),
        'skipped':sum(x['outcome']=='skipped' for x in rows),
        'journeys':rows,
    }

def _browser_journey_summary(path:Path)->dict[str,Any]:
    payload=_read_json(path,{}) or {}
    items=[]
    def walk(suites:list[dict[str,Any]], prefix:str='')->None:
        for suite in suites or []:
            title=str(suite.get('title') or '').strip()
            scope=' / '.join(x for x in (prefix,title) if x)
            for spec in suite.get('specs') or []:
                statuses=[]; duration_ms=0.0; message=None
                for test in spec.get('tests') or []:
                    for result in test.get('results') or []:
                        status=str(result.get('status') or '')
                        if status: statuses.append(status)
                        duration_ms += float(result.get('duration') or 0)
                        if message is None:
                            error=result.get('error') or {}
                            if isinstance(error,dict) and error.get('message'): message=str(error.get('message'))[:500]
                if spec.get('ok') is True: outcome='passed'
                elif statuses and all(x=='skipped' for x in statuses): outcome='skipped'
                elif any(x in {'failed','timedOut','interrupted'} for x in statuses) or spec.get('ok') is False: outcome='failed'
                else: outcome='unknown'
                items.append({'title':str(spec.get('title') or 'unnamed browser journey'),'scope':scope,'outcome':outcome,'duration_seconds':duration_ms/1000.0,'message':message})
            walk(suite.get('suites') or [],scope)
    walk(payload.get('suites') or [])
    return {
        'total':len(items),
        'passed':sum(x['outcome']=='passed' for x in items),
        'failed':sum(x['outcome']=='failed' for x in items),
        'skipped':sum(x['outcome']=='skipped' for x in items),
        'journeys':items,
        'result_file':'browser/playwright-reader.json' if path.exists() else None,
    }

def _read_journey_actions(path:Path)->dict[str,Any]:
    items=[]
    if path.exists():
        for line in path.read_text(encoding='utf-8',errors='ignore').splitlines():
            if not line.strip(): continue
            try: item=json.loads(line)
            except json.JSONDecodeError: continue
            items.append(item)
    return {
        'total':len(items),
        'passed':sum(bool(x.get('passed')) for x in items),
        'failed':sum(not bool(x.get('passed')) for x in items),
        'items':items,
    }

def _coverage_summary()->dict[str,Any]:
    candidates=[Path('/repo/tests/api/endpoint_coverage.tsv'),Path(__file__).resolve().parents[2]/'tests'/'api'/'endpoint_coverage.tsv']; manifest=next((p for p in candidates if p.exists()),None)
    if manifest is None: return {'declared_routes':None,'classes':{}}
    classes={}; count=0
    with manifest.open(encoding='utf-8') as handle:
        for row in csv.DictReader(handle,delimiter='\t'):
            count+=1; level=row.get('coverage') or 'unknown'; classes[level]=classes.get(level,0)+1
    return {'declared_routes':count,'classes':classes}

def _test_layer_summaries(run_dir:Path, api_summary:dict[str,Any]|None)->dict[str,dict[str,int]]:
    layers={}
    sources={
        'permissions':run_dir/'pytest'/'permissions'/'summary.json',
        'boundary':run_dir/'pytest'/'boundary'/'summary.json',
        'api':run_dir/'pytest'/'summary.json',
        'external':run_dir/'pytest'/'external'/'summary.json',
    }
    for name,path in sources.items():
        payload=api_summary if name=='api' else _read_json(path,None)
        if not payload:
            continue
        summary=payload.get('summary') or {}
        layers[name]={key:int(summary.get(key) or 0) for key in ('total','passed','failed','skipped')}
    return layers

def _test_layer_lines(layers:dict[str,dict[str,int]])->list[str]:
    lines=['','## Diagnostic test layers','']
    if not layers:
        return lines+['- No layered pytest summaries were produced.','']
    lines += ['| Layer | Total | Passed | Failed | Skipped |','|---|---:|---:|---:|---:|']
    for name in ('permissions','boundary','api','external'):
        if name not in layers:
            continue
        row=layers[name]
        lines.append(f"| {name} | {row['total']} | {row['passed']} | {row['failed']} | {row['skipped']} |")
    return lines


def _cascade_analysis(layers:dict[str,dict[str,int]])->list[dict[str,str]]:
    findings=[]
    permissions=layers.get('permissions') or {}
    boundary=layers.get('boundary') or {}
    api=layers.get('api') or {}
    if int(permissions.get('failed') or 0)>0:
        findings.append({
            'source_layer':'permissions',
            'guidance':'Database permission or role-membership checks are failing; downstream API/browser 500/503 failures may be secondary until these grants are reconciled.',
        })
    if int(boundary.get('failed') or 0)>0:
        findings.append({
            'source_layer':'boundary',
            'guidance':'Gateway/routing/CORS boundary checks are failing; downstream functional failures may be caused by wrong-plane routing, service reachability, or edge policy before handler code runs.',
        })
    if int(api.get('failed') or 0)>0 and not findings:
        findings.append({
            'source_layer':'api',
            'guidance':'Permission and boundary layers are clean; prioritize handler integration, persistence, state propagation, and application-code failures in the core API suite.',
        })
    return findings

def _cascade_lines(findings:list[dict[str,str]])->list[str]:
    lines=['','## Failure cascade guidance','']
    if not findings:
        return lines+['- No upstream permission/boundary cascade was detected from the available layer summaries.','']
    for finding in findings:
        lines.append(f"- **{finding['source_layer']}** — {finding['guidance']}")
    return lines+['']

def _next_target(issues:list[dict[str,str]])->dict[str,str]|None:
    errors=[i for i in issues if i.get('severity')=='error']
    if not errors: return None
    priority={'python-import':0,'postgres-auth':1,'postgres-permission':1,'postgres-relation':1,'oom':2,'crashloop':3,'probe':4,'connectivity':5,'dns':5,'timeout':6,'http-5xx':7,'route-coverage':8,'test-stage':9}
    return min(errors,key=lambda item:(priority.get(item.get('category',''),50),item.get('component',''),item.get('evidence','')))

def _bundle(run_dir:Path)->Path:
    bundle=run_dir/'REPORT_BUNDLE.zip'
    with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(run_dir.rglob('*')):
            if not path.is_file() or path==bundle: continue
            rel=path.relative_to(run_dir)
            if path.name.startswith('.raw-') or path.suffix=='.tmp': continue
            archive.write(path,rel.as_posix())
    return bundle

def _actor_lines(actor_journeys:dict[str,Any])->list[str]:
    lines=['## Actor journeys','']
    if actor_journeys['total']:
        lines += [f"Actor journeys: **{actor_journeys['passed']} passed / {actor_journeys['failed']} failed / {actor_journeys['skipped']} skipped**",'', '| Journey | Outcome | Seconds | Detail |','|---|---:|---:|---|']
        for journey in actor_journeys['journeys']:
            name=journey['nodeid'].split('::')[-1]
            detail=(journey.get('message') or '').replace('|','\\|')
            lines.append(f"| `{name}` | {journey['outcome']} | {journey['duration_seconds']:.1f} | {detail} |")
    else:
        lines += ['- No actor-journey results were produced.','']
    actions=actor_journeys['actions']
    lines += ['',f"Actor action assertions: **{actions['passed']} passed / {actions['failed']} failed**",'']
    if actions['items']:
        lines += ['| Actor action | Intended result | Result | Observed |','|---|---|---:|---|']
        for item in actions['items']:
            intended=str(item.get('intended') or '').replace('|','\\|').replace('\n',' ')
            observed=str(item.get('observed') if item.get('observed') is not None else '').replace('|','\\|').replace('\n',' ')
            outcome='PASS' if item.get('passed') else 'FAIL'
            lines.append(f"| `{item.get('action','')}` | {intended} | {outcome} | {observed[:300]} |")
    return lines

def _browser_lines(browser_journeys:dict[str,Any])->list[str]:
    lines=['','## Browser journeys','']
    if not browser_journeys['total']:
        return lines+['- Browser journeys were not run or produced no Playwright JSON report.','']
    lines += [f"Browser journeys: **{browser_journeys['passed']} passed / {browser_journeys['failed']} failed / {browser_journeys['skipped']} skipped**",'', '| Browser journey | Outcome | Seconds | Detail |','|---|---:|---:|---|']
    for journey in browser_journeys['journeys']:
        detail=(journey.get('message') or '').replace('|','\\|').replace('\n',' ')
        label=' / '.join(x for x in (journey.get('scope'),journey.get('title')) if x)
        lines.append(f"| `{label}` | {journey['outcome']} | {journey['duration_seconds']:.1f} | {detail} |")
    return lines

def _stage_lines(stages:list[dict[str,Any]])->list[str]:
    lines=['## Stage results','','| Stage | Result | Exit | Seconds | Log |','|---|---:|---:|---:|---|']
    if not stages:
        return lines+['| _none_ | WARN | 0 | 0.0 | `stages.tsv missing/empty` |']
    for stage in stages:
        lines.append(f"| {stage.get('name','')} | {stage.get('status','')} | {stage.get('exit_code',0)} | {float(stage.get('duration_seconds') or 0):.1f} | `{stage.get('log','')}` |")
    return lines

def _issue_lines(issues:list[dict[str,str]],working:list[str],next_target:dict[str,str]|None)->list[str]:
    lines=['','## What is working','']
    lines += [f'- {name}' for name in working] or ['- No diagnostic stage completed successfully.']
    lines += ['','## Issues','']
    if issues:
        for issue in issues:
            lines.append(f"- **{str(issue.get('severity','info')).upper()} — {issue.get('category','unknown')} — {issue.get('component','unknown')}**: {issue.get('reason','')} (`{issue.get('evidence','')}`)")
    else:
        lines.append('- No error/warning findings were classified from the collected evidence.')
    lines += ['','## Next diagnostic target','']
    if next_target:
        lines.append(f"Investigate **{next_target.get('component','unknown')}** first: {next_target.get('reason','')} (evidence: `{next_target.get('evidence','')}`).")
    else:
        lines.append('No error-severity target remains in the collected evidence.')
    return lines

def _render_report(payload:dict[str,Any],endpoints:list[dict[str,str]])->str:
    version=payload['mreader_version']; coverage=payload['api_coverage']; pytest_summary=payload['pytest']
    lines=[f'# MReader diagnostic report — {version}','',f"**Overall: {payload['overall']}**",f"Generated: {payload['generated_at_utc']}",'']
    if coverage.get('declared_routes') is not None:
        classes=', '.join(f'{k}={v}' for k,v in sorted(coverage['classes'].items()))
        lines += [f"API route manifest: **{coverage['declared_routes']} classified source routes** ({classes})",'']
    if pytest_summary:
        sm=pytest_summary.get('summary',{})
        lines += [f"API/functionality pytest: **{sm.get('passed',0)} passed / {sm.get('failed',0)} failed / {sm.get('skipped',0)} skipped**",'']
    lines += _test_layer_lines(payload.get('test_layers') or {})
    lines += _cascade_lines(payload.get('cascade_analysis') or [])
    lines += _actor_lines(payload['actor_journeys'])
    lines += _browser_lines(payload['browser_journeys'])
    lines += [f'Observed HTTP exchanges: **{len(endpoints)}**','']
    lines += _stage_lines(payload['stages'])
    lines += _issue_lines(payload['issues'],payload['working'],payload['next_diagnostic_target'])
    lines += ['','## Evidence bundle','','Upload `REPORT_BUNDLE.zip` for diagnosis. It contains sanitized HTTP exchanges, stage logs, Kubernetes pod current/previous logs, events, Docker/Compose state, PostgreSQL/RabbitMQ/Valkey/NAS snapshots, endpoint results, and machine-readable findings.','']
    return '\n'.join(lines)

def build_report(run_dir:Path,version:str='unknown')->dict[str,Any]:
    run_dir=run_dir.resolve(); run_dir.mkdir(parents=True,exist_ok=True)
    stages=_read_stages(run_dir/'stages.tsv')
    pytest_summary=_read_json(run_dir/'pytest'/'summary.json',None)
    test_layers=_test_layer_summaries(run_dir,pytest_summary)
    cascade_analysis=_cascade_analysis(test_layers)
    issues=_read_json(run_dir/'issues.json',[])
    endpoints=_read_endpoints(run_dir/'endpoint-results.tsv')
    coverage=_coverage_summary()
    actor_journeys=_actor_journey_summary(pytest_summary)
    actor_journeys['actions']=_read_journey_actions(run_dir/'pytest'/'journey_actions.jsonl')
    browser_journeys=_browser_journey_summary(run_dir/'browser'/'playwright-reader.json')
    overall='FAIL' if any(i.get('severity')=='error' for i in issues) else ('WARN' if any(i.get('severity')=='warning' for i in issues) else 'PASS')
    working=[row.get('name','') for row in stages if row.get('status')=='PASS']
    next_target=_next_target(issues)
    status_counts={}
    for row in endpoints:
        status=str(row.get('status') or 'unknown'); status_counts[status]=status_counts.get(status,0)+1
    payload={'format_version':3,'mreader_version':version,'generated_at_utc':datetime.now(timezone.utc).isoformat(),'overall':overall,'stages':stages,'pytest':pytest_summary,'test_layers':test_layers,'cascade_analysis':cascade_analysis,'actor_journeys':actor_journeys,'browser_journeys':browser_journeys,'api_coverage':coverage,'endpoint_observations':{'total':len(endpoints),'status_counts':status_counts,'file':'endpoint-results.tsv'},'working':working,'issues':issues,'next_diagnostic_target':next_target,'files':{'human_report':'REPORT.md','machine_report':'REPORT.json','issues':'issues.json','endpoint_results':'endpoint-results.tsv','stage_table':'stages.tsv','snapshot_dir':'snapshot','pytest_dir':'pytest','logs_dir':'logs','bundle':'REPORT_BUNDLE.zip'}}
    (run_dir/'REPORT.json').write_text(json.dumps(payload,indent=2,default=str),encoding='utf-8')
    (run_dir/'REPORT.md').write_text(_render_report(payload,endpoints),encoding='utf-8')
    bundle=_bundle(run_dir); payload['bundle_path']=str(bundle); return payload

def main(argv:list[str])->int:
    if len(argv)<2 or len(argv)>3: print('usage: report_builder.py RUN_DIR [VERSION]',file=sys.stderr); return 2
    result=build_report(Path(argv[1]),argv[2] if len(argv)==3 else 'unknown'); print(f"OVERALL={result['overall']}"); print(f"REPORT={Path(argv[1]).resolve()/'REPORT.md'}"); print(f"JSON={Path(argv[1]).resolve()/'REPORT.json'}"); print(f"BUNDLE={Path(argv[1]).resolve()/'REPORT_BUNDLE.zip'}"); return 0
if __name__=='__main__': raise SystemExit(main(sys.argv))
