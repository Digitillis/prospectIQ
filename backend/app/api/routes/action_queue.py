"""Action Queue routes for ProspectIQ — Dynamic Action Plan System."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.core.database import Database

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/action-queue", tags=["action-queue"])

def get_db(): return Database()
def _today_str(): return datetime.now(timezone.utc).strftime("%Y-%m-%d")

class ActionRequestBody(BaseModel):
    action_type: str
    count: int = Field(ge=1, le=500)
    filters: dict = Field(default_factory=dict)
    scheduled_date: Optional[str] = None
    source_preference: str = "existing_first"

class CompleteActionBody(BaseModel):
    action_type: str
    contact_id: Optional[str] = None
    company_id: Optional[str] = None

class SkipActionBody(BaseModel):
    reason: Optional[str] = None

class UpdateTargetBody(BaseModel):
    action_type: str
    target_count: int = Field(ge=0, le=1000)
    effective_date: Optional[str] = None

class BatchTargetItem(BaseModel):
    action_type: str
    target_count: int = Field(ge=0, le=1000)

class BatchTargetsBody(BaseModel):
    targets: list[BatchTargetItem]
    effective_date: Optional[str] = None

def _resolve_prospects(db, at, count, filt, excl):
    res, mi, ma = [], filt.get("min_pqs",0), filt.get("max_pqs",100)
    inds, tkw = filt.get("industries",[]), filt.get("title_keywords",[])
    ls = ["not_sent"] if at=="connection" else (["connection_accepted"] if at=="dm" else [])
    try:
        q=db.client.table("contacts").select("id,full_name,title,linkedin_url,linkedin_status,company_id,email,companies(id,name,domain,tier,pqs_total,status,industry,pain_signals,personalization_hooks)")
        if ls: q=q.in_("linkedin_status",ls)
        if at in("connection","dm"): q=q.not_.is_("linkedin_url","null")
        for r in(q.limit(count*3).execute().data or[]):
            if len(res)>=count: break
            if r["id"]in excl: continue
            co=r.get("companies")or{}
            if isinstance(co,list): co=co[0]if co else{}
            pqs=co.get("pqs_total",0)or 0
            if pqs<mi or pqs>ma: continue
            if inds and not any(i.lower()in(co.get("industry")or"").lower()for i in inds): continue
            if tkw and not any(k.lower()in(r.get("title")or"").lower()for k in tkw): continue
            res.append({"contact_id":r["id"],"company_id":r.get("company_id"),"full_name":r.get("full_name"),"title":r.get("title"),"linkedin_url":r.get("linkedin_url"),"company_name":co.get("name"),"pqs_total":pqs,"pain_signals":co.get("pain_signals"),"hooks":co.get("personalization_hooks")})
        res.sort(key=lambda x:x.get("pqs_total",0),reverse=True)
    except Exception as e: logger.error(f"Resolve: {e}")
    return res

def _build_items(prospects,at,rid,sd,src):
    return[{"action_type":at,"company_id":p.get("company_id"),"contact_id":p.get("contact_id"),"source":src,"request_id":rid,"priority":max(0,100-(p.get("pqs_total",0)or 0)),"pqs_at_queue_time":p.get("pqs_total",0),"status":"pending","scheduled_date":sd,"context":{k:p[k]for k in("pain_signals","hooks")if p.get(k)}}for p in prospects]

@router.post("/request")
async def request_actions(body: ActionRequestBody):
    db=get_db(); sd=body.scheduled_date or _today_str()
    req=db.insert_action_request({"action_type":body.action_type,"requested_count":body.count,"filters":body.filters,"status":"pending"})
    rid=req.get("id")
    excl=db.get_queued_contact_ids(sd)
    prospects=_resolve_prospects(db,body.action_type,body.count,body.filters,excl)
    items=_build_items(prospects,body.action_type,rid,sd,"request_batch")
    inserted=[]
    if items:
        try: inserted=db.insert_action_queue_batch(items)
        except Exception as e:
            db.update_action_request(rid,{"status":"failed","error_message":str(e)})
            raise HTTPException(500,f"Failed: {e}")
    n=len(inserted)
    db.update_action_request(rid,{"fulfilled_count":n,"from_existing":n,"status":"fulfilled" if n>=body.count else("partial" if n>0 else "failed")})
    return{"data":{"request_id":rid,"action_type":body.action_type,"requested":body.count,"fulfilled":n,"from_existing":n,"from_apollo":0,"scheduled_date":sd,"queue_preview":[{"company":p.get("company_name"),"contact":p.get("full_name",""),"pqs":p.get("pqs_total",0)}for p in prospects[:5]]},"message":f"Queued {n} actions"}

@router.get("")
async def get_queue(date:str|None=None,action_type:str|None=None,status:str="pending",limit:int=100):
    db=get_db(); items=db.get_action_queue(date or _today_str(),action_type,status,limit)
    return{"data":items,"count":len(items)}

@router.post("/{item_id}/complete")
async def complete_action(item_id:str,body:CompleteActionBody):
    db=get_db(); now=datetime.now(timezone.utc).isoformat()
    u=db.update_action_queue_item(item_id,{"status":"completed","completed_at":now})
    if not u: raise HTTPException(404,"Not found")
    db.insert_interaction({"type":"note","body":f"Action: {body.action_type}","source":"daily_cockpit","metadata":{"action_type":body.action_type,"queue_item_id":item_id},**(dict(company_id=body.company_id)if body.company_id else{}),**(dict(contact_id=body.contact_id)if body.contact_id else{})})
    if body.action_type=="connection"and body.contact_id: db.update_contact(body.contact_id,{"linkedin_status":"connection_sent","updated_at":now})
    if body.action_type=="dm"and body.contact_id: db.update_contact(body.contact_id,{"linkedin_status":"dm_sent","updated_at":now})
    return{"data":{"item_id":item_id,"status":"completed"},"message":"Done"}

@router.post("/{item_id}/skip")
async def skip_action(item_id:str,body:SkipActionBody):
    db=get_db()
    u=db.update_action_queue_item(item_id,{"status":"skipped","skipped_reason":body.reason})
    if not u: raise HTTPException(404,"Not found")
    return{"data":{"item_id":item_id,"status":"skipped"},"message":"Skipped"}

@router.delete("/{item_id}")
async def remove_action(item_id:str):
    db=get_db(); db.client.table("action_queue").delete().eq("id",item_id).execute()
    return{"message":"Removed"}

@router.get("/targets")
async def get_targets(date:str|None=None):
    db=get_db(); tgts=db.get_daily_targets(date or _today_str())
    return{"data":tgts,"summary":{t["action_type"]:t["target_count"]for t in tgts}}

@router.put("/targets")
async def update_target(body:UpdateTargetBody):
    db=get_db(); r=db.upsert_daily_target(body.action_type,body.target_count,body.effective_date)
    return{"data":r,"message":f"Target set to {body.target_count}"}

@router.put("/targets/batch")
async def update_targets_batch(body:BatchTargetsBody):
    db=get_db(); rs=[db.upsert_daily_target(i.action_type,i.target_count,body.effective_date)for i in body.targets]
    return{"data":rs,"message":f"Updated {len(rs)} targets"}

@router.post("/auto-fill")
async def auto_fill(scheduled_date:str|None=None):
    db=get_db(); sd=scheduled_date or _today_str()
    tgts=db.get_daily_targets(sd); excl=db.get_queued_contact_ids(sd)
    total,by_type=0,{}
    for t in tgts:
        at,tc=t["action_type"],t["target_count"]
        need=max(0,tc-db.count_action_queue(sd,at))
        if need<=0: by_type[at]=0; continue
        ps=_resolve_prospects(db,at,need,{},excl)
        if ps:
            items=_build_items(ps,at,None,sd,"auto")
            try: db.insert_action_queue_batch(items); total+=len(items); by_type[at]=len(items); excl.update(p["contact_id"]for p in ps if p.get("contact_id"))
            except: by_type[at]=0
        else: by_type[at]=0
    return{"data":{"scheduled_date":sd,"total_added":total,"by_type":by_type},"message":f"Auto-filled {total}"}

@router.get("/summary")
async def get_summary(date:str|None=None):
    db=get_db(); sd=date or _today_str()
    tgts=db.get_daily_targets(sd); tm={t["action_type"]:t["target_count"]for t in tgts}
    bd,td,tt={},0,0
    for at in(list(tm.keys())or["connection","dm","email","outcome","post"]):
        d=db.count_action_queue(sd,at,"completed"); p=db.count_action_queue(sd,at,"pending"); t=tm.get(at,0)
        bd[at]={"done":d,"pending":p,"target":t}; td+=d; tt+=t
    return{"data":{"date":sd,"total_done":td,"total_target":tt,"breakdown":bd}}

@router.get("/requests")
async def get_requests(limit:int=50):
    db=get_db(); r=db.get_action_requests(limit)
    return{"data":r,"count":len(r)}
