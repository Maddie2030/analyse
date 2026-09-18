from __future__ import annotations
import argparse, ast, json, os, re, hashlib, subprocess, sys
from pathlib import Path
import networkx as nx
from networkx.readwrite import json_graph

def _args():
    repo_default = Path(__file__).resolve().parents[2]
    ap = argparse.ArgumentParser(description="Build deterministic MReader code graph for Graphify")
    ap.add_argument("--root", type=Path, default=repo_default)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--checkpoint", default=None)
    return ap.parse_args()

ARGS = _args()
ROOT = ARGS.root.resolve()
OUT = (ARGS.out or (ROOT / "graphify-out")).resolve()
OUT.mkdir(parents=True, exist_ok=True)
if ARGS.checkpoint:
    CHECKPOINT = ARGS.checkpoint
else:
    try:
        CHECKPOINT = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        CHECKPOINT = "UNKNOWN"

EXTS={'.py','.go','.ts','.tsx','.js','.jsx','.mjs','.kt','.kts','.sh','.sql','.yaml','.yml','.json','.toml','.conf','.alloy','.xml','.md'}
INCLUDE_TOP={'frontend','android','services','contracts','db','deploy','scripts','tests','shared','ops'}
SKIP_PARTS={'node_modules','build','dist','.gradle','__pycache__','.git','graphify-out','package-evidence','reference'}

def rel(p:Path)->str: return p.relative_to(ROOT).as_posix()
def nid(kind,key): return f'{kind}:{key}'

def component_for(path:str):
    parts=path.split('/')
    if path.startswith('frontend/'):
        return 'client:web'
    if path.startswith('android/'):
        return 'client:android'
    if path.startswith('services/') and len(parts)>1:
        return f'service:{parts[1]}'
    if path.startswith('contracts/') and len(parts)>1:
        return f'contract:{parts[1]}'
    if path.startswith('db/'):
        return 'persistence:postgresql'
    if path.startswith('deploy/docker-desktop-hybrid/'):
        return 'deployment:kubernetes'
    if path.startswith('deploy/compose/'):
        return 'deployment:compose'
    if path.startswith('deploy/'):
        return 'deployment:other'
    if path.startswith('scripts/diagnostics/'):
        return 'tooling:diagnostics'
    if path.startswith('scripts/'):
        return 'tooling:scripts'
    if path.startswith('tests/') and len(parts)>1:
        return f'tests:{parts[1]}'
    if path.startswith('ops/') and len(parts)>1:
        return f'ops:{parts[1]}'
    if path.startswith('shared/'):
        return 'shared:common'
    return 'repo:other'

def add_node(G, id_, label, file_type='code', source_file='-', source_location='L1', **attrs):
    if id_ not in G:
        G.add_node(id_, label=label, file_type=file_type, source_file=source_file, source_location=source_location, **attrs)
    else:
        G.nodes[id_].update({k:v for k,v in attrs.items() if v is not None})

def add_edge(G,s,t,relation='references',source_file='-',line=1,confidence='EXTRACTED',weight=1.0, **attrs):
    if s not in G or t not in G: return
    key=(s,t,relation,source_file,line)
    G.add_edge(s,t,relation=relation,confidence=confidence,source_file=source_file,source_location=f'L{line}',weight=weight,_src=s,_tgt=t,**attrs)

files=[]
for top in sorted(INCLUDE_TOP):
    base=ROOT/top
    if not base.exists(): continue
    for p in base.rglob('*'):
        if not p.is_file() or p.suffix.lower() not in EXTS: continue
        if any(part in SKIP_PARTS for part in p.parts): continue
        files.append(p)
files=sorted(files,key=lambda p:rel(p))

G=nx.DiGraph()
G.graph.update({
    'name':'MReader RC4.85 development reference graph',
    'source_checkpoint':CHECKPOINT,
    'builder':'deterministic fallback architecture extractor; Graphify AST extractor unavailable because tree-sitter runtime is absent',
    'root':'.',
})

