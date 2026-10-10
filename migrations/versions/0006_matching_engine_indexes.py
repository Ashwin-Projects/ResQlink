"""add matching-engine indexes: GiST proximity + status/type/zone/urgency lookups

Revision ID: 0006
Revises: 0005
Create Date: 2026-01-01 00:05:00
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Proximity (GiST on geography) — powers ST_DWithin and the <-> KNN operator.
    op.execute("CREATE INDEX idx_zones_location_gist     ON zones             USING GIST (location);")
    op.execute("CREATE INDEX idx_shelters_location_gist  ON shelters          USING GIST (location) WHERE location IS NOT NULL;")
    op.execute("CREATE INDEX idx_resources_location_gist ON resources         USING GIST (location);")
    op.execute("CREATE INDEX idx_requests_location_gist  ON emergency_requests USING GIST (location);")

    # Matching engine candidate-resource filter: status + type + zone (partial,
    # only 'available' resources are ever candidates).
    op.execute(
        """
        CREATE INDEX idx_resources_status_type_zone
            ON resources (status, resource_type, current_zone_id)
            WHERE status = 'available';
        """
    )
    op.execute("CREATE INDEX idx_resources_owner        ON resources (owner_id);")
    op.execute("CREATE INDEX idx_resources_current_zone ON resources (current_zone_id);")

    # Resource <-> zone coverage, both directions.
    op.execute("CREATE INDEX idx_coverage_zone     ON resource_zone_coverage (zone_id);")
    op.execute("CREATE INDEX idx_coverage_resource ON resource_zone_coverage (resource_id);")

    # Live request queue: open/partially-fulfilled, ranked by urgency then age.
    op.execute(
        """
        CREATE INDEX idx_requests_open_urgency
            ON emergency_requests (urgency_level, requested_at)
            WHERE status IN ('open','partially_fulfilled');
        """
    )
    op.execute("CREATE INDEX idx_requests_requester    ON emergency_requests (requester_id);")
    op.execute("CREATE INDEX idx_requests_zone         ON emergency_requests (zone_id);")
    op.execute(
        """
        CREATE INDEX idx_requests_duplicate_of ON emergency_requests (duplicate_of_request_id)
            WHERE duplicate_of_request_id IS NOT NULL;
        """
    )

    # Allocation lookups, both directions of the junction.
    op.execute("CREATE INDEX idx_allocations_resource_status ON allocations (resource_id, allocation_status);")
    op.execute("CREATE INDEX idx_allocations_request_status  ON allocations (request_id, allocation_status);")
    op.execute("CREATE INDEX idx_allocations_matched_by      ON allocations (matched_by);")

    # Audit trail reconstruction.
    op.execute("CREATE INDEX idx_history_entity       ON allocation_history (entity_type, entity_id, performed_at);")
    op.execute("CREATE INDEX idx_history_allocation   ON allocation_history (allocation_id);")
    op.execute("CREATE INDEX idx_history_performed_by ON allocation_history (performed_by);")

    # Zone hierarchy / shelter-to-zone traversal.
    op.execute("CREATE INDEX idx_zones_parent  ON zones (parent_zone_id);")
    op.execute("CREATE INDEX idx_shelters_zone ON shelters (zone_id);")


def downgrade() -> None:
    for idx in [
        "idx_shelters_zone", "idx_zones_parent",
        "idx_history_performed_by", "idx_history_allocation", "idx_history_entity",
        "idx_allocations_matched_by", "idx_allocations_request_status", "idx_allocations_resource_status",
        "idx_requests_duplicate_of", "idx_requests_zone", "idx_requests_requester", "idx_requests_open_urgency",
        "idx_coverage_resource", "idx_coverage_zone",
        "idx_resources_current_zone", "idx_resources_owner", "idx_resources_status_type_zone",
        "idx_requests_location_gist", "idx_resources_location_gist", "idx_shelters_location_gist", "idx_zones_location_gist",
    ]:
        op.execute(f"DROP INDEX IF EXISTS {idx};")
