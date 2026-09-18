import argparse, json, re, hashlib, subprocess
from pathlib import Path
import networkx as nx
from networkx.readwrite import json_graph
def _args():
    repo_default = Path(__file__).resolve().parents[2]
    ap = argparse.ArgumentParser(description="Build MReader issue-oriented development graph")
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
code_graph = OUT / "code-graph.json"
if not code_graph.exists():
    code_graph = OUT / "graph.json"
full=json.load(open(code_graph))
Gfull=json_graph.node_link_graph(full,edges='links')
G=nx.DiGraph()

def addn(i,label,kind='concept',sf='-',sl='L1',**kw):
    if i not in G: G.add_node(i,label=label,kind=kind,file_type=kind,source_file=sf,source_location=sl,community=0,**kw)

def adde(s,t,rel='references',sf='-',line=1,conf='EXTRACTED',**kw):
    if s in G and t in G: G.add_edge(s,t,relation=rel,confidence=conf,source_file=sf,source_location=f'L{line}',weight=1.0,_src=s,_tgt=t,**kw)

# all file + component nodes, import relations only
for i,d in Gfull.nodes(data=True):
    if str(i).startswith('file:') or str(i).startswith('component:'):
        G.add_node(i,**d)
for s,t,d in Gfull.edges(data=True):
    if s in G and t in G and d.get('relation') in {'imports','imports_from','dynamic_import','re_exports','contains'}:
        G.add_edge(s,t,**d)

# conceptual clients and infrastructure
concepts={
 'client:user-web':'User Web','client:admin-web':'Admin Web','client:android-app':'Android App',
 'infra:postgresql':'PostgreSQL','infra:rabbitmq':'RabbitMQ','infra:critical-valkey':'Critical Valkey','infra:cache-valkey':'Cache Valkey','infra:seaweedfs':'NAS SeaweedFS','infra:staging-pvc':'Scraper staging PVC','infra:image-edge':'Image Edge / nginx',
 'storage:web-reading-indexeddb':'IndexedDB: mreader-reading-v1','storage:web-protected-indexeddb':'IndexedDB: mreader-protected-assets-v1','storage:web-cache-storage':'Browser CacheStorage protected assets','storage:android-protected-assets':'Android protected encoded asset store','storage:android-reading-journal':'Android reading journal','storage:host-db-protection':'Host ~/.mreader/database-protection',
 'capability:database-protection':'Database Protection capability'
}
for i,l in concepts.items(): addn(i,l,i.split(':')[0])

# map logical owners to real service components
owner_comp={
 'catalog':'component:service:catalog_go','scraper':'component:service:scraper_service','social':'component:service:social_ts','media':'component:service:image_service','auth':'component:service:auth_service','reader':'component:service:reader_go','notifications':'component:service:notification_worker','progress':'component:service:progress_go','realtime':'component:service:realtime_go','database-protection':'capability:database-protection'}
consumer_comp={'web':'client:user-web','admin-web':'client:admin-web','android':'client:android-app'}
# connect logical clients to physical source components
adde('client:user-web','component:client:web','uses','frontend/src/App.tsx',1,'INFERRED')
adde('client:admin-web','component:client:web','uses','frontend/src/App.tsx',1,'INFERRED')
adde('client:android-app','component:client:android','uses','android/app/src/main/java/com/mreader/android/ui/MReaderApp.kt',1,'INFERRED')
# database-protection current implementation/facade
adde('capability:database-protection','component:service:scraper_service','uses','services/scraper_service/app/database_facade.py',1,'INFERRED')

