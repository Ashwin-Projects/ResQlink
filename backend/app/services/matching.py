import datetime
import uuid
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, text, desc
from app.models.core import Resource, EmergencyRequest, Reservation, Pool, RequestPoolDependency, EventOutbox, MatchingDecision, HazardArea, ResourceLocationHistory, Allocation
from geoalchemy2.functions import ST_Distance, ST_DWithin, ST_Intersects

class MatchingEngine:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.algorithm_version = "v1.0"
        self.max_distance_meters = 50000  # 50km
        self.reservation_lease_hours = 1

    async def _get_temporal_confidence(self, resource: Resource, now: datetime.datetime) -> float:
        # Time-decay based on last_verified_at. If old, confidence drops to 0.1
        if not resource.last_verified_at:
            return 0.5
        
        # Ensure timezone awareness
        verified_at = resource.last_verified_at
        if verified_at.tzinfo is None:
            verified_at = verified_at.replace(tzinfo=datetime.timezone.utc)
            
        age_hours = (now - verified_at).total_seconds() / 3600.0
        confidence = max(0.1, 1.0 - (age_hours / 72.0))
        return round(confidence, 2)

    async def _get_hazard_accessibility_multiplier(self, resource: Resource, request_location) -> float:
        # In a real implementation, this would use ST_Intersects(ST_MakeLine(...), hazard_area)
        # Here we mock a basic check: assume some mobility classes bypass hazards.
        # True routing requires pgRouting; geometric is a heuristic.
        mobility = resource.capabilities.get("mobility_class", "default") if resource.capabilities else "default"
        if mobility == "air":
            return 1.0
        elif mobility == "boat":
            return 0.9
        # Default penalty for land-based passing through potential hazards
        return 0.7

    async def _calculate_pool_pressure(self, pool_id: uuid.UUID) -> float:
        # pressure = demand / supply
        # This is a simplified calculation
        return 1.0

    async def committed_quantity(self, request_id: uuid.UUID) -> float:
        """Quantity already committed to a request but not yet fulfilled."""
        stmt = text("""
            SELECT COALESCE((SELECT sum(quantity) FROM reservation
                             WHERE request_id = :rid AND status = 'active' AND lease_expires_at > now()), 0)
                 + COALESCE((SELECT sum(quantity_allocated) FROM allocations
                             WHERE request_id = :rid
                               AND allocation_status IN ('pending','matched','proposed','reserved','dispatched','in_transit','delivered')), 0)
        """)
        return float((await self.db.execute(stmt, {"rid": request_id})).scalar_one())

    async def score_candidates(self, req: EmergencyRequest, now: datetime.datetime) -> List[dict]:
        """Spatial candidate retrieval (ST_DWithin) + scoring, ranked best first.
        Read-only: used by match_request and by the candidate preview API."""
        stmt = select(
            Resource,
            ST_Distance(Resource.location, req.location).label("distance_m")
        ).where(
            and_(
                Resource.status == 'available',
                Resource.resource_type == req.resource_type_needed,
                Resource.quantity_available > 0,
                ST_DWithin(Resource.location, req.location, self.max_distance_meters)
            )
        ).execution_options(populate_existing=True)

        candidates = (await self.db.execute(stmt)).all()

        scored_candidates = []
        for resource, distance_m in candidates:
            conf = await self._get_temporal_confidence(resource, now)
            access_mult = await self._get_hazard_accessibility_multiplier(resource, req.location)

            # Simple scoring formula:
            # Score = (1 - distance_normalized) * conf * access_mult + urgency_bonus
            dist_norm = min(1.0, float(distance_m) / self.max_distance_meters)
            urgency_bonus = 0.2 if req.urgency_level == 'critical' else 0.0

            score = ((1.0 - dist_norm) * conf * access_mult) + urgency_bonus

            scored_candidates.append({
                "resource": resource,
                "score": score,
                "components": {
                    "distance_m": float(distance_m),
                    "confidence": conf,
                    "accessibility": access_mult,
                    "urgency_bonus": urgency_bonus
                }
            })

        scored_candidates.sort(key=lambda x: x["score"], reverse=True)
        return scored_candidates

    async def match_request(self, request_id: uuid.UUID, mode: str = "incremental") -> List[dict]:
        """Core match logic for a single request, creating reservations atomically."""
        now = datetime.datetime.now(datetime.timezone.utc)
        
        # 1. Identify request. Lock its row so two concurrent match calls for
        #    the same request serialize instead of both reserving its remaining
        #    quantity (populate_existing: re-read, never trust a cached row).
        lock_req = select(EmergencyRequest).where(EmergencyRequest.request_id == request_id) \
            .with_for_update().execution_options(populate_existing=True)
        req = (await self.db.execute(lock_req)).scalar_one_or_none()
        if not req or req.status not in ["pending", "open", "partially_fulfilled"]:
            await self.db.commit()  # release the request row lock
            return []

        # Quantity still to cover = requested - fulfilled - quantity already
        # committed to this request (active unexpired leases + allocations
        # not yet confirmed). Without this a second match would over-reserve.
        remaining_qty = float(req.quantity_requested - req.quantity_fulfilled) - await self.committed_quantity(req.request_id)
        if remaining_qty <= 0:
            await self.db.commit()
            return []

        # 2-4. Retrieve, score and rank candidates.
        scored_candidates = await self.score_candidates(req, now)
        if not scored_candidates:
            await self.db.commit()
            return []

        proposed_reservations = []
        
        # 5. Atomic lock and reservation (Contention-safe loop)
        for cand in scored_candidates:
            if remaining_qty <= 0:
                break
                
            res_id = cand["resource"].resource_id
            
            # Select FOR UPDATE SKIP LOCKED
            # populate_existing: use the quantity read under the lock, not the
            # value cached in the session by the candidate query.
            lock_stmt = select(Resource).where(Resource.resource_id == res_id) \
                .with_for_update(skip_locked=True).execution_options(populate_existing=True)
            locked_res_result = await self.db.execute(lock_stmt)
            locked_res = locked_res_result.scalar_one_or_none()
            
            if not locked_res or locked_res.quantity_available <= 0:
                continue # Skipped or grabbed by another transaction
                
            take_qty = round(min(remaining_qty, float(locked_res.quantity_available)), 2)
            if take_qty <= 0:
                continue
            
            # Create Reservation
            expires_at = now + datetime.timedelta(hours=self.reservation_lease_hours)
            new_res = Reservation(
                reservation_id=uuid.uuid4(),
                request_id=req.request_id,
                resource_id=locked_res.resource_id,
                quantity=take_qty,
                status="active",
                lease_expires_at=expires_at,
                priority_snapshot=cand["score"]
            )
            self.db.add(new_res)
            
            # Decision Record
            decision = MatchingDecision(
                request_id=req.request_id,
                resource_id=locked_res.resource_id,
                score_components=cand["components"],
                final_score=cand["score"],
                algorithm_version=self.algorithm_version,
                mode=mode
            )
            self.db.add(decision)
            
            # Event Outbox
            event = EventOutbox(
                event_type="reservation_created",
                payload={
                    "request_id": str(req.request_id), 
                    "resource_id": str(locked_res.resource_id),
                    "quantity": take_qty
                }
            )
            self.db.add(event)
            
            # Note: The database trigger 'trg_reservations_reserve_qty' will handle decrementing resource quantity
            
            remaining_qty = round(remaining_qty - take_qty, 2)
            proposed_reservations.append({
                "reservation_id": new_res.reservation_id,
                "resource_id": locked_res.resource_id,
                "quantity": take_qty,
                "score": cand["score"],
                "lease_expires_at": expires_at,
                "score_components": cand["components"],
            })
            
        await self.db.commit()
        return proposed_reservations

    async def full_rescan(self) -> dict:
        """Baseline: evaluates all pending requests."""
        stmt = select(EmergencyRequest.request_id).where(EmergencyRequest.status.in_(["pending", "open", "partially_fulfilled"]))
        result = await self.db.execute(stmt)
        request_ids = result.scalars().all()
        
        matches = []
        for req_id in request_ids:
            res = await self.match_request(req_id, mode="full_scan")
            if res:
                matches.extend(res)
                
        return {
            "requests_examined": len(request_ids),
            "matches_made": len(matches)
        }

    async def incremental_rematch(self, pool_id: uuid.UUID) -> dict:
        """Core Invention: Only evaluates requests dependent on the affected pool."""
        stmt = select(RequestPoolDependency.request_id).where(RequestPoolDependency.pool_id == pool_id)
        result = await self.db.execute(stmt)
        affected_request_ids = result.scalars().all()
        
        matches = []
        for req_id in affected_request_ids:
            res = await self.match_request(req_id, mode="incremental")
            if res:
                matches.extend(res)
                
        return {
            "affected_pool": str(pool_id),
            "requests_examined": len(affected_request_ids),
            "matches_made": len(matches)
        }
