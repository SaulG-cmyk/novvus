"""Business rules for Auditorías."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, UTC
from fastapi.responses import PlainTextResponse

from models import AuditFinding, Audit
from novvus_sdk import NovvusModule, requires, current_context

class EscalateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notes: str = ""

async def export_audits_csv(session: AsyncSession) -> str:
    rows = (await session.execute(text(
        "SELECT id, name, audit_type, status, start_date, end_date FROM mod_auditorias.audit WHERE deleted_at IS NULL ORDER BY start_date DESC NULLS LAST"
    ))).all()
    lines = ["id,name,audit_type,status,start_date,end_date"]
    for r in rows:
        def esc(v):
            s = "" if v is None else str(v)
            if "," in s or '"' in s or "\n" in s:
                s = '"' + s.replace('"', '""') + '"'
            return s
        lines.append(",".join(esc(v) for v in r))
    return "\n".join(lines) + "\n"


async def dashboard(session: AsyncSession) -> dict[str, Any]:
    audits = (await session.execute(text("SELECT status, COUNT(*) FROM mod_auditorias.audit WHERE deleted_at IS NULL GROUP BY status"))).all()
    by_status = {str(r[0]): int(r[1]) for r in audits}
    findings = (await session.execute(text("SELECT severity, COUNT(*) FROM mod_auditorias.audit_finding WHERE deleted_at IS NULL AND status NOT IN ('closed','accepted') GROUP BY severity"))).all()
    by_sev = {str(r[0]): int(r[1]) for r in findings}
    total_findings = sum(by_sev.values())
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "metrics": [
            {"label": "Auditorías totales", "value": sum(by_status.values()), "description": "Todas las auditorías", "tone": "info"},
            {"label": "En progreso", "value": by_status.get("in_progress", 0), "description": "Auditorías en curso", "tone": "info"},
            {"label": "Completadas", "value": by_status.get("completed", 0), "description": "Auditorías finalizadas", "tone": "success"},
            {"label": "Hallazgos abiertos", "value": total_findings, "description": "No cerrados ni aceptados", "tone": "danger" if total_findings else "success"},
            {"label": "Hallazgos críticos", "value": by_sev.get("critical", 0), "description": "Severidad crítica", "tone": "danger" if by_sev.get("critical") else "neutral"},
        ],
        "recent": {"title": "Auditorías recientes", "description": "Últimas auditorías", "path": "audits", "empty": "Sin auditorías.", "items": []},
        "queues": [],
        "distribution": [{"label": k, "value": v, "tone": "info"} for k, v in sorted(by_sev.items())],
    }


def register(module: NovvusModule) -> None:
    router = module.router
    SessionDep = Annotated[AsyncSession, Depends(module.session_dependency())]

    @router.get("/reports/dashboard")
    async def _dashboard(session: SessionDep) -> dict[str, Any]:
        return await dashboard(session)

    @router.get("/reports/export/audits")
    async def _export(session: SessionDep):
        csv = await export_audits_csv(session)
        return PlainTextResponse(csv, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=audits.csv"})

    @router.post("/audit_findings/{finding_id}/escalate")
    @requires("auditorias.audit_findings.write")
    async def escalate_finding(finding_id: UUID, payload: EscalateBody, session: SessionDep) -> dict[str, Any]:
        finding = await session.scalar(
            select(AuditFinding).where(AuditFinding.id == finding_id, AuditFinding.deleted_at.is_(None))
        )
        if finding is None:
            raise HTTPException(status_code=404, detail="finding not found")

        # Get audit
        audit = await session.scalar(
            select(Audit).where(Audit.id == finding.audit_id, Audit.deleted_at.is_(None))
        )

        ctx = current_context()
        try:
            await module.call(
                "POST",
                "/api/crm/activities",
                org_id=ctx.org_id,
                json={
                    "type": "task",
                    "title": f"Seguimiento de hallazgo: {finding.title}",
                    "notes": f"Auditoría: {audit.name if audit else 'N/A'}\nSeveridad: {finding.severity}\n{payload.notes}",
                    "status": "pending",
                    "priority": "high" if finding.severity in ("high", "critical") else "medium",
                    "due_date": finding.due_date.isoformat() if finding.due_date else None,
                },
            )
        except Exception as e:
            import logging
            logging.getLogger("auditorias").warning("Failed to create activity in CRM: %s", e)

        await module.emit(
            "auditorias.finding.created",
            {"finding_id": str(finding.id), "audit_id": str(finding.audit_id), "title": finding.title, "severity": finding.severity},
        )
        return {"finding_id": str(finding.id), "status": "escalated"}

    @router.post("/audits/{audit_id}/complete")
    @requires("auditorias.audits.write")
    async def complete_audit(audit_id: UUID, session: SessionDep) -> dict[str, Any]:
        audit = await session.scalar(
            select(Audit).where(Audit.id == audit_id, Audit.deleted_at.is_(None))
        )
        if audit is None:
            raise HTTPException(status_code=404, detail="audit not found")

        audit.status = "completed"
        await session.flush()

        # Create activities for all open findings
        findings = await session.scalars(
            select(AuditFinding).where(AuditFinding.audit_id == audit_id, AuditFinding.deleted_at.is_(None), AuditFinding.status == "open")
        )
        ctx = current_context()
        count = 0
        for f in findings.all():
            try:
                await module.call(
                    "POST",
                    "/api/crm/activities",
                    org_id=ctx.org_id,
                    json={
                        "type": "task",
                        "title": f"Remediar hallazgo: {f.title}",
                        "notes": f"Auditoría: {audit.name}\nSeveridad: {f.severity}\n{f.description}",
                        "status": "pending",
                        "priority": "high" if f.severity in ("high", "critical") else "medium",
                        "due_date": f.due_date.isoformat() if f.due_date else None,
                    },
                )
                count += 1
            except Exception as e:
                import logging
                logging.getLogger("auditorias").warning("Failed to create activity: %s", e)

        await module.emit("auditorias.audit.completed", {"audit_id": str(audit.id), "name": audit.name, "findings_count": count})
        return {"audit_id": str(audit.id), "status": "completed", "activities_created": count}
