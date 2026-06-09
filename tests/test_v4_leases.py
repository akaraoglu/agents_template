import pytest
import datetime
import time
from AgenticTeam.scripts.v4_leases import (
    acquire_lease,
    validate_lease,
    release_lease,
    clean_expired_leases
)

def test_acquire_and_validate_lease(tmp_path):
    # Acquire a valid lease
    metadata = {"project_id": "p1", "attempt_id": "att-1"}
    lease = acquire_lease(
        workspace_root=str(tmp_path),
        resource_id="res-1",
        owner="worker-1",
        duration_seconds=10,
        metadata=metadata
    )
    
    assert lease is not None
    assert lease.resource_id == "res-1"
    assert lease.owner == "worker-1"
    
    # Validate lease
    is_valid = validate_lease(
        workspace_root=str(tmp_path),
        lease_id=lease.lease_id,
        resource_id="res-1",
        owner="worker-1",
        attempt_id="att-1"
    )
    assert is_valid is True

def test_lease_collision(tmp_path):
    metadata = {"project_id": "p1", "attempt_id": "att-1"}
    # Owner 1 acquires
    lease1 = acquire_lease(
        workspace_root=str(tmp_path),
        resource_id="res-1",
        owner="worker-1",
        duration_seconds=10,
        metadata=metadata
    )
    assert lease1 is not None
    
    # Owner 2 tries to acquire same resource
    lease2 = acquire_lease(
        workspace_root=str(tmp_path),
        resource_id="res-1",
        owner="worker-2",
        duration_seconds=10,
        metadata={"project_id": "p1", "attempt_id": "att-2"}
    )
    assert lease2 is None

def test_lease_renewal(tmp_path):
    metadata = {"project_id": "p1", "attempt_id": "att-1"}
    lease1 = acquire_lease(
        workspace_root=str(tmp_path),
        resource_id="res-1",
        owner="worker-1",
        duration_seconds=5,
        metadata=metadata
    )
    assert lease1 is not None
    
    # Renew
    lease2 = acquire_lease(
        workspace_root=str(tmp_path),
        resource_id="res-1",
        owner="worker-1",
        duration_seconds=15,
        metadata=metadata
    )
    assert lease2 is not None
    assert lease2.lease_id == lease1.lease_id
    # Check that expiry is updated to roughly now + 15
    now = datetime.datetime.now(datetime.timezone.utc)
    diff = lease2.expires_at.replace(tzinfo=datetime.timezone.utc) - now
    assert diff.total_seconds() > 10

def test_lease_expiration(tmp_path):
    metadata = {"project_id": "p1", "attempt_id": "att-1"}
    # Acquire a lease with -1 duration (already expired)
    lease = acquire_lease(
        workspace_root=str(tmp_path),
        resource_id="res-1",
        owner="worker-1",
        duration_seconds=-10,
        metadata=metadata
    )
    assert lease is not None
    
    # Validate should fail
    is_valid = validate_lease(
        workspace_root=str(tmp_path),
        lease_id=lease.lease_id,
        resource_id="res-1",
        owner="worker-1",
        attempt_id="att-1"
    )
    assert is_valid is False
    
    # Another owner should now be able to acquire it
    lease2 = acquire_lease(
        workspace_root=str(tmp_path),
        resource_id="res-1",
        owner="worker-2",
        duration_seconds=10,
        metadata={"project_id": "p1", "attempt_id": "att-2"}
    )
    assert lease2 is not None

def test_release_lease(tmp_path):
    metadata = {"project_id": "p1", "attempt_id": "att-1"}
    lease = acquire_lease(
        workspace_root=str(tmp_path),
        resource_id="res-1",
        owner="worker-1",
        duration_seconds=10,
        metadata=metadata
    )
    assert lease is not None
    
    # Release it
    released = release_lease(str(tmp_path), lease.lease_id)
    assert released is True
    
    # Validate should fail
    is_valid = validate_lease(
        workspace_root=str(tmp_path),
        lease_id=lease.lease_id,
        resource_id="res-1",
        owner="worker-1",
        attempt_id="att-1"
    )
    assert is_valid is False