# Component and file nodes
components={}
for p in files:
    rp=rel(p); comp=component_for(rp); components.setdefault(comp,[]).append(rp)
    fid=nid('file',rp)
    add_node(G,fid,rp,'code' if p.suffix.lower() in {'.py','.go','.ts','.tsx','.js','.jsx','.mjs','.kt','.kts','.sh'} else 'artifact',rp,'L1',kind='file',component=comp,language=p.suffix.lower().lstrip('.'))
for comp, fps in components.items():
    cid=nid('component',comp)
    add_node(G,cid,comp,'component',fps[0] if fps else '-', 'L1', kind='component')
    for rp in fps:
        add_edge(G,cid,nid('file',rp),'contains',rp,1)

# Resolve indexes
path_to_id={rel(p):nid('file',rel(p)) for p in files}
path_set=set(path_to_id)
by_stem={}
for rp in path_set:
    by_stem.setdefault(Path(rp).stem,[]).append(rp)

# package maps
py_mod={}
kt_pkg={}
go_modules=[]
for p in files:
    rp=rel(p)
    if p.suffix=='.py':
        parts=list(Path(rp).with_suffix('').parts)
        if parts[-1]=='__init__': parts=parts[:-1]
        py_mod['.'.join(parts)]=rp
    elif p.suffix in {'.kt','.kts'}:
        try: txt=p.read_text(errors='ignore')
        except: continue
        m=re.search(r'^\s*package\s+([\w.]+)',txt,re.M)
        if m: kt_pkg.setdefault(m.group(1)+'.'+p.stem,[]).append(rp)
# go module roots
for gm in ROOT.rglob('go.mod'):
    if any(part in SKIP_PARTS for part in gm.parts): continue
    try: txt=gm.read_text()
    except: continue
    m=re.search(r'^module\s+(\S+)',txt,re.M)
    if m: go_modules.append((m.group(1),gm.parent))

# symbol collection
symbols_by_name={}
file_symbols={}

def register_symbol(rp,name,line,kind):
    sid=nid('symbol',f'{rp}::{name}@{line}')
    add_node(G,sid,name,'code',rp,f'L{line}',kind=kind,qualified=f'{rp}::{name}')
    add_edge(G,nid('file',rp),sid,'contains',rp,line)
    symbols_by_name.setdefault(name,[]).append(sid)
    file_symbols.setdefault(rp,{}).setdefault(name,[]).append(sid)
    return sid

for p in files:
    rp=rel(p); ext=p.suffix.lower()
    if ext not in {'.py','.go','.ts','.tsx','.js','.jsx','.mjs','.kt','.kts'}: continue
    try: txt=p.read_text(errors='ignore')
    except: continue
    if ext=='.py':
        try: tree=ast.parse(txt)
        except SyntaxError: continue
        for node in ast.walk(tree):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                register_symbol(rp,node.name,node.lineno,'function')
            elif isinstance(node,ast.ClassDef):
                register_symbol(rp,node.name,node.lineno,'class')
    elif ext=='.go':
        for m in re.finditer(r'(?m)^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\(',txt):
            register_symbol(rp,m.group(1),txt.count('\n',0,m.start())+1,'function')
        for m in re.finditer(r'(?m)^\s*type\s+([A-Za-z_]\w*)\s+',txt):
            register_symbol(rp,m.group(1),txt.count('\n',0,m.start())+1,'type')
    elif ext in {'.ts','.tsx','.js','.jsx','.mjs'}:
        pats=[(r'(?m)^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(', 'function'),
              (r'(?m)^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)\b','class'),
              (r'(?m)^\s*(?:export\s+)?(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^\n]*\)\s*=>','function')]
        for pat,k in pats:
            for m in re.finditer(pat,txt): register_symbol(rp,m.group(1),txt.count('\n',0,m.start())+1,k)
    elif ext in {'.kt','.kts'}:
        for m in re.finditer(r'(?m)^\s*(?:suspend\s+)?fun\s+([A-Za-z_]\w*)\s*\(',txt):
            register_symbol(rp,m.group(1),txt.count('\n',0,m.start())+1,'function')
        for m in re.finditer(r'(?m)^\s*(?:data\s+|sealed\s+|enum\s+)?class\s+([A-Za-z_]\w*)\b',txt):
            register_symbol(rp,m.group(1),txt.count('\n',0,m.start())+1,'class')