routes=json.load(open(ROOT/'contracts/ownership/routes.v1.json'))['routes']
for idx,r in enumerate(routes,1):
    rid='route:'+r['method']+' '+r['path']
    addn(rid,rid,'route','contracts/ownership/routes.v1.json',f'L{idx}',method=r['method'],path=r['path'],plane=r.get('access_plane'),owner=r.get('owner'))
    oc=owner_comp.get(r.get('owner'))
    if oc in G: adde(rid,oc,'uses','contracts/ownership/routes.v1.json',idx)
    # handler file
    h=r.get('handler','')
    hp=h.split(':',1)[0]
    fid='file:'+hp
    if fid in G: adde(rid,fid,'references','contracts/ownership/routes.v1.json',idx)
    for c in r.get('consumers',[]):
        cc=consumer_comp.get(c.get('kind'))
        if cc in G: adde(cc,rid,'uses','contracts/ownership/routes.v1.json',idx)
        elif c.get('kind')=='service':
            name=c.get('name','').replace('-','_')
            # fuzzy map service names
            matches=[n for n in G if str(n).startswith('component:service:') and (name in str(n) or str(n).split(':')[-1].replace('_','-')==c.get('name'))]
            if matches: adde(matches[0],rid,'uses','contracts/ownership/routes.v1.json',idx)
    for dep in r.get('dependencies',[]):
        k=dep.get('kind')
        target={'postgres':'infra:postgresql','seaweedfs':'infra:seaweedfs','filesystem':'infra:staging-pvc','cache':'infra:cache-valkey'}.get(k)
        if target: adde(oc if oc in G else rid,target,'uses','contracts/ownership/routes.v1.json',idx)
    for w in r.get('permitted_writes',[]):
        res=w.get('resource')
        if res:
            tid='table:'+res
            addn(tid,'table:'+res,'table','contracts/ownership/routes.v1.json',f'L{idx}')
            adde(rid,tid,'uses','contracts/ownership/routes.v1.json',idx)
    for e in r.get('events',[]):
        en=e.get('name')
        if en:
            eid='event:'+en; addn(eid,eid,'event','contracts/ownership/routes.v1.json',f'L{idx}')
            if e.get('direction')=='publish': adde(rid,eid,'uses','contracts/ownership/routes.v1.json',idx)
            else: adde(eid,rid,'uses','contracts/ownership/routes.v1.json',idx)
    for ev in r.get('evidence',[]):
        ef='file:'+ev
        if ef in G: adde(ef,rid,'references','contracts/ownership/routes.v1.json',idx)

# event pipeline explicit from event contracts and services
for p in (ROOT/'contracts/events').rglob('*.schema.json'):
    name=p.name.replace('.schema.json',''); eid='event:'+name
    addn(eid,eid,'event',p.relative_to(ROOT).as_posix(),'L1')
# core async paths
for s,t in [
 ('component:service:catalog_go','component:service:outbox_relay'),
 ('component:service:outbox_relay','infra:rabbitmq'),
 ('infra:rabbitmq','component:service:notification_worker'),
 ('component:service:notification_worker','infra:rabbitmq'),
 ('infra:rabbitmq','component:service:realtime_go')]:
    if s in G and t in G: adde(s,t,'uses','docs/development-reference/MREADER-DEVELOPMENT-REFERENCE.md',1,'INFERRED')

# Publication path grounded by current boundary files
for s,t,sf in [
 ('component:service:scraper_service','infra:staging-pvc','services/scraper_service/app/staging_store.py'),
 ('component:service:scraper_service','component:service:image_service','services/scraper_service/app/publication_bridge.py'),
 ('component:service:image_service','infra:seaweedfs','services/image_service/app/media_operations.py'),
 ('component:service:image_service','component:service:catalog_go','services/image_service/app/catalog_publication.py'),
 ('component:service:catalog_go','infra:postgresql','services/catalog_go/internal/store/publication.go')]:
    if s in G and t in G: adde(s,t,'uses',sf,1,'INFERRED')

# Reading client durability/cache paths
links=[
 ('file:frontend/src/reading/indexedDB.ts','storage:web-reading-indexeddb','frontend/src/reading/indexedDB.ts'),
 ('file:frontend/src/reading/browser.ts','storage:web-reading-indexeddb','frontend/src/reading/browser.ts'),
 ('file:frontend/src/reader/protectedAssetCache.ts','storage:web-protected-indexeddb','frontend/src/reader/protectedAssetCache.ts'),
 ('file:frontend/src/reader/protectedAssetCache.ts','storage:web-cache-storage','frontend/src/reader/protectedAssetCache.ts'),
 ('file:android/app/src/main/java/com/mreader/android/core/repository/ProtectedAssetStore.kt','storage:android-protected-assets','android/app/src/main/java/com/mreader/android/core/repository/ProtectedAssetStore.kt'),
 ('file:android/app/src/main/java/com/mreader/android/core/repository/ReadingJournal.kt','storage:android-reading-journal','android/app/src/main/java/com/mreader/android/core/repository/ReadingJournal.kt'),
 ('component:service:progress_go','infra:postgresql','services/progress_go/internal/store/store.go'),
 ('component:service:reader_go','infra:postgresql','services/reader_go/internal/store/store.go')]
