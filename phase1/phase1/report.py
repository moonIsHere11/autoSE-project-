"""Self-contained interactive HTML report (no network, no libraries): program graph coloured by
subsystem, drill-down unit graph coloured by module cluster with hazard-risk rings, hazard
breakdown, and the migration plan."""
import json

from .agent import heuristic_plan


def build_data(ix, plan=None):
    d = ix.d
    plan = plan or heuristic_plan(ix)
    units = [{"id": u["unit_id"], "p": u["program"], "k": u["kind"], "loc": u["loc"], "risk": u["risk"],
              "c": u.get("cluster"), "un": u["unsupported"], "to": u["performs"],
              "hz": [[h["gap_id"], h["severity"][0], h["line"], h["message"]] for h in sorted(
                  u["hazards"], key=lambda h: -{"high": 3, "medium": 2, "low": 1}[h["severity"]])[:8]]}
             for u in d["units"]]
    progs = [{"id": p["program_id"], "loc": p["loc"], "ss": p.get("subsystem"), "fl": p["flags"],
              "desc": (p["description"] or "")[:90], "file": p["file"], "n": p["unit_count"]} for p in d["programs"]]
    edges = [[a, b, "call"] for a, bs in d["program_call_graph"].items() for b in bs]
    cbs = d["copybook_users"]
    for cb, us in cbs.items():
        if 2 <= len(us) <= max(3, len(progs) // 2):
            edges += [[a, b, "cpy"] for i, a in enumerate(us) for b in us[i + 1:i + 3]]
    hz = {}
    for u in d["units"]:
        for h in u["hazards"]:
            hz.setdefault(h["gap_id"], [0, 0, 0])["hml".index(h["severity"][0])] += 1
    return {"progs": progs, "units": units, "edges": edges, "hz": hz, "ss": d["subsystems"],
            "plan": [u["unit_id"] for u in plan["units"]], "skipped": len(plan["skipped"]),
            "stats": {"programs": len(progs), "units": len(units), "loc": sum(p["loc"] for p in progs),
                      "in_scope": sum(1 for u in d["units"] if not set(u["unsupported"]) & {"file_io", "cics", "sql", "goto", "alter", "redefines"}),
                      "hazards": sum(len(u["hazards"]) for u in d["units"])}}


def render(ix, plan=None):
    return HTML.replace("__DATA__", json.dumps(build_data(ix, plan)).replace("</", "<\\/"))


HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>COBOL Migration Atlas</title><style>
:root{--bg:#0e1117;--panel:#161b22;--line:#2a313c;--tx:#e6edf3;--mute:#8b949e;--hi:#f85149;--md:#d29922;--lo:#3fb950;--acc:#58a6ff}
@media (prefers-color-scheme:light){:root{--bg:#f6f8fa;--panel:#fff;--line:#d0d7de;--tx:#1f2328;--mute:#59636e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.45 system-ui,sans-serif}
header{padding:20px 24px 8px}h1{margin:0;font-size:22px}h1 span{color:var(--acc)}.sub{color:var(--mute);margin-top:2px}
.cards{display:flex;gap:12px;flex-wrap:wrap;padding:8px 24px}.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 16px;min-width:120px}
.card b{display:block;font-size:22px}.card small{color:var(--mute)}
nav{display:flex;gap:4px;padding:8px 24px;border-bottom:1px solid var(--line)}nav button{background:none;border:0;color:var(--mute);padding:8px 14px;border-radius:8px;cursor:pointer;font:inherit}
nav button.on{background:var(--panel);color:var(--tx);border:1px solid var(--line)}
main{padding:16px 24px;display:grid;grid-template-columns:minmax(0,2fr) minmax(280px,1fr);gap:16px}@media(max-width:900px){main{grid-template-columns:1fr}}
.box{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px;min-width:0}.box h3{margin:0 0 8px;font-size:14px}
svg{width:100%;height:520px;display:block;background:transparent}.lbl{font-size:10px;fill:var(--tx);pointer-events:none}
.legend span{display:inline-block;margin:2px 10px 2px 0;color:var(--mute);font-size:12px}.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px;vertical-align:-1px}
table{border-collapse:collapse;width:100%;font-size:12px}td,th{text-align:left;padding:4px 6px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--mute);font-weight:500}
.sev-h{color:var(--hi)}.sev-m{color:var(--md)}.sev-l{color:var(--lo)}.bar{height:14px;display:flex;border-radius:3px;overflow:hidden}
.hide{display:none}select{background:var(--panel);color:var(--tx);border:1px solid var(--line);border-radius:6px;padding:4px}.muted{color:var(--mute)}
code{font-size:12px}.pill{padding:1px 6px;border-radius:9px;border:1px solid var(--line);font-size:11px;color:var(--mute)}
</style></head><body>
<header><h1>COBOL Migration <span>Atlas</span></h1><div class="sub">Static architecture, semantic-hazard and module analysis produced by the Phase 1 agent (no LLM involved)</div></header>
<div class="cards" id="cards"></div>
<nav id="nav"><button data-t="arch" class="on">Architecture</button><button data-t="haz">Semantic hazards</button><button data-t="plan">Migration plan</button></nav>
<main id="arch"><div class="box"><h3 id="gtitle">Programs · colour = subsystem, size = LOC, solid = CALL/XCTL, dashed = shared copybook</h3><svg id="g"></svg><div class="legend" id="legend"></div></div>
<div class="box"><h3 id="ptitle">Click a program</h3><div id="panel" class="muted">Select a node to drill into its units, module clusters and hazards.</div></div></main>
<main id="haz" class="hide"><div class="box"><h3>Hazard sites by kind (red = high, amber = medium, green = low)</h3><div id="hzbars"></div></div>
<div class="box"><h3>Riskiest units</h3><table id="risk"></table></div></main>
<main id="plan" class="hide"><div class="box"><h3>Plan: modules kept together, callees first</h3><div id="planl"></div></div>
<div class="box"><h3>How to read this</h3><p class="muted">Units with file I/O, CICS, SQL, GO TO, ALTER or REDEFINES fall outside the iteration-1 subset and are skipped. Remaining units are ordered bottom-up inside each data-coupled module (label propagation over calls + shared written fields).</p></div></main>
<script>
const D=__DATA__;const $=s=>document.querySelector(s);const PAL=["#58a6ff","#f778ba","#56d364","#e3b341","#bc8cff","#ff7b72","#39c5cf","#ffa657","#a5d6ff","#7ee787"];
const gapName={"G-TRUNCATE":"truncation","G-OVERFLOW":"silent overflow","G-ROUNDING":"ROUNDED","G-SIGN":"sign loss","G-NUMALPHA":"num↔alpha","G-GROUPMOVE":"group MOVE","G-GOTO":"GO TO","G-FALLTHROUGH":"fall-through","G-PACKED":"COMP/COMP-3","G-DIVZERO":"divide by zero"};
const S=D.stats;$("#cards").innerHTML=[["programs",S.programs],["units",S.units],["lines",S.loc.toLocaleString()],["in iteration-1 scope",Math.round(100*S.in_scope/S.units)+"%"],["hazard sites",S.hazards],["planned units",D.plan.length]].map(([k,v])=>`<div class="card"><b>${v}</b><small>${k}</small></div>`).join("");
document.querySelectorAll("nav button").forEach(b=>b.onclick=()=>{document.querySelectorAll("nav button").forEach(x=>x.classList.toggle("on",x==b));["arch","haz","plan"].forEach(t=>$("#"+t).classList.toggle("hide",t!=b.dataset.t))});
const ssIdx={};D.ss.forEach((s,i)=>ssIdx[s.subsystem_id]=i);const col=i=>PAL[(i||0)%PAL.length];
function force(nodes,links,w,h,it=260){nodes.forEach((n,i)=>{n.x=w/2+Math.cos(i*2.4)*w/3*Math.random();n.y=h/2+Math.sin(i*2.4)*h/3*Math.random();n.vx=n.vy=0});
 const idx={};nodes.forEach(n=>idx[n.id]=n);links=links.filter(l=>idx[l[0]]&&idx[l[1]]);
 for(let t=0;t<it;t++){const a=1-t/it;for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){const p=nodes[i],q=nodes[j];let dx=p.x-q.x,dy=p.y-q.y,d2=dx*dx+dy*dy+.1,f=(900/d2)*a;dx*=f;dy*=f;p.vx+=dx;p.vy+=dy;q.vx-=dx;q.vy-=dy}
 links.forEach(l=>{const p=idx[l[0]],q=idx[l[1]];const dx=q.x-p.x,dy=q.y-p.y,d=Math.sqrt(dx*dx+dy*dy)+.1,f=(d-70)*.02*a;p.vx+=dx/d*f;p.vy+=dy/d*f;q.vx-=dx/d*f;q.vy-=dy/d*f});
 nodes.forEach(n=>{n.vx+=(w/2-n.x)*.004;n.vy+=(h/2-n.y)*.004;n.x+=n.vx*.6;n.y+=n.vy*.6;n.vx*=.6;n.vy*=.6;n.x=Math.max(20,Math.min(w-20,n.x));n.y=Math.max(20,Math.min(h-20,n.y))})}
 return links.map(l=>[idx[l[0]],idx[l[1]],l[2]])}