# Import/reference edges helpers
def resolve_rel_import(rp,spec,exts):
    base=(ROOT/rp).parent
    q=(base/spec).resolve()
    cands=[]
    if q.is_file(): cands.append(q)
    for e in exts:
        cands.append(Path(str(q)+e))
    for e in exts:
        cands.append(q/('index'+e))
    for c in cands:
        try: rr=rel(c)
        except: continue
        if rr in path_set: return rr
    return None

def add_concept(prefix,label,rp,line,relation='references',direction='file_to'):
    cid=nid(prefix,label)
    add_node(G,cid,f'{prefix}:{label}',prefix,rp,f'L{line}',kind=prefix)
    fid=nid('file',rp)
    if direction=='to_file': add_edge(G,cid,fid,relation,rp,line)
    else: add_edge(G,fid,cid,relation,rp,line)
    return cid

# DB table definitions from SQL
DB_TABLES={}
for p in files:
    if p.suffix.lower()!='.sql': continue
    rp=rel(p); txt=p.read_text(errors='ignore')
    for m in re.finditer(r'(?is)\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?([a-zA-Z_][\w]*)',txt):
        table=m.group(1); line=txt.count('\n',0,m.start())+1
        tid=add_concept('table',table,rp,line,'references','to_file')
        DB_TABLES[table]=tid

# Main per-file scan
route_re=re.compile(r'(["\'`])(/(?:api|internal|healthz|readyz|metrics)[^"\'`\s]*)\1')
env_patterns=[re.compile(r'(?:os\.getenv|os\.environ\.get|env|getenv)\(\s*["\']([A-Z][A-Z0-9_]{2,})["\']'),
              re.compile(r'process\.env\.([A-Z][A-Z0-9_]{2,})'),
              re.compile(r'\$\{([A-Z][A-Z0-9_]{2,})(?::-[^}]*)?\}')]
interesting_storage={'mreader-reading-v1':'indexeddb','mreader-protected-assets-v1':'indexeddb','caches.open':'cache-storage','SeaweedFS':'seaweedfs','seaweedfs':'seaweedfs','RabbitMQ':'rabbitmq','rabbitmq':'rabbitmq','Valkey':'valkey','Redis':'redis'}

def is_route_definition(line):
    l=line.lower()
    return any(x in l for x in ['@app.','@router.','handlefunc','methods(','route(','get("','post("','put("','delete("','patch("']) and not any(x in l for x in ['fetch(','client.','request(','api.'])

