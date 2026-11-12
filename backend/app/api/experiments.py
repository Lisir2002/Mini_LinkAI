"""EXT-014 A/B 路由实验：创建/列表/结束/分桶聚合报告（管理员）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.deps import get_db, require_admin

router = APIRouter(prefix="/api/admin/experiments", tags=["admin-experiments"])
Admin = Depends(require_admin)


class ExperimentIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_id: int
    channel_a: int
    channel_b: int
    ratio_a: int = Field(default=50, ge=1, le=99)


@router.post("")
async def create_experiment(body: ExperimentIn, user: dict[str, Any] = Admin,
                            db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if body.channel_a == body.channel_b:
        raise AppError(422, "EXPERIMENT_SAME_CHANNEL", "A/B 必须是两个不同渠道")
    model = (await db.execute(text("SELECT id FROM models WHERE id=:i"),
                              {"i": body.model_id})).first()
    if model is None:
        raise AppError(422, "EXPERIMENT_MODEL_INVALID", "模型不存在")
    bound = (await db.execute(text(
        "SELECT channel_id FROM model_channels WHERE model_id=:m AND channel_id = ANY(:cs)"),
        {"m": body.model_id, "cs": [body.channel_a, body.channel_b]})).scalars().all()
    if set(bound) != {body.channel_a, body.channel_b}:
        raise AppError(422, "EXPERIMENT_CHANNEL_UNBOUND", "两个渠道都必须已绑定该模型")
    try:
        row = (await db.execute(text(
            "INSERT INTO route_experiments (model_id,channel_a,channel_b,ratio_a,created_by) "
            "VALUES (:m,:a,:b,:r,:u) RETURNING id"),
            {"m": body.model_id, "a": body.channel_a, "b": body.channel_b,
             "r": body.ratio_a, "u": user["id"]})).mappings().one()
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AppError(409, "EXPERIMENT_RUNNING", "该模型已有运行中的实验") from None
    return {"code": 0, "data": {"experiment_id": row["id"]}}


@router.get("")
async def list_experiments(user: dict[str, Any] = Admin,
                           db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    rows = (await db.execute(text(
        "SELECT e.id,e.model_id,e.channel_a,e.channel_b,e.ratio_a,e.status,"
        "e.started_at,e.ended_at,m.display_name AS model_name,"
        "ca.name AS channel_a_name,cb.name AS channel_b_name "
        "FROM route_experiments e "
        "JOIN models m ON m.id=e.model_id "
        "JOIN channels ca ON ca.id=e.channel_a "
        "JOIN channels cb ON cb.id=e.channel_b "
        "ORDER BY e.id DESC LIMIT 100"))).mappings().all()
    return {"code": 0, "data": {"items": [dict(r) for r in rows]}}


@router.post("/{eid}/end")
async def end_experiment(eid: int, user: dict[str, Any] = Admin,
                         db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = (await db.execute(text(
        "UPDATE route_experiments SET status='ended', ended_at=now() "
        "WHERE id=:i AND status='running' RETURNING id"), {"i": eid})).first()
    if row is None:
        raise AppError(404, "EXPERIMENT_NOT_FOUND", "实验不存在或已结束")
    await db.commit()
    return {"code": 0, "data": {"ended": True}}


def _recommendation(a: dict[str, Any], b: dict[str, Any],
                    names: dict[str, str]) -> str:
    if a["calls"] < 5 or b["calls"] < 5:
        return "样本量还小（任一分桶不足 5 次调用），建议继续实验再下结论。"

    def rate(x: dict[str, Any]) -> float | None:
        total = x["up"] + x["down"]
        return x["up"] / total if total else None

    ra, rb = rate(a), rate(b)
    ca, cb = a["cost"] / a["calls"], b["cost"] / b["calls"]
    reasons: list[str] = []
    winner = None
    if abs(ca - cb) > 1e-9 and (max(ca, cb) - min(ca, cb)) / max(ca, cb, 1e-9) > 0.1:
        winner = "a" if ca < cb else "b"
        reasons.append(f"单次成本低 {abs(ca - cb) / max(ca, cb):.0%}")
    if winner is None and ra is not None and rb is not None and ra != rb:
        winner = "a" if ra > rb else "b"
        reasons.append(f"好评率高 {abs(ra - rb):.0%}")
    if winner is None and a["avg_total_ms"] != b["avg_total_ms"]:
        winner = "a" if a["avg_total_ms"] < b["avg_total_ms"] else "b"
        reasons.append(f"平均延迟低 {abs(a['avg_total_ms'] - b['avg_total_ms'])}ms")
    if winner is None:
        return "两桶表现接近，暂无明显优劣，可延长实验或保持现状。"
    return f"建议切换到渠道 {names[winner]}（{'、'.join(reasons)}）。"


@router.get("/{eid}/report")
async def experiment_report(eid: int, user: dict[str, Any] = Admin,
                            db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    exp = (await db.execute(text(
        "SELECT e.*, ca.name AS a_name, cb.name AS b_name "
        "FROM route_experiments e "
        "JOIN channels ca ON ca.id=e.channel_a "
        "JOIN channels cb ON cb.id=e.channel_b WHERE e.id=:i"),
        {"i": eid})).mappings().first()
    if exp is None:
        raise AppError(404, "EXPERIMENT_NOT_FOUND", "实验不存在")
    rows = (await db.execute(text(
        "SELECT ul.bucket, count(*) AS calls, "
        "coalesce(avg(ul.total_ms),0) AS avg_ms, "
        "coalesce(sum(ul.cost),0) AS cost, "
        "count(f.id) FILTER (WHERE f.rating='up') AS up, "
        "count(f.id) FILTER (WHERE f.rating='down') AS down "
        "FROM usage_logs ul "
        "LEFT JOIN messages m ON m.usage_log_id=ul.id "
        "LEFT JOIN message_feedbacks f ON f.message_id=m.id "
        "WHERE ul.experiment_id=:e GROUP BY ul.bucket"), {"e": eid})).mappings().all()
    lat = (await db.execute(text(
        "SELECT bucket,total_ms FROM usage_logs "
        "WHERE experiment_id=:e AND total_ms IS NOT NULL"), {"e": eid})).all()
    from app.services.live_metrics import p95
    buckets = []
    for bucket in ("a", "b"):
        r = next((x for x in rows if x["bucket"] == bucket), None)
        samples = [int(x[1]) for x in lat if x[0] == bucket]
        buckets.append({
            "bucket": bucket,
            "channel_id": exp["channel_a"] if bucket == "a" else exp["channel_b"],
            "channel_name": exp["a_name"] if bucket == "a" else exp["b_name"],
            "calls": int(r["calls"]) if r else 0,
            "avg_total_ms": int(round(float(r["avg_ms"]))) if r else 0,
            "p95_total_ms": p95(samples),
            "cost": round(float(r["cost"]), 6) if r else 0.0,
            "up": int(r["up"]) if r else 0,
            "down": int(r["down"]) if r else 0,
        })
    return {"code": 0, "data": {
        "experiment_id": eid, "status": exp["status"], "ratio_a": exp["ratio_a"],
        "buckets": buckets,
        "recommendation": _recommendation(buckets[0], buckets[1],
                                          {"a": exp["a_name"], "b": exp["b_name"]})}}