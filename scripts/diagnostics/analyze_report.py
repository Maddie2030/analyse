#!/usr/bin/env python3
from __future__ import annotations
import csv,json,os,re,sys
from pathlib import Path
from typing import Any,Iterable
from urllib.parse import urlsplit
TEXT_LIMIT=20*1024*1024
SENSITIVE_KEY_RE=re.compile(r'(?i)(password|passwd|authorization|cookie|set-cookie|(?:old_|access_|refresh_|chapter_|session_|csrf_)?token|api[_-]?key|secret)')
DSN_RE=re.compile(r'(?i)((?:postgres(?:ql)?(?:\+[^:]+)?|redis|rediss)://[^:\s/@]+:)([^@\s/]+)(@)')
HEADER_RE=re.compile(r'(?im)^((?:authorization|cookie|set-cookie)\s*:\s*)(.+)$')
KV_RE=re.compile(r'(?i)(\b(?:password|passwd|authorization|cookie|(?:old_|access_|refresh_|chapter_|session_|csrf_)?token|api[_-]?key|secret)\b\s*[=:]\s*)([^\s,;]+)')
JSON_RE=re.compile(r'''(?ix)(["'](?:password|passwd|authorization|cookie|set-cookie|(?:old_|access_|refresh_|chapter_|session_|csrf_)?token|api[_-]?key|secret)["']\s*:\s*["'])(.*?)(["'])''')
JWT_RE=re.compile(r'\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}\b')
BEARER_RE=re.compile(r'(?i)(\bBearer\s+)([^\s,;]+)')
PATTERNS=[
 ('error','crashloop','Kubernetes workload is in CrashLoopBackOff',re.compile(r'CrashLoopBackOff',re.I)),
 ('error','oom','Container was terminated by OOMKilled',re.compile(r'(?:Reason:\s*OOMKilled|["\']OOMKilled["\']\s*:\s*true|["\']?reason["\']?\s*[:=]\s*["\']?OOMKilled)',re.I)),
 ('error','probe','Kubernetes readiness/liveness probe failed',re.compile(r'(?:Readiness|Liveness) probe failed',re.I)),
 ('error','python-import','Python import/startup failure with circular import evidence',re.compile(r'ImportError:.*(?:circular import|partially initialized module)',re.I)),
 ('error','python-traceback','Python traceback detected',re.compile(r'Traceback \(most recent call last\):')),
 ('error','go-panic','Go panic/fatal runtime error detected',re.compile(r'(?:^|\n)(?:panic:|fatal error:)',re.I)),
 ('error','postgres-permission','PostgreSQL permission/grant failure detected',re.compile(r'permission denied for (?:relation|table|schema|sequence|function)',re.I)),
 ('error','postgres-auth','PostgreSQL authentication failure detected',re.compile(r'(?:password authentication failed|no pg_hba\.conf entry)',re.I)),
 ('error','postgres-relation','PostgreSQL relation/schema mismatch detected',re.compile(r'''relation ["'][^"']+["'] does not exist''',re.I)),
 ('error','connectivity','Connection refused detected',re.compile(r'(?:connection refused|connect: connection refused)',re.I)),
 ('error','dns','DNS/name-resolution failure detected',re.compile(r'(?:name or service not known|temporary failure in name resolution|no such host)',re.I)),
 ('error','timeout','Timeout detected',re.compile(r'(?:timed out|timeout exceeded|context deadline exceeded)',re.I)),
 ('error','rabbitmq','RabbitMQ/AMQP connectivity failure detected',re.compile(r'(?:AMQP|rabbitmq).*(?:refused|unreachable|closed|failed)',re.I)),
 ('error','valkey','Valkey/Redis connectivity failure detected',re.compile(r'(?:redis|valkey).*(?:refused|unreachable|failed)',re.I)),
]
def _component_from_evidence(evidence:str)->str:
    parts=Path(evidence).parts
    if 'pods' in parts:
        idx=parts.index('pods')
        if len(parts)>idx+3: return parts[idx+3]
    return Path(evidence).stem or 'diagnostics'
def redact_text(text:str,known_secrets:Iterable[str]=())->str:
    result=text
    for secret in known_secrets:
        if secret and len(secret)>=6: result=result.replace(secret,'***')
    result=DSN_RE.sub(r'\1***\3',result); result=HEADER_RE.sub(lambda m:f'{m.group(1)}***',result); result=BEARER_RE.sub(r'\1***',result); result=JSON_RE.sub(lambda m:f'{m.group(1)}***{m.group(3)}',result); result=KV_RE.sub(lambda m:f'{m.group(1)}***',result); result=JWT_RE.sub('***',result); return result
def redact_obj(value:Any,known_secrets:Iterable[str]=())->Any:
    if isinstance(value,str):
        return redact_text(value,known_secrets)
    if isinstance(value,list):
        return [redact_obj(item,known_secrets) for item in value]
    if not isinstance(value,dict):
        return value
    cleaned={}
    for key,item in value.items():
        if SENSITIVE_KEY_RE.search(str(key)):
            cleaned[key]='***'
        else:
            cleaned[key]=redact_obj(item,known_secrets)
    return cleaned
def _ready_running_describe(evidence:str,text:str)->bool:
    return (
        evidence.endswith('/describe.txt')
        and re.search(r'(?m)^\s*Ready:\s+True\s*$',text) is not None
        and re.search(r'(?m)^\s*State:\s+Running\s*$',text) is not None
    )

def _pattern_matches(category:str,pattern:re.Pattern[str],text:str)->bool:
    if category!='rabbitmq':
        return pattern.search(text) is not None
    for line in text.splitlines():
        if '0 servers failed to start' in line.lower():
            continue
        if pattern.search(line):
            return True
    return False

def _severity_for_evidence(severity:str,category:str,evidence:str)->str:
    historical=evidence.endswith('/events.txt') or evidence.endswith('/warning-events.txt')
    if historical and category in {'probe','connectivity','crashloop'}:
        return 'warning'
    return severity

def classify_text(evidence:str,text:str)->list[dict[str,str]]:
    component=_component_from_evidence(evidence); issues=[]
    ready_describe=_ready_running_describe(evidence,text)
    for severity,category,reason,pattern in PATTERNS:
        if category in {'probe','connectivity','crashloop'} and ready_describe:
            continue
        if not _pattern_matches(category,pattern,text):
            continue
        issues.append({
            'severity':_severity_for_evidence(severity,category,evidence),
            'category':category,'component':component,'reason':reason,'evidence':evidence,
        })
    return issues
def _iter_text_files(run_dir:Path):
    for path in run_dir.rglob('*'):
        if not path.is_file() or path.name=='REPORT_BUNDLE.zip' or path.name.startswith('.host-') or path.name.startswith('.container-'): continue
        try:
            if path.stat().st_size>TEXT_LIMIT: continue
            text=path.read_bytes().decode('utf-8')
        except (OSError,UnicodeDecodeError): continue
        yield path,text
def _stage_issues(run_dir:Path)->list[dict[str,str]]:
    path=run_dir/'stages.tsv'; issues=[]
    if not path.exists(): return issues
    with path.open(encoding='utf-8') as handle:
        for row in csv.DictReader(handle,delimiter='\t'):
            if row.get('status')!='FAIL': continue
            stage=row.get('name','unknown'); issues.append({'severity':'error','category':'route-coverage' if stage=='api-route-audit' else 'test-stage','component':stage,'reason':f"Diagnostic stage failed with exit code {row.get('exit_code') or '?'}",'evidence':row.get('log') or 'stages.tsv'})
    return issues
def _collector_issues(run_dir:Path)->list[dict[str,str]]:
    issues=[]; critical=('postgres-','rabbitmq-','valkey-','gateway-','seaweedfs-')
    for path in run_dir.glob('snapshot/*/collector-errors.tsv'):
        phase=path.parent.name
        try:
            with path.open(encoding='utf-8') as handle: rows=list(csv.DictReader(handle,delimiter='\t'))
        except Exception: continue
        for row in rows:
            collector=row.get('collector') or 'unknown'; issues.append({'severity':'error' if collector.startswith(critical) else 'warning','category':'collector','component':collector,'reason':f"{phase} evidence collector failed with exit code {row.get('exit_code') or '?'}: {row.get('message') or ''}",'evidence':path.relative_to(run_dir).as_posix()})
    return issues
def _exchange_layer(source:Path,run_dir:Path)->str:
    relative=source.relative_to(run_dir/'pytest')
    return relative.parts[0] if len(relative.parts)>1 else 'api'

