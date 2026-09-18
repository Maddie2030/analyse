from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, NamedTuple, Sequence

class StageResult(NamedTuple):
    name: str
    status: str
    exit_code: int
    duration_seconds: float
    log: str

def _ensure_stage_table(run_dir: Path) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path=run_dir/'stages.tsv'
    if not path.exists(): path.write_text('name\tstatus\texit_code\tduration_seconds\tlog\n',encoding='utf-8')
    return path

def _append_stage(run_dir: Path, result: StageResult) -> None:
    with _ensure_stage_table(run_dir).open('a',encoding='utf-8',newline='') as handle:
        csv.writer(handle,delimiter='\t',lineterminator='\n').writerow([result.name,result.status,result.exit_code,f'{result.duration_seconds:.3f}',result.log])

def run_stage(run_dir: Path, name: str, command: Sequence[str], env: dict[str,str]|None=None, timeout_seconds: float|None=None) -> StageResult:
    logs=run_dir/'logs'; logs.mkdir(parents=True,exist_ok=True); log_rel=f'logs/{name}.log'; log_path=run_dir/log_rel
    started=time.monotonic(); exit_code=0
    with log_path.open('w',encoding='utf-8') as handle:
        try:
            proc=subprocess.run(list(command),stdout=handle,stderr=subprocess.STDOUT,env=env,text=True,check=False,timeout=timeout_seconds)
            exit_code=proc.returncode
        except subprocess.TimeoutExpired:
            exit_code=124; handle.write(f'\nDiagnostic stage timed out after {timeout_seconds} seconds.\n')
    result=StageResult(name,'PASS' if exit_code==0 else 'FAIL',exit_code,time.monotonic()-started,log_rel); _append_stage(run_dir,result); return result

def run_stages(run_dir: Path, stages: Iterable[tuple[str,Sequence[str]]], env: dict[str,str]|None=None, timeout_seconds: float|None=None) -> list[StageResult]:
    return [run_stage(run_dir,name,command,env=env,timeout_seconds=timeout_seconds) for name,command in stages]

def mark_container_tests_done(run_dir: Path) -> None:
    run_dir.mkdir(parents=True,exist_ok=True); (run_dir/'.container-tests-done').touch()

def wait_for_host_capture(run_dir: Path, *, timeout_seconds: float=600.0, poll_seconds: float=0.5) -> bool:
    deadline=time.monotonic()+timeout_seconds; sentinel=run_dir/'.host-post-capture-done'
    while time.monotonic()<deadline:
        if sentinel.exists(): return True
        time.sleep(poll_seconds)
    return sentinel.exists()

def _commands(mode: str, external: bool) -> list[tuple[str,list[str]]]:
    quick_targets=[
        '/tests/test_01_health_gateway.py','/tests/test_02_auth_registration.py','/tests/test_03_auth_session_profile.py','/tests/test_04_catalog_reads.py',
        '/tests/test_06_reader_manifest_history.py','/tests/test_07_reader_images_tokens.py','/tests/test_08_progress.py','/tests/test_13_media.py',
        '/tests/test_16_lifecycle_integrity.py','/tests/test_17_smart_library.py','/tests/test_23_endpoint_contract_matrix.py',
        '/tests/test_28_user_actor_journeys.py','/tests/test_29_admin_actor_journeys.py',
    ]
    external_targets=[
        '/tests/test_14_scraper_existing_batch.py','/tests/test_15_scraper_new_series.py','/tests/test_30_external_actor_journeys.py',
    ]
    targets=['/tests'] if mode=='full' else quick_targets + (external_targets if external else [])
    marker_args=[] if external else ['-m','not external']
    return [
        ('api-route-audit',[sys.executable,'-u','/repo/scripts/tests/api-route-audit.py']),
        ('pytest-collect',[sys.executable,'-u','-m','pytest','--collect-only','-q',*marker_args,*targets]),
        ('pytest-api',[sys.executable,'-u','-m','pytest','-vv','-ra','--disable-warnings','--maxfail=0',*marker_args,*targets]),
    ]

def _core_api_command(command:list[str])->list[str]:
    """Return the core pytest command without permission/boundary/external cases.

    The command starts with ``python -m pytest``.  Do not confuse Python's
    ``-m`` module switch with pytest's later ``-m`` marker switch; doing so
    replaces the literal ``pytest`` module name and silently prevents the core
    functional suite from executing.
    """
    result=list(command)
    marker_index=next(
        (index for index in range(4, len(result)) if result[index] == '-m'),
        None,
    )
    expression='not external and not permission and not boundary'
    if marker_index is None:
        # Insert immediately after pytest's fixed CLI options and before the
        # first target.  All current targets are /tests paths.
        target_index=next(
            (index for index, value in enumerate(result) if str(value).startswith('/tests')),
            len(result),
        )
        result[target_index:target_index]=['-m', expression]
    else:
        result[marker_index+1]=expression
    return result

