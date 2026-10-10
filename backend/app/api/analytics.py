"""Analytics overview and chart recommendation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models import DatabaseConnection, QueryHistory, SavedQuery, User
from app.schemas import ChartRecommendationIn
from app.services.chart_service import recommend_chart

router = APIRouter()


@router.get("/overview")
def overview(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    connections = db.execute(
        select(func.count())
        .select_from(DatabaseConnection)
        .where(DatabaseConnection.user_id == user.id)
    ).scalar_one()

    total_queries = db.execute(
        select(func.count()).select_from(QueryHistory).where(QueryHistory.user_id == user.id)
    ).scalar_one()

    successful = db.execute(
        select(func.count())
        .select_from(QueryHistory)
        .where(QueryHistory.user_id == user.id, QueryHistory.execution_status == "success")
    ).scalar_one()

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent = (
        db.execute(
            select(QueryHistory)
            .where(QueryHistory.user_id == user.id)
            .order_by(QueryHistory.created_at.desc())
            .limit(8)
        )
        .scalars()
        .all()
    )
    saved_count = db.execute(
        select(func.count()).select_from(SavedQuery).where(SavedQuery.user_id == user.id)
    ).scalar_one()
    favorites = db.execute(
        select(func.count())
        .select_from(SavedQuery)
        .where(SavedQuery.user_id == user.id, SavedQuery.is_favorite.is_(True))
    ).scalar_one()

    avg_ms = db.execute(
        select(func.avg(QueryHistory.execution_time_ms)).where(
            QueryHistory.user_id == user.id,
            QueryHistory.execution_status == "success",
        )
    ).scalar_one()

    return {
        "success": True,
        "stats": {
            "connections": connections,
            "total_queries": total_queries,
            "successful_queries": successful,
            "saved_queries": saved_count,
            "favorite_queries": favorites,
            "avg_execution_time_ms": int(avg_ms) if avg_ms else None,
        },
        "recent_activity": [
            {
                "id": r.id,
                "question": r.question,
                "status": r.execution_status,
                "row_count": r.row_count,
                "execution_time_ms": r.execution_time_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in recent
        ],
    }


@router.post("/chart-recommendation")
def chart_recommendation(payload: ChartRecommendationIn) -> dict:
    chart = recommend_chart(payload.columns, payload.rows)
    return {"success": True, "chart": chart}
