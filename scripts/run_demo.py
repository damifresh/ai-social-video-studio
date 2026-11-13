import os, sys, time, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
from app.db.database import Base, engine, SessionLocal
from app.db.models import Project, Job
from app.services.pipeline import run_full_pipeline
from app.services import project_store as ps

Base.metadata.create_all(bind=engine)
duration=int(sys.argv[1]) if len(sys.argv)>1 else 1
aspect=sys.argv[2] if len(sys.argv)>2 else '16:9'
style=sys.argv[3] if len(sys.argv)>3 else 'motivational'
title=sys.argv[4] if len(sys.argv)>4 else f'Demo {duration}min {aspect}'
topic=sys.argv[5] if len(sys.argv)>5 else 'How small daily habits create extraordinary results over time'
db = SessionLocal()
p = Project(title=title, topic=topic, prompt=topic, duration_min=duration, aspect_ratio=aspect,
            style=style, language='en', voice='say:Samantha', subtitle_enabled=True, music_track='none', status='draft')
db.add(p); db.commit(); db.refresh(p)
job = Job(project_id=p.id, type='full', stage='queued', status='queued', progress=0, message='Queued')
p.status='generating'; db.add(job); db.commit(); db.refresh(job)
pid,jid=p.id,job.id; db.close()
print('PROJECT',pid,'JOB',jid, flush=True)
t0=time.time(); run_full_pipeline(jid); dt=time.time()-t0
db=SessionLocal(); j=db.get(Job,jid); p=db.get(Project,pid); db.close()
res=ps.read_json(ps.project_dir(pid)/'result.json')
print('STATUS',j.status,'STAGE',j.stage,'PROG',j.progress, flush=True)
print('MSG',j.message, flush=True)
print('ERR',(j.error or '')[:500], flush=True)
print('TIME_SEC',round(dt,2), flush=True)
print('RESULT',json.dumps(res, indent=2) if res else None, flush=True)
if j.status!='succeeded': sys.exit(2)