def _with_junit(command:list[str], path:str)->list[str]:
    result=list(command)
    target_index=next(
        (index for index, value in enumerate(result) if str(value).startswith('/tests')),
        len(result),
    )
    result.insert(target_index, f'--junitxml={path}')
    return result

def _diagnostic_commands(mode:str,external:bool)->list[tuple[str,list[str]]]:
    core=_commands(mode,False)
    commands=[core[0]]
    commands.extend([
        ('pytest-permissions',['/usr/bin/env','PYTEST_RESULTS_DIR=/results/pytest/permissions',sys.executable,'-u','-m','pytest','-vv','-ra','--disable-warnings','--maxfail=0','--junitxml=/results/pytest/permissions/junit.xml','/tests/test_31_postgres_permission_matrix.py']),
        ('pytest-boundary',['/usr/bin/env','PYTEST_RESULTS_DIR=/results/pytest/boundary',sys.executable,'-u','-m','pytest','-vv','-ra','--disable-warnings','--maxfail=0','--junitxml=/results/pytest/boundary/junit.xml','/tests/test_32_gateway_boundary_matrix.py']),
        core[1],
        (core[2][0],_with_junit(_core_api_command(core[2][1]),'/results/pytest/junit-api.xml')),
    ])
    if external:
        external_targets=['/tests'] if mode=='full' else [
            '/tests/test_14_scraper_existing_batch.py','/tests/test_15_scraper_new_series.py','/tests/test_30_external_actor_journeys.py',
        ]
        commands.append(('pytest-external',['/usr/bin/env','PYTEST_RESULTS_DIR=/results/pytest/external',sys.executable,'-u','-m','pytest','-vv','-ra','--disable-warnings','--maxfail=0','--junitxml=/results/pytest/external/junit.xml','-m','external',*external_targets]))
    return commands

def main() -> int:
    run_dir=Path(os.environ.get('MREADER_DIAGNOSTICS_RESULTS_DIR','/results'))
    mode=os.environ.get('MREADER_DIAGNOSTICS_MODE','full')
    external=os.environ.get('MREADER_DIAGNOSTICS_EXTERNAL','false').lower() in {'1','true','yes','on'}
    pytest_results=run_dir/'pytest'; pytest_results.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy(); env['PYTEST_RESULTS_DIR']=str(pytest_results); env.setdefault('PYTEST_RUN_ID',os.environ.get('MREADER_DIAGNOSTICS_RUN_ID','diagnostics')); env['RUN_EXTERNAL_SCRAPER_TESTS']='true' if external else 'false'
    stage_timeout=float(os.environ.get('MREADER_DIAGNOSTICS_STAGE_TIMEOUT_SECONDS','1800'))
    run_stages(run_dir,_diagnostic_commands(mode,external),env=env,timeout_seconds=stage_timeout)
    mark_container_tests_done(run_dir)
    timeout=float(os.environ.get('MREADER_DIAGNOSTICS_HOST_CAPTURE_TIMEOUT','600'))
    if not wait_for_host_capture(run_dir,timeout_seconds=timeout):
        logs=run_dir/'logs'; logs.mkdir(parents=True,exist_ok=True); (logs/'host-post-capture.log').write_text('Timed out waiting for host runtime evidence capture.\n',encoding='utf-8')
        _append_stage(run_dir,StageResult('host-post-capture','FAIL',124,timeout,'logs/host-post-capture.log'))
    repo_root=Path('/repo')
    analysis=run_stage(run_dir,'report-analysis',[sys.executable,'-u',str(repo_root/'scripts'/'diagnostics'/'analyze_report.py'),str(run_dir)],env=env,timeout_seconds=300)
    report=run_stage(run_dir,'report-build',[sys.executable,'-u',str(repo_root/'scripts'/'diagnostics'/'report_builder.py'),str(run_dir),os.environ.get('MREADER_VERSION','unknown')],env=env,timeout_seconds=300)
    if analysis.exit_code != 0 or report.exit_code != 0: return 1
    try: payload=json.loads((run_dir/'REPORT.json').read_text(encoding='utf-8'))
    except Exception: return 1
    return 1 if payload.get('overall')=='FAIL' else 0

if __name__=='__main__': raise SystemExit(main())