for s,t,sf in links:
    if s in G and t in G: adde(s,t,'uses',sf,1,'INFERRED')
# browser file client flow
for ff in ['file:frontend/src/pages/Reader.tsx','file:frontend/src/reading/repository.ts','file:frontend/src/reading/transport.ts']:
    if ff in G: adde('client:user-web',ff,'uses',ff.split(':',1)[1],1,'INFERRED')
for ff in ['file:android/app/src/main/java/com/mreader/android/ui/screens/ReaderScreen.kt','file:android/app/src/main/java/com/mreader/android/core/repository/ReadingRepository.kt','file:android/app/src/main/java/com/mreader/android/core/network/MReaderApiAdapter.kt']:
    if ff in G: adde('client:android-app',ff,'uses',ff.split(':',1)[1],1,'INFERRED')

# deployment / infra associations based on manifest text mentions
service_tokens={
 'auth':'component:service:auth_service','catalog':'component:service:catalog_go','reader':'component:service:reader_go','progress':'component:service:progress_go','social':'component:service:social_ts','realtime':'component:service:realtime_go','scraper':'component:service:scraper_service','image-service':'component:service:image_service','notification':'component:service:notification_worker','outbox':'component:service:outbox_relay'}
for rp in ['deploy/docker-desktop-hybrid/user-apps.yaml','deploy/docker-desktop-hybrid/admin-apps.yaml','deploy/compose/docker-compose.hybrid-stateful.yml']:
    fid='file:'+rp
    if fid not in G: continue
    txt=(ROOT/rp).read_text(errors='ignore').lower()
    for tok,cid in service_tokens.items():
        if tok in txt and cid in G: adde(fid,cid,'references',rp,1,'INFERRED')
    for tok,target in [('postgres','infra:postgresql'),('rabbitmq','infra:rabbitmq'),('valkey','infra:cache-valkey'),('seaweed','infra:seaweedfs'),('image','infra:image-edge')]:
        if tok in txt: adde(fid,target,'references',rp,1,'INFERRED')

# diagnostics linkage
for rp in ['scripts/diagnostics/report_builder.py','scripts/diagnostics/runtime-snapshot.sh','tests/diagnostics/runner.py','diagnose-mreader.sh']:
    fid='file:'+rp
    if fid in G:
        for target in ['infra:postgresql','infra:rabbitmq','infra:cache-valkey','infra:seaweedfs','component:deployment:kubernetes','component:deployment:compose']:
            if target in G: adde(fid,target,'references',rp,1,'INFERRED')

# host DB protection
for rp in ['scripts/backup/backup-agent.sh','scripts/backup/postgres-backup.sh','scripts/backup/postgres-restore.sh','scripts/recovery/catalog-restore.sh','services/scraper_service/app/database_facade.py']:
    fid='file:'+rp
    if fid in G: adde(fid,'storage:host-db-protection','uses',rp,1,'INFERRED')

# keep graph metadata
G.graph={'name':'MReader RC4.85 issue-oriented development graph','source_checkpoint':CHECKPOINT,'basis':'route ownership manifest + source imports + storage/boundary evidence','native_graphify_ast':'blocked: tree-sitter unavailable'}
data=json_graph.node_link_data(G,edges='links')
for e in data['links']: e.setdefault('_src',e['source']); e.setdefault('_tgt',e['target'])
p=OUT/'development-graph.json'; p.write_text(json.dumps(data,indent=2),encoding='utf-8')
meta={'source_checkpoint':CHECKPOINT,'nodes':G.number_of_nodes(),'edges':G.number_of_edges(),'routes':len(routes),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
(OUT/'DEVELOPMENT-GRAPH-METADATA.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
print(meta)