for p in files:
    rp=rel(p); fid=nid('file',rp); ext=p.suffix.lower()
    try: txt=p.read_text(errors='ignore')
    except: continue
    lines=txt.splitlines()
    # language imports
    if ext=='.py':
        try: tree=ast.parse(txt)
        except SyntaxError: tree=None
        if tree:
            for node in ast.walk(tree):
                target=None
                if isinstance(node,ast.ImportFrom):
                    mod=node.module or ''
                    if node.level:
                        # resolve relative package path
                        cur=Path(rp).with_suffix('').parts[:-1]
                        base=list(cur[:max(0,len(cur)-(node.level-1))])
                        modparts=mod.split('.') if mod else []
                        key='.'.join(base+modparts)
                    else: key=mod
                    target=py_mod.get(key) or py_mod.get(key+'.__init__')
                elif isinstance(node,ast.Import):
                    for alias in node.names:
                        target=py_mod.get(alias.name)
                        if target: add_edge(G,fid,nid('file',target),'imports',rp,getattr(node,'lineno',1))
                    continue
                if target: add_edge(G,fid,nid('file',target),'imports_from',rp,getattr(node,'lineno',1))
    elif ext in {'.ts','.tsx','.js','.jsx','.mjs'}:
        for m in re.finditer(r'(?m)(?:import\s+(?:[^\n;]+?\s+from\s+)?|export\s+[^\n;]+?\s+from\s+|require\s*\(|import\s*\()\s*["\']([^"\']+)["\']',txt):
            spec=m.group(1); line=txt.count('\n',0,m.start())+1
            if spec.startswith('.'):
                target=resolve_rel_import(rp,spec,['.ts','.tsx','.js','.jsx','.mjs'])
                if target: add_edge(G,fid,nid('file',target),'imports',rp,line)
    elif ext=='.go':
        # all quoted imports inside import block or single import
        for m in re.finditer(r'(?m)["`]([^"`]+)["`]',txt):
            spec=m.group(1); line=txt.count('\n',0,m.start())+1
            for mod,base in go_modules:
                if spec==mod or spec.startswith(mod+'/'):
                    sub=spec[len(mod):].lstrip('/')
                    d=(base/sub).resolve()
                    for cand in sorted(d.glob('*.go')) if d.exists() else []:
                        rr=rel(cand)
                        if rr in path_set: add_edge(G,fid,nid('file',rr),'imports',rp,line)
                    break
    elif ext in {'.kt','.kts'}:
        for m in re.finditer(r'(?m)^\s*import\s+([\w.]+)',txt):
            spec=m.group(1); line=txt.count('\n',0,m.start())+1
            # exact class file map or longest package prefix + class
            for rr in kt_pkg.get(spec,[]): add_edge(G,fid,nid('file',rr),'imports',rp,line)

    # local unique symbol calls (file-first, global unique second)
    if ext in {'.py','.go','.ts','.tsx','.js','.jsx','.mjs','.kt','.kts'}:
        for m in re.finditer(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\(',txt):
            name=m.group(1)
            if name in {'if','for','while','switch','catch','return','func','fun','function','class','typeof','sizeof'}: continue
            line=txt.count('\n',0,m.start())+1
            cands=file_symbols.get(rp,{}).get(name,[]) or (symbols_by_name.get(name,[]) if len(symbols_by_name.get(name,[]))==1 else [])
            if cands:
                add_edge(G,fid,cands[0],'calls',rp,line,confidence='INFERRED',weight=.7)

    # routes
    for i,line_txt in enumerate(lines,1):
        for m in route_re.finditer(line_txt):
            route=m.group(2)
            # normalize obvious templated query fragments only, preserve path params
            rid=nid('route',route)
            add_node(G,rid,f'route:{route}','route',rp,f'L{i}',kind='route')
            if is_route_definition(line_txt):
                add_edge(G,rid,fid,'references',rp,i,confidence='INFERRED',weight=.8,role='provider')
            else:
                add_edge(G,fid,rid,'references',rp,i,confidence='EXTRACTED',role='consumer')
    # env vars
    for pat in env_patterns:
        for m in pat.finditer(txt):
            line=txt.count('\n',0,m.start())+1
            add_concept('env',m.group(1),rp,line)
    # db tables
    low=txt.lower()
    for table,tid in DB_TABLES.items():
        # skip definition migration edge already exists; add all meaningful references
        for m in re.finditer(r'\b'+re.escape(table)+r'\b',low):
            line=txt.count('\n',0,m.start())+1
            add_edge(G,fid,tid,'references',rp,line)
            if line>1: break
    # storage/brokers
    for token,kind in interesting_storage.items():
        pos=txt.find(token)
        if pos>=0:
            line=txt.count('\n',0,pos)+1
            add_concept('infra',kind,rp,line)

# Event concepts: contract filenames + dotted event-looking strings in event-related files
for p in files:
    rp=rel(p)
    if 'contracts/events/' in rp and p.name.endswith('.schema.json'):
        event=p.name[:-len('.schema.json')]
        eid=add_concept('event',event,rp,1,'references','to_file')
for p in files:
    rp=rel(p)
    try: txt=p.read_text(errors='ignore')
    except: continue
    # only known event labels defined above
    for eid,data in list(G.nodes(data=True)):
        if not str(eid).startswith('event:'): continue
        event=str(eid).split(':',1)[1]
        pos=txt.find(event)
        if pos>=0 and 'contracts/events/' not in rp:
            line=txt.count('\n',0,pos)+1
            add_edge(G,nid('file',rp),eid,'references',rp,line)

# Connect tests to likely prod file based on unique stem/name mentions
prod_files=[rp for rp in path_set if not rp.startswith('tests/') and '/test' not in rp.lower()]
unique_stem={s:v[0] for s,v in by_stem.items() if len(v)==1 and v[0] in prod_files}
for rp in path_set:
    if not (rp.startswith('tests/') or '/test' in rp.lower()): continue
    p=ROOT/rp
    try: txt=p.read_text(errors='ignore')
    except: continue
    for stem,target in unique_stem.items():
        if len(stem)<5: continue
        if re.search(r'\b'+re.escape(stem)+r'\b',txt,re.I):
            add_edge(G,nid('file',rp),nid('file',target),'references',rp,1,confidence='INFERRED',weight=.5,role='test-target')

# Explicit architecture edges grounded in current code map / service boundaries.
# These are marked INFERRED so Graphify output does not confuse them with parser-extracted imports.
def comp_edge(src,tgt,relation='uses',evidence='architecture-boundary'):
    s=nid('component',src); t=nid('component',tgt)
    if s in G and t in G: add_edge(G,s,t,relation,'docs/development-reference/MREADER-DEVELOPMENT-REFERENCE.md',1,confidence='INFERRED',weight=.6,evidence=evidence)
for s,t in [
 ('client:web','service:reader_go'),('client:web','service:progress_go'),('client:web','service:catalog_go'),('client:web','service:auth_service'),('client:web','service:social_ts'),
 ('client:android','service:reader_go'),('client:android','service:progress_go'),('client:android','service:catalog_go'),('client:android','service:auth_service'),('client:android','service:social_ts'),
 ('service:scraper_service','service:image_service'),('service:image_service','service:catalog_go'),('service:catalog_go','service:outbox_relay'),('service:outbox_relay','service:notification_worker'),('service:notification_worker','service:realtime_go'),
 ('service:reader_go','persistence:postgresql'),('service:progress_go','persistence:postgresql'),('service:catalog_go','persistence:postgresql'),('service:social_ts','persistence:postgresql'),('service:scraper_service','persistence:postgresql')]: comp_edge(s,t)

# assign simple communities by component
comp_names=sorted(components)
comp_idx={c:i+1 for i,c in enumerate(comp_names)}
for node,data in G.nodes(data=True):
    c=data.get('component')
    if data.get('kind')=='component': c=data.get('label')
    data['community']=comp_idx.get(c,0)

# Node-link JSON. Preserve directedness.
data=json_graph.node_link_data(G,edges='links')
# Add _src/_tgt (networkx serializer keeps source/target; Graphify samples also carry aliases)
for e in data['links']:
    e.setdefault('_src',e['source']); e.setdefault('_tgt',e['target'])
(OUT/'graph.json').write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
(OUT/'code-graph.json').write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
(OUT/'.graphify_python').write_text(os.environ.get('GRAPHIFY_PYTHON',sys.executable)+'\n')
meta={
 'source_checkpoint':CHECKPOINT,
 'files_indexed':len(files),'nodes':G.number_of_nodes(),'edges':G.number_of_edges(),
 'components':{k:len(v) for k,v in sorted(components.items())},
 'limitations':['Graphify native AST update failed because tree-sitter runtime/parser packages are unavailable in this sandbox.','This deterministic fallback graph uses language-native Python AST plus regex/import/config/contract extraction; inferred edges are tagged INFERRED.'],
 'graph_sha256':hashlib.sha256((OUT/'code-graph.json').read_bytes()).hexdigest(),
}
(OUT/'CODE-GRAPH-METADATA.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
(OUT/'BUILD-METADATA.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
print(json.dumps(meta,indent=2))
