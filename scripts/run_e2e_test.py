import os, sys, time, json, traceback
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
from app.db.database import Base, engine, SessionLocal
from app.db.models import Project, Job
from app.services.pipeline import run_full_pipeline
from app.services import project_store as ps

Base.metadata.create_all(bind=engine)

def run(duration_min=1, title="Demo 60s", topic="The power of morning routines", style="motivational", aspect="16:9"):
    db = SessionLocal()
    p = Project(title=title, topic=topic, prompt=topic, duration_min=duration_min, aspect_ratio=aspect,
                style=style, language="en", voice="say:Samantha", subtitle_enabled=True, music_track="none", status="draft")
    db.add(p); db.commit(); db.refresh(p)
    job = Job(project_id=p.id, type="full", stage="queued", status="queued", progress=0, message="Queued")
    p.status = "generating"; db.add(job); db.commit(); db.refresh(job)
    pid, jid = p.id, job.id
    db.close()
    print("PROJECT", pid, "JOB", jid)
    t0=time.time()
    run_full_pipeline(jid)
    dt=time.time()-t0
    db=SessionLocal(); j=db.get(Job,jid); p=db.get(Project,pid); db.close()
    res = ps.read_json(ps.project_dir(pid)/"result.json")
    print("STATUS", j.status, "STAGE", j.stage, "PROG", j.progress)
    print("MSG", j.message)
    print("ERR", j.error)
    print("TIME_SEC", round(dt,2))
    print("RESULT", json.dumps(res, indent=2) if res else None)
    if j.status != 'succeeded':
        sys.exit(2)
    return pid, res

if __name__ == '__main__':
    run()