function draw(nodes,links,opt){const w=760,h=520,svg=$("#g");svg.setAttribute("viewBox",`0 0 ${w} ${h}`);const L=force(nodes,links,w,h);
 let s="";L.forEach(([a,b,t])=>s+=`<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="${t=="cpy"?"#6e7681":"#8b949e"}" stroke-opacity="${t=="cpy"?.25:.55}" ${t=="cpy"?'stroke-dasharray="3 3"':""}/>`);
 nodes.forEach(n=>{const r=opt.r(n),ring=opt.ring?opt.ring(n):null;s+=`<g data-id="${n.id}" style="cursor:pointer"><title>${opt.tip(n)}</title>${ring?`<circle cx="${n.x}" cy="${n.y}" r="${r+4}" fill="none" stroke="${ring[0]}" stroke-width="${ring[1]}" opacity=".85"/>`:""}<circle cx="${n.x}" cy="${n.y}" r="${r}" fill="${opt.fill(n)}" fill-opacity="${opt.dim&&opt.dim(n)?.25:.9}"/>${r>9?`<text class="lbl" x="${n.x}" y="${n.y+r+11}" text-anchor="middle">${n.id.split(".").pop().slice(0,14)}</text>`:""}</g>`});
 svg.innerHTML=s;svg.querySelectorAll("g[data-id]").forEach(g=>g.onclick=()=>opt.click(g.dataset.id))}
