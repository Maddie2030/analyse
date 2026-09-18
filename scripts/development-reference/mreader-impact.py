#!/usr/bin/env python3
from __future__ import annotations
import argparse, os, re, shlex, subprocess, sys
from pathlib import Path

STOP={"the","a","an","and","or","to","of","in","on","for","with","not","wrong","issue","problem","fails","failed","failure","is","are","from","into"}

def toks(s:str):
    return {t for t in re.findall(r"[a-z0-9_./-]+", s.lower()) if len(t)>1 and t not in STOP}

def rows(md:Path):
    out=[]
    for line in md.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.startswith("|---") or "Symptom / capability" in line:
            continue
        parts=[p.strip() for p in line.strip().strip("|").split("|")]
        if len(parts)!=4: continue
        symptom,start,follow,verify=parts
        blob=" ".join(parts).replace("`","")
        out.append({"symptom":symptom,"start":start,"follow":follow,"verify":verify,"blob":blob,"tokens":toks(blob)})
    return out

def score(q,row):
    qt=toks(q)
    if not qt: return 0
    overlap=qt & row["tokens"]
    s=sum(3 if t in toks(row["symptom"]) else 1 for t in overlap)
    phrase=q.lower().strip()
    if phrase and phrase in row["blob"].lower(): s+=10
    return s

def graph_query(issue, graph, budget=2400):
    cmd=["graphify","query",issue,"--graph",str(graph),"--budget",str(budget)]
    return cmd

def main():
    repo=Path(__file__).resolve().parents[2]
    ap=argparse.ArgumentParser(description="MReader issue -> likely change surface lookup")
    ap.add_argument("issue", nargs="+", help="issue/symptom words")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--reference-dir", default=os.environ.get("MREADER_REFERENCE_DIR", str(repo/"development-reference")))
    ap.add_argument("--graph", default=None)
    ap.add_argument("--run-graphify", action="store_true", help="also execute a Graphify query when available")
    args=ap.parse_args()
    issue=" ".join(args.issue)
    reference_dir=Path(args.reference_dir)
    catalog_path = reference_dir / "ISSUE-TO-CHANGE-INDEX.md"
    if not catalog_path.exists():
        catalog_path = repo / "docs" / "development-reference" / "ISSUE-TO-CHANGE-INDEX.md"
    catalog=rows(catalog_path)
    ranked=sorted(((score(issue,r),r) for r in catalog), key=lambda x:(-x[0],x[1]["symptom"]))
    ranked=[x for x in ranked if x[0]>0][:max(1,args.top)]
    print(f"Issue: {issue}\n")
    if not ranked:
        print("No direct domain match. Start with Graphify query and route ownership manifest.")
    for i,(s,r) in enumerate(ranked,1):
        print(f"[{i}] {r['symptom']}  (match={s})")
        print(f"    Start:  {r['start']}")
        print(f"    Follow: {r['follow']}")
        print(f"    Verify: {r['verify']}\n")
    graph=Path(args.graph) if args.graph else reference_dir / "graphify-out" / "development-graph.json"
    print("Graphify next step:")
    print("  "+" ".join(shlex.quote(x) for x in graph_query(issue,graph)))
    print("Then run `graphify explain <candidate>` and `graphify affected <candidate> --depth 3` before editing.")
    if args.run_graphify:
        if not graph.exists():
            print(f"\nGraph not found: {graph}", file=sys.stderr); return 2
        try:
            p=subprocess.run(graph_query(issue,graph), check=False)
            return p.returncode
        except FileNotFoundError:
            print("\ngraphify is not installed/on PATH; printed commands remain usable after Drushti restore.", file=sys.stderr)
            return 127
    return 0
if __name__=="__main__": raise SystemExit(main())