def _sanitize_exchange_file(source:Path,run_dir:Path,known_secrets:Iterable[str])->tuple[list[dict[str,Any]],list[dict[str,str]]]:
    endpoints=[]; issues=[]; sanitized=[]; layer=_exchange_layer(source,run_dir); rel_source=source.relative_to(run_dir).as_posix()
    for line_no,line in enumerate(source.read_text(encoding='utf-8',errors='ignore').splitlines(),1):
        if not line.strip(): continue
        try: payload=redact_obj(json.loads(line),known_secrets)
        except json.JSONDecodeError:
            sanitized.append(redact_text(line,known_secrets)); continue
        sanitized.append(json.dumps(payload,sort_keys=True,default=str))
        status=int(payload.get('status') or 0); raw=str(payload.get('url') or ''); path=urlsplit(raw).path or raw
        endpoint={'layer':layer,'method':str(payload.get('method') or ''),'path':path,'status':status,'duration_ms':payload.get('duration_ms') or '','test_id':str(payload.get('test_id') or '')}; endpoints.append(endpoint)
        if status>=500: issues.append({'severity':'error','category':'http-5xx','component':path or 'http','layer':layer,'reason':f"{endpoint['method']} {path} returned HTTP {status}",'evidence':f'{rel_source}:{line_no}'})
    source.write_text('\n'.join(sanitized)+('\n' if sanitized else ''),encoding='utf-8')
    return endpoints,issues

def _sanitize_http_exchanges(run_dir:Path,known_secrets:Iterable[str]):
    endpoints=[]; issues=[]
    if not (run_dir/'pytest').exists(): return endpoints,issues
    for source in sorted((run_dir/'pytest').rglob('http_exchanges.jsonl')):
        file_endpoints,file_issues=_sanitize_exchange_file(source,run_dir,known_secrets)
        endpoints.extend(file_endpoints); issues.extend(file_issues)
    return endpoints,issues

def _write_endpoint_table(run_dir:Path,endpoints:list[dict[str,Any]])->None:
    with (run_dir/'endpoint-results.tsv').open('w',encoding='utf-8',newline='') as handle:
        w=csv.DictWriter(handle,fieldnames=['layer','method','path','status','duration_ms','test_id'],delimiter='\t',lineterminator='\n'); w.writeheader(); w.writerows(endpoints)
def _dedupe(issues:list[dict[str,str]])->list[dict[str,str]]:
    seen=set(); out=[]
    for item in issues:
        key=(item.get('category',''),item.get('component',''),item.get('reason',''),item.get('evidence',''))
        if key not in seen: seen.add(key); out.append(item)
    rank={'error':0,'warning':1,'info':2}; out.sort(key=lambda x:(rank.get(x.get('severity','info'),3),x.get('category',''),x.get('component',''),x.get('evidence',''))); return out
def analyze_run(run_dir:Path,known_secrets:Iterable[str]=())->dict[str,Any]:
    run_dir=run_dir.resolve(); secrets=[s for s in known_secrets if s]; endpoints,issues=_sanitize_http_exchanges(run_dir,secrets); issues.extend(_stage_issues(run_dir)); issues.extend(_collector_issues(run_dir))
    for path,text in list(_iter_text_files(run_dir)):
        rel=path.relative_to(run_dir).as_posix()
        if rel in {'issues.json','endpoint-results.tsv','REPORT.json','REPORT.md'}: continue
        clean=redact_text(text,secrets)
        if clean!=text: path.write_text(clean,encoding='utf-8')
        issues.extend(classify_text(rel,clean))
    _write_endpoint_table(run_dir,endpoints); issues=_dedupe(issues); (run_dir/'issues.json').write_text(json.dumps(issues,indent=2),encoding='utf-8'); return {'issues':issues,'endpoints':endpoints}
def _known_env_secrets()->list[str]:
    names=('PASSWORD','PASSWD','TOKEN','SECRET','API_KEY','DATABASE_URL'); return [v for k,v in os.environ.items() if v and len(v)>=6 and any(part in k.upper() for part in names)]
def main(argv:list[str])->int:
    if len(argv)!=2: print('usage: analyze_report.py RUN_DIR',file=sys.stderr); return 2
    result=analyze_run(Path(argv[1]),_known_env_secrets()); errors=sum(1 for i in result['issues'] if i.get('severity')=='error'); print(f"diagnostics analysis: endpoints={len(result['endpoints'])} issues={len(result['issues'])} errors={errors}"); return 0
if __name__=='__main__': raise SystemExit(main(sys.argv))
