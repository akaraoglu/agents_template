import json
import os
import uuid
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from AgenticTeam.scripts.v4_contracts import LeaseV4

def get_leases_file_path(workspace_root: str) -> Path:
    return Path(workspace_root) / ".openclaw" / "leases.json"

def _load_leases(workspace_root: str) -> List[LeaseV4]:
    path = get_leases_file_path(workspace_root)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                return []
            return [LeaseV4.model_validate(item) for item in data]
    except Exception:
        return []

def _save_leases(workspace_root: str, leases: List[LeaseV4]):
    path = get_leases_file_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".json.tmp")
    
    with open(temp_path, "w", encoding="utf-8") as f:
        # Convert to list of dicts, ensuring datetimes are serialized to strings
        json.dump([item.model_dump(mode="json") for item in leases], f, indent=2)
    temp_path.replace(path)

def acquire_lease(
    workspace_root: str,
    resource_id: str,
    owner: str,
    duration_seconds: int = 60,
    metadata: Optional[Dict[str, Any]] = None
) -> Optional[LeaseV4]:
    """
    Acquires a lease on a resource.
    Returns the lease if successful, or None if the resource is currently leased by someone else.
    """
    leases = _load_leases(workspace_root)
    now = datetime.datetime.now(datetime.timezone.utc)
    
    # Filter out expired leases
    active_leases = []
    for lease in leases:
        # Ensure lease.expires_at is timezone-aware
        exp = lease.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=datetime.timezone.utc)
        if exp > now:
            active_leases.append(lease)
            
    # Check if there is an active lease on this resource
    existing = next((l for l in active_leases if l.resource_id == resource_id), None)
    if existing:
        if existing.owner == owner and existing.metadata.get("attempt_id") == (metadata or {}).get("attempt_id"):
            # Renew the existing lease
            expires_at = now + datetime.timedelta(seconds=duration_seconds)
            existing.expires_at = expires_at
            _save_leases(workspace_root, active_leases)
            return existing
        else:
            # Resource is leased by someone else
            return None
            
    # Create new lease
    expires_at = now + datetime.timedelta(seconds=duration_seconds)
    new_lease = LeaseV4(
        lease_id=str(uuid.uuid4()),
        resource_id=resource_id,
        owner=owner,
        expires_at=expires_at,
        metadata=metadata or {}
    )
    active_leases.append(new_lease)
    _save_leases(workspace_root, active_leases)
    return new_lease

def validate_lease(
    workspace_root: str,
    lease_id: str,
    resource_id: str,
    owner: str,
    attempt_id: Optional[str] = None
) -> bool:
    """
    Validates that the given lease is currently active, unexpired, and matches parameters.
    """
    leases = _load_leases(workspace_root)
    now = datetime.datetime.now(datetime.timezone.utc)
    
    lease = next((l for l in leases if l.lease_id == lease_id), None)
    if not lease:
        return False
        
    if lease.resource_id != resource_id or lease.owner != owner:
        return False
        
    if attempt_id is not None and lease.metadata.get("attempt_id") != attempt_id:
        return False
        
    exp = lease.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=datetime.timezone.utc)
        
    return exp > now

def release_lease(workspace_root: str, lease_id: str) -> bool:
    """
    Releases a lease. Returns True if released, False if not found.
    """
    leases = _load_leases(workspace_root)
    original_len = len(leases)
    leases = [l for l in leases if l.lease_id != lease_id]
    if len(leases) < original_len:
        _save_leases(workspace_root, leases)
        return True
    return False

def clean_expired_leases(workspace_root: str):
    """
    Removes all expired leases from the leases file.
    """
    leases = _load_leases(workspace_root)
    now = datetime.datetime.now(datetime.timezone.utc)
    active_leases = []
    for lease in leases:
        exp = lease.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=datetime.timezone.utc)
        if exp > now:
            active_leases.append(lease)
    _save_leases(workspace_root, active_leases)
