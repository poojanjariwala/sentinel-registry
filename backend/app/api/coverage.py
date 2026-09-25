"""Coverage/gap-analysis endpoints."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import client_ip, require_perm
from app.core.errors import SentinelError, request_id_var
from app.models.gap_run import GapAnalysisRun
from app.schemas.coverage import GapAnalysisRequest
from app.services import audit as audit_svc
from app.services.coverage_service import run_gap_analysis

router = APIRouter(prefix="/coverage", tags=["coverage"])


@router.post("/gap-analysis")
def gap_analysis(
    body: GapAnalysisRequest,
    request: Request,
    user=Depends(require_perm("coverage", "run")),
    db: Session = Depends(get_db),
):
    summary = run_gap_analysis(
        db, user,
        departments=body.departments,
        districts=body.districts,
        resolution=body.resolution,
        min_cameras_per_cell=body.min_cameras_per_cell,
        ageing_years=body.ageing_years,
    )
    run = GapAnalysisRun(
        created_by=user.user_id,
        params_json=summary["params"],
        summary_json=summary,
        camera_count_total=summary["total_cameras"],
        uncovered_hex_count=0,
        completed_at=None,
    )
    db.add(run)
    db.flush()

    audit_svc.record(
        db, "COVERAGE_RUN_CREATE", "gap_run", run.run_id,
        after_state={"params": summary["params"], "total_cameras": summary["total_cameras"]},
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=client_ip(request), user_agent=request.headers.get("user-agent"),
    )
    db.commit()

    return {"data": {"run_id": run.run_id, **summary}, "meta": {}, "requestId": request_id_var.get()}


@router.get("/runs")
def list_runs(
    user=Depends(require_perm("coverage", "run")),
    db: Session = Depends(get_db),
):
    runs = db.execute(
        select(GapAnalysisRun).order_by(GapAnalysisRun.created_at.desc()).limit(50)
    ).scalars().all()
    return {
        "data": [
            {
                "run_id": r.run_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "created_by": r.created_by,
                "params": r.params_json,
                "total_cameras": r.camera_count_total,
            }
            for r in runs
        ],
        "meta": {},
        "requestId": request_id_var.get(),
    }


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    user=Depends(require_perm("coverage", "run")),
    db: Session = Depends(get_db),
):
    run = db.get(GapAnalysisRun, run_id)
    if not run:
        raise SentinelError("RUN_NOT_FOUND", "Gap analysis run not found", 404)
    return {"data": {"run_id": run.run_id, **(run.summary_json or {})}, "meta": {}, "requestId": request_id_var.get()}


@router.get("/runs/{run_id}/export.csv")
def export_run(
    run_id: str,
    user=Depends(require_perm("coverage", "run")),
    db: Session = Depends(get_db),
):
    run = db.get(GapAnalysisRun, run_id)
    if not run:
        raise SentinelError("RUN_NOT_FOUND", "Gap analysis run not found", 404)
    s = run.summary_json or {}

    lines = ["section,key,value"]
    lines.append(f"total_cameras,{s.get('total_cameras', 0)},")
    lines.append(f"hex_covered,{s.get('hex_covered', 0)},")
    lines.append(f"hex_thin,{s.get('hex_thin', 0)},")
    lines.append(f"ageing_count,{s.get('ageing_count', 0)},")
    lines.append(f"amc_expired_count,{s.get('amc_expired_count', 0)},")
    lines.append("")
    lines.append("district,cameras,offline,faulty,ageing,amc_expired")
    for e in s.get("by_district", []):
        lines.append(f"{e['district']},{e['cameras']},{e['offline']},{e['faulty']},{e['ageing']},{e['amc_expired']}")
    lines.append("")
    lines.append("camera_code,name,district,install_date,amc_end_date,maintenance_status")
    for a in s.get("ageing_sample", []):
        lines.append(
            f"{a['camera_code']},{a['name']},{a.get('district') or ''},{a.get('install_date') or ''},"
            f"{a.get('amc_end_date') or ''},{a.get('maintenance_status') or ''}"
        )

    return Response(
        content=("\n".join(lines) + "\n").encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="gap_analysis_{run_id}.csv"'},
    )
