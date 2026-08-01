"""Factors API."""
from __future__ import annotations

import logging
import mimetypes
from io import StringIO
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response

from app.core.response import ok
from app.models.factors import FactorCreate, FactorUpdate
from app.routers.auth_db import get_current_user
from app.services.factors import bs_kit as kit
from app.services.factors_service import factors_service

logger = logging.getLogger("webapi")
router = APIRouter(prefix="/factors", tags=["factors"])


@router.get("")
@router.get("/")
async def list_factors(current_user: dict = Depends(get_current_user)):
    """同时挂 '' 与 '/'，避免 /api/factors → /api/factors/ 的 307 丢掉 Authorization。"""
    items = await factors_service.list_factors()
    return ok({"total": len(items), "items": items})


@router.get("/{factor_id}")
async def get_factor(factor_id: str, current_user: dict = Depends(get_current_user)):
    item = await factors_service.get_factor(factor_id)
    if not item:
        raise HTTPException(status_code=404, detail="factor not found")
    return ok(item)


@router.get("/{factor_id}/backtest")
async def get_factor_backtest(factor_id: str, current_user: dict = Depends(get_current_user)):
    item = await factors_service.get_backtest(factor_id)
    if item is None:
        raise HTTPException(status_code=404, detail="factor not found")
    return ok(item)


@router.get("/{factor_id}/guide")
async def get_factor_guide(factor_id: str, current_user: dict = Depends(get_current_user)):
    item = await factors_service.get_guide(factor_id)
    if item is None:
        raise HTTPException(status_code=404, detail="factor not found")
    return ok(item)


@router.get("/{factor_id}/artifacts/{artifact_id}")
async def get_factor_artifact(
    factor_id: str,
    artifact_id: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        path, meta = factors_service.resolve_artifact(factor_id, artifact_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="artifact not found")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="artifact file missing; run backtest first")

    # 操作历史：返回时补齐股票名称列（兼容旧 CSV）
    is_trade_csv = (
        str(meta.get("kind") or "") == "csv"
        and (
            "trade" in str(artifact_id).lower()
            or path.name.endswith("_trade_history.csv")
            or "操作历史" in str(meta.get("label") or "")
        )
    )
    if is_trade_csv and path.exists():
        try:
            df = pd.read_csv(path)
            df = kit.attach_stock_name_column(df)
            buf = StringIO()
            df.to_csv(buf, index=False)
            content = "\ufeff" + buf.getvalue()
            return Response(
                content=content.encode("utf-8"),
                media_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="{path.name}"'
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("enrich trade names fail %s/%s: %s", factor_id, artifact_id, exc)

    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        content_disposition_type="inline" if meta.get("kind") == "image" else "attachment",
    )


@router.post("/")
async def create_factor(payload: FactorCreate, current_user: dict = Depends(get_current_user)):
    try:
        item = await factors_service.create_factor(payload)
        return ok(item)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{factor_id}")
async def update_factor(factor_id: str, payload: FactorUpdate, current_user: dict = Depends(get_current_user)):
    try:
        item = await factors_service.update_factor(factor_id, payload)
        return ok(item)
    except LookupError:
        raise HTTPException(status_code=404, detail="factor not found")


@router.post("/{factor_id}/compute")
async def compute_factor(
    factor_id: str,
    asof: Optional[str] = Query(None, description="YYYY-MM-DD"),
    current_user: dict = Depends(get_current_user),
):
    try:
        result = await factors_service.compute_signal(factor_id, asof=asof)
        return ok(result)
    except LookupError:
        raise HTTPException(status_code=404, detail="factor not found")
    except Exception as e:  # noqa: BLE001
        logger.exception("compute factor failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{factor_id}/signals")
async def list_signals(
    factor_id: str,
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    items = await factors_service.list_signals(factor_id, limit=limit)
    return ok({"total": len(items), "items": items})