function progView(){$("#gtitle").textContent="Programs · colour = subsystem, size = LOC, solid = CALL/XCTL, dashed = shared copybook";
 const nodes=D.progs.map(p=>({...p}));draw(nodes,D.edges,{r:n=>5+Math.sqrt(n.loc)/3,fill:n=>col(ssIdx[n.ss]),tip:n=>`${n.id} · ${n.loc} loc · ${n.fl.join(",")||"clean"}\n${n.desc}`,
  ring:n=>n.fl.some(f=>["file_io","cics","sql","goto","alter","redefines"].includes(f))?["#d29922",1.5]:null,click:showProg});
 $("#legend").innerHTML=D.ss.slice(0,8).map((s,i)=>`<span><i style="background:${col(i)}"></i>${s.subsystem_id}: ${s.label}</span>`).join("")+'<span><i style="background:none;border:2px solid #d29922"></i>uses out-of-scope constructs</span>'}
function showProg(pid){const p=D.progs.find(x=>x.id==pid),us=D.units.filter(u=>u.p==pid);$("#ptitle").textContent=pid;
 const cl=[...new Set(us.map(u=>u.c))],ci=c=>cl.indexOf(c);const mx=Math.max(1,...us.map(u=>u.risk));
 $("#gtitle").innerHTML=`${pid} · units · colour = module cluster, ring = hazard risk, faded = out of scope · <a href="#" id="back" style="color:var(--acc)">← all programs</a>`;
 const nodes=us.map(u=>({...u})),links=[];us.forEach(u=>u.to.forEach(t=>links.push([u.id,t,"call"])));
 draw(nodes,links,{r:n=>5+Math.sqrt(n.loc)*1.2,fill:n=>col(ci(n.c)),dim:n=>n.un.some(x=>["file_io","cics","sql","goto","alter","redefines"].includes(x)),
  ring:n=>n.risk?[n.risk>12?"#f85149":n.risk>5?"#d29922":"#3fb950",1+3*n.risk/mx]:null,tip:n=>`${n.id}\nrisk ${n.risk} · ${n.hz.length} hazards\n${n.un.join(",")}`,click:id=>showUnit(id)});
 $("#back").onclick=e=>{e.preventDefault();progView();$("#panel").innerHTML="";$("#ptitle").textContent="Click a program"};
 $("#legend").innerHTML=cl.slice(0,8).map(c=>`<span><i style="background:${col(ci(c))}"></i>${(c||"").split("#")[1]!==undefined?"module "+c.split("#")[1]:"-"}</span>`).join("");
 $("#panel").innerHTML=`<p class="muted">${p.desc||""}<br>${p.file} · ${p.loc} loc · ${p.n} units</p><table><tr><th>unit</th><th>risk</th><th>flags</th></tr>${[...us].sort((a,b)=>b.risk-a.risk).slice(0,14).map(u=>`<tr><td><a href="#" data-u="${u.id}" style="color:var(--acc)">${u.id.split(".").pop()}</a></td><td>${u.risk}</td><td class="muted">${u.un.join(" ")}</td></tr>`).join("")}</table>`;
 $("#panel").querySelectorAll("a[data-u]").forEach(a=>a.onclick=e=>{e.preventDefault();showUnit(a.dataset.u)})}
function showUnit(id){const u=D.units.find(x=>x.id==id);$("#ptitle").textContent=id;$("#panel").innerHTML=`<p><span class="pill">${u.k}</span> <span class="pill">${u.loc} loc</span> <span class="pill">risk ${u.risk}</span> ${u.un.map(x=>`<span class="pill">${x}</span>`).join(" ")}</p>`+(u.hz.length?`<table>${u.hz.map(h=>`<tr><td class="sev-${h[1]}">${h[0]}</td><td>L${h[2]}</td><td>${h[3]}</td></tr>`).join("")}</table>`:'<p class="muted">no hazards detected</p>')}
progView();
const mxh=Math.max(...Object.values(D.hz).map(v=>v[0]+v[1]+v[2]));$("#hzbars").innerHTML=Object.entries(D.hz).sort((a,b)=>b[1].reduce((x,y)=>x+y)-a[1].reduce((x,y)=>x+y)).map(([g,v])=>`<div style="display:grid;grid-template-columns:130px 1fr 40px;gap:8px;align-items:center;margin:6px 0"><span>${gapName[g]||g} <small class="muted">${g}</small></span><div class="bar" style="width:${100*(v[0]+v[1]+v[2])/mxh}%"><i style="flex:${v[0]};background:var(--hi)"></i><i style="flex:${v[1]};background:var(--md)"></i><i style="flex:${v[2]};background:var(--lo)"></i></div><b>${v[0]+v[1]+v[2]}</b></div>`).join("");
$("#risk").innerHTML="<tr><th>unit</th><th>risk</th><th>top hazards</th></tr>"+[...D.units].sort((a,b)=>b.risk-a.risk).slice(0,15).map(u=>`<tr><td>${u.id}</td><td>${u.risk}</td><td class="muted">${[...new Set(u.hz.map(h=>h[0]))].join(" ")}</td></tr>`).join("");
const byC={};D.plan.forEach(id=>{const u=D.units.find(x=>x.id==id);(byC[u.c]=byC[u.c]||[]).push(u)});
$("#planl").innerHTML=`<p class="muted">${D.plan.length} units planned, ${D.skipped} skipped as out of scope.</p>`+Object.entries(byC).slice(0,40).map(([c,us])=>`<div style="margin:8px 0"><b>${c}</b> <span class="muted">${us.length} units · risk ${us.reduce((a,u)=>a+u.risk,0)}</span><br><code>${us.slice(0,10).map(u=>u.id.split(".").pop()).join(" → ")}${us.length>10?" …":""}</code></div>`).join("");
</script></body></html>"""
