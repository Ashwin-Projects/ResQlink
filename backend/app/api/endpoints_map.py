from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, exc
from app.api.deps import get_db_with_rls, get_current_user
from app.schemas.schemas import TokenData
from app.services.request_intake import _pg_code
from app.models.core import Resource, EmergencyRequest, Shelter, Zone
import os, json, csv

router = APIRouter()

SCENARIO_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "scenario")


def _denied_or_none(e: Exception):
    """A PostgreSQL permission error is a 403, never a reason to serve the
    scenario CSV fallback (that would show data the caller's role cannot see)."""
    if isinstance(e, exc.DBAPIError) and _pg_code(e) == "42501":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role is not permitted to view this map layer.")

@router.get("/resources")
async def get_map_resources(db: AsyncSession = Depends(get_db_with_rls)):
    try:
        # Visibility follows RLS: coordinator all, owner its own, requester available only.
        stmt = text("SELECT resource_id, resource_type, resource_subtype, quantity_available, quantity_total, unit_of_measure, status, ST_Y(location::geometry) as lat, ST_X(location::geometry) as lng FROM resources")
        res = await db.execute(stmt)
        rows = res.mappings().all()
        return [dict(r) for r in rows]
    except Exception as e:
        _denied_or_none(e)
        # Fallback reading CSV
        res_path = os.path.join(SCENARIO_DIR, "resources.csv")
        items = []
        if os.path.exists(res_path):
            with open(res_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for r in reader:
                    items.append({
                        "resource_id": r.get("resource_id"),
                        "resource_type": r.get("resource_type", "general"),
                        "resource_subtype": r.get("resource_subtype", ""),
                        "quantity_available": float(r.get("quantity_available", 10)),
                        "quantity_total": float(r.get("quantity_total", 10)),
                        "unit_of_measure": r.get("unit_of_measure", "units"),
                        "status": r.get("status", "available"),
                        "lat": float(r.get("lat", 13.0827)),
                        "lng": float(r.get("lng", 80.2707)),
                        "owner_id": r.get("owner_id"),
                        "current_zone_id": r.get("current_zone_id"),
                        "capabilities": {"mobility_class": r.get("mobility_class", "land")}
                    })
        return items

@router.get("/requests")
async def get_map_requests(db: AsyncSession = Depends(get_db_with_rls),
                           current_user: TokenData = Depends(get_current_user)):
    if current_user.role == "owner":
        return []   # owners have no privilege on emergency_requests
    try:
        stmt = text("SELECT request_id, resource_type_needed, quantity_requested, quantity_fulfilled, urgency_level, status, description, ST_Y(location::geometry) as lat, ST_X(location::geometry) as lng FROM emergency_requests")
        res = await db.execute(stmt)
        rows = res.mappings().all()
        return [dict(r) for r in rows]
    except Exception as e:
        _denied_or_none(e)
        req_path = os.path.join(SCENARIO_DIR, "requests.csv")
        items = []
        if os.path.exists(req_path):
            with open(req_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for r in reader:
                    items.append({
                        "request_id": r.get("request_id"),
                        "resource_type_needed": r.get("resource_type_needed", "general"),
                        "quantity_requested": float(r.get("quantity_requested", 5)),
                        "quantity_fulfilled": float(r.get("quantity_fulfilled", 0)),
                        "urgency_level": r.get("urgency_level", "medium"),
                        "status": r.get("status", "pending"),
                        "description": r.get("description", "Emergency request"),
                        "lat": float(r.get("lat", 13.0500)),
                        "lng": float(r.get("lng", 80.2500)),
                        "zone_id": r.get("zone_id")
                    })
        return items

@router.get("/shelters")
async def get_map_shelters(db: AsyncSession = Depends(get_db_with_rls)):
    try:
        stmt = text("SELECT shelter_id, name, capacity_total, capacity_occupied, status, ST_Y(location::geometry) as lat, ST_X(location::geometry) as lng FROM shelters")
        res = await db.execute(stmt)
        rows = res.mappings().all()
        return [dict(r) for r in rows]
    except Exception as e:
        _denied_or_none(e)
        path = os.path.join(SCENARIO_DIR, "shelters.csv")
        items = []
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for r in reader:
                    items.append({
                        "shelter_id": r.get("shelter_id"),
                        "name": r.get("name", "Shelter"),
                        "capacity_total": int(r.get("capacity_total", 500)),
                        "capacity_occupied": int(r.get("capacity_occupied", 120)),
                        "status": r.get("status", "open"),
                        "lat": float(r.get("lat", 13.0800)),
                        "lng": float(r.get("lng", 80.2600))
                    })
        return items

@router.get("/zones")
async def get_map_zones(db: AsyncSession = Depends(get_db_with_rls)):
    try:
        stmt = text("SELECT zone_id, zone_name, zone_type, risk_level, population_estimate, ST_Y(location::geometry) as lat, ST_X(location::geometry) as lng FROM zones")
        res = await db.execute(stmt)
        rows = res.mappings().all()
        return [dict(r) for r in rows]
    except Exception as e:
        _denied_or_none(e)
        path = os.path.join(SCENARIO_DIR, "zones.csv")
        items = []
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for r in reader:
                    items.append({
                        "zone_id": r.get("zone_id"),
                        "zone_name": r.get("zone_name", "Zone"),
                        "zone_type": r.get("zone_type", "urban"),
                        "risk_level": r.get("risk_level", "high"),
                        "population_estimate": int(r.get("population_estimate", 10000)),
                        "lat": float(r.get("lat", 13.0800)),
                        "lng": float(r.get("lng", 80.2700))
                    })
        return items

@router.get("/hazards")
async def get_map_hazards():
    path = os.path.join(SCENARIO_DIR, "hazards.geojson")
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"type": "FeatureCollection", "features": []}
