from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Literal, Self, cast

from pydantic import Field, model_validator

from .canonical import canonical_sha256
from .models import ActorRef, ContractModel, MailboxMessage, RecordRef, ResponseBody, RoleInstance, VersionedRecord
from .storage import RevisionConflict, StorageConflict, V2ProjectStore


class MailboxEnvelope(VersionedRecord):
    kind: Literal["mailbox_envelope"]
    envelope_id: str
    message: RecordRef
    mailbox_sequence: int = Field(ge=1)
    authenticated_sender: ActorRef
    submitted_at: datetime

    @model_validator(mode="after")
    def message_kind_is_valid(self) -> Self:
        if self.message.kind != "mailbox_message":
            raise ValueError("message must reference a mailbox_message")
        return self


class MailboxReceipt(VersionedRecord):
    kind: Literal["mailbox_receipt"]
    receipt_id: str
    envelope: RecordRef
    message: RecordRef
    mailbox_sequence: int = Field(ge=1)
    accepted_at: datetime


class MailboxProcessingState(ContractModel):
    message_id: str
    status: Literal["pending", "claimed", "read", "processed", "failed", "superseded"]
    claimant: ActorRef | None = None
    claim_expires_at: datetime | None = None
    detail: str | None = None

    @model_validator(mode="after")
    def claim_fields_match_status(self) -> Self:
        claimed = self.status == "claimed"
        if claimed != (self.claimant is not None and self.claim_expires_at is not None):
            raise ValueError("claimant and expiry are required only for claimed state")
        return self


class Mailbox:
    def __init__(
        self,
        store: V2ProjectStore,
        *,
        active_role_instance: RecordRef | None = None,
        authenticate_agents: bool = False,
    ) -> None:
        self.store = store
        self.active_role_instance = active_role_instance
        self.authenticate_agents = authenticate_agents or active_role_instance is not None
        store.register_record_type("mailbox_envelope", MailboxEnvelope, "envelope_id")
        store.register_record_type("mailbox_receipt", MailboxReceipt, "receipt_id")

    @staticmethod
    def _now(value: datetime | None) -> datetime:
        result = value or datetime.now(timezone.utc)
        if result.tzinfo is None or result.utcoffset() != timedelta(0):
            raise ValueError("timestamp must be UTC-aware")
        return result

    def submit(
        self,
        message: MailboxMessage,
        authenticated_sender: ActorRef,
        *,
        submitted_at: datetime | None = None,
    ) -> MailboxReceipt:
        if message.sender != authenticated_sender:
            raise PermissionError("authenticated sender does not match message sender")
        if message.sender.kind == "agent" and self.authenticate_agents:
            try:
                role = cast(RoleInstance, self.store.read_record("role_instance", cast(str, message.sender.role_instance_id)))
            except FileNotFoundError as exc:
                raise PermissionError("mailbox sender RoleInstance does not exist") from exc
            role_ref = self.store.reference(role)
            if self.active_role_instance is not None and role_ref != self.active_role_instance:
                raise PermissionError("mailbox sender is not the active runtime RoleInstance")
        accepted_at = self._now(submitted_at or message.created_at)
        aggregate = "mailbox"
        sender_key = f"{message.sender.actor_id}:{message.idempotency_key}"
        with self.store.run_lock(aggregate):
            prior_events = self.store.replay_events(aggregate, _locked=True)
            for event in prior_events:
                if event.payload.get("type") != "submitted":
                    continue
                if event.payload.get("message_id") == message.message_id:
                    prior = cast(
                        MailboxReceipt,
                        self.store.read_record("mailbox_receipt", cast(str, event.payload["receipt_id"])),
                    )
                    prior_message = self.store.resolve(prior.message)
                    if prior_message != message:
                        raise StorageConflict(f"mailbox message conflict for {message.message_id}")
                    prior_envelope = cast(MailboxEnvelope, self.store.resolve(prior.envelope))
                    self.store.commit_records_event(
                        f"mailbox-submit-{message.message_id}",
                        (
                            (message, sender_key),
                            (prior_envelope, message.message_id),
                            (prior, message.message_id),
                        ),
                        aggregate,
                        {
                            "message_id": message.message_id,
                            "receipt_id": prior.receipt_id,
                            "recipient": message.recipient.model_dump(mode="json"),
                            "sender_key": sender_key,
                            "type": "submitted",
                        },
                        expected_version=len(prior_events),
                        _locked=True,
                    )
                    return prior
                if event.payload.get("sender_key") == sender_key:
                    raise StorageConflict(f"mailbox idempotency conflict for {sender_key}")
            message_ref = self.store.reference(message)
            sequence = len(prior_events) + 1
            envelope_id = f"envelope-{message.message_id}"
            envelope = MailboxEnvelope(
                schema_version="2.0",
                kind="mailbox_envelope",
                envelope_id=envelope_id,
                message=message_ref,
                mailbox_sequence=sequence,
                authenticated_sender=authenticated_sender,
                submitted_at=accepted_at,
            )
            envelope_ref = self.store.reference(envelope)
            receipt = MailboxReceipt(
                schema_version="2.0",
                kind="mailbox_receipt",
                receipt_id=f"receipt-{message.message_id}",
                envelope=envelope_ref,
                message=message_ref,
                mailbox_sequence=sequence,
                accepted_at=accepted_at,
            )
            payload = {
                "message_id": message.message_id,
                "receipt_id": receipt.receipt_id,
                "recipient": message.recipient.model_dump(mode="json"),
                "sender_key": sender_key,
                "type": "submitted",
            }
            self.store.commit_records_event(
                f"mailbox-submit-{message.message_id}",
                (
                    (message, sender_key),
                    (envelope, message.message_id),
                    (receipt, message.message_id),
                ),
                aggregate,
                payload,
                expected_version=len(prior_events),
                _locked=True,
            )
            journaled = self.store.journaled_record(
                f"mailbox-submit-{message.message_id}", "mailbox_receipt", receipt.receipt_id
            )
            if not isinstance(journaled, MailboxReceipt):
                raise RuntimeError("mailbox transaction did not retain its durable receipt")
            self.store.resolve(journaled.message)
            self.store.resolve(journaled.envelope)
            return journaled

    send = submit

    def receive(self, recipient: ActorRef, *, after_sequence: int = 0) -> tuple[MailboxEnvelope, ...]:
        if after_sequence < 0:
            raise ValueError("after_sequence must be nonnegative")
        received: list[MailboxEnvelope] = []
        for event in self.store.replay_events("mailbox"):
            if event.sequence <= after_sequence or event.payload.get("type") != "submitted":
                continue
            if event.payload.get("recipient") != recipient.model_dump(mode="json"):
                continue
            receipt = cast(MailboxReceipt, self.store.read_record("mailbox_receipt", cast(str, event.payload["receipt_id"])))
            received.append(cast(MailboxEnvelope, self.store.resolve(receipt.envelope)))
        return tuple(received)

    def message(self, envelope: MailboxEnvelope) -> MailboxMessage:
        return cast(MailboxMessage, self.store.resolve(envelope.message))

    def _processing_events(self, message_id: str) -> tuple[dict[str, object], ...]:
        return tuple(dict(event.payload) for event in self.store.replay_events(f"mailbox-state-{message_id}"))

    def _recipient(self, message_id: str) -> ActorRef:
        for event in self.store.replay_events("mailbox"):
            if event.payload.get("type") == "submitted" and event.payload.get("message_id") == message_id:
                return ActorRef.model_validate(event.payload["recipient"])
        raise FileNotFoundError(f"unknown mailbox message {message_id!r}")

    def processing_state(self, message_id: str, *, at: datetime | None = None) -> MailboxProcessingState:
        current = MailboxProcessingState(message_id=message_id, status="pending")
        observed_at = self._now(at)
        for event in self._processing_events(message_id):
            current = MailboxProcessingState.model_validate_json(json.dumps(event["state"]), strict=True)
        if current.status == "claimed" and cast(datetime, current.claim_expires_at) <= observed_at:
            return MailboxProcessingState(message_id=message_id, status="pending")
        return current

    def _transition(
        self,
        message_id: str,
        state: MailboxProcessingState,
        *,
        expected_version: int,
    ) -> MailboxProcessingState:
        self.store.append_event(
            f"mailbox-state-{message_id}",
            {"state": state.model_dump(mode="json"), "type": "processing_state"},
            expected_version=expected_version,
        )
        return state

    def claim(
        self,
        message_id: str,
        claimant: ActorRef,
        *,
        ttl_seconds: float = 60.0,
        claimed_at: datetime | None = None,
    ) -> MailboxProcessingState:
        if ttl_seconds <= 0:
            raise ValueError("claim TTL must be positive")
        if claimant != self._recipient(message_id):
            raise PermissionError("only the message recipient may claim it")
        now = self._now(claimed_at)
        aggregate = f"mailbox-state-{message_id}"
        with self.store.run_lock(aggregate):
            events = self.store.replay_events(aggregate, _locked=True)
            current = self.processing_state(message_id, at=now)
            if current.status == "claimed":
                if current.claimant == claimant:
                    return current
                raise RevisionConflict("message is already claimed")
            if current.status not in {"pending"}:
                raise ValueError(f"cannot claim a message in {current.status!r} state")
            state = MailboxProcessingState(
                message_id=message_id,
                status="claimed",
                claimant=claimant,
                claim_expires_at=now + timedelta(seconds=ttl_seconds),
            )
            self.store.append_event(
                aggregate,
                {"state": state.model_dump(mode="json"), "type": "processing_state"},
                expected_version=len(events),
                _locked=True,
            )
            return state

    def mark_read(self, message_id: str, actor: ActorRef, *, at: datetime | None = None) -> MailboxProcessingState:
        return self._finish(message_id, actor, "read", at=at)

    def complete(
        self,
        message_id: str,
        actor: ActorRef,
        outcome: Literal["processed", "failed", "superseded"] = "processed",
        *,
        detail: str | None = None,
        at: datetime | None = None,
    ) -> MailboxProcessingState:
        return self._finish(message_id, actor, outcome, detail=detail, at=at)

    def _finish(
        self,
        message_id: str,
        actor: ActorRef,
        outcome: Literal["read", "processed", "failed", "superseded"],
        *,
        detail: str | None = None,
        at: datetime | None,
    ) -> MailboxProcessingState:
        aggregate = f"mailbox-state-{message_id}"
        if actor != self._recipient(message_id):
            raise PermissionError("only the message recipient may update processing state")
        with self.store.run_lock(aggregate):
            events = self.store.replay_events(aggregate, _locked=True)
            current = self.processing_state(message_id, at=at)
            if current.status == outcome:
                return current
            allowed = current.status == "claimed" and current.claimant == actor
            if outcome == "read":
                allowed = allowed or current.status == "pending"
            elif current.status == "read":
                allowed = True
            if not allowed:
                raise PermissionError("only the active claimant may complete the message")
            state = MailboxProcessingState(message_id=message_id, status=outcome, detail=detail)
            self.store.append_event(
                aggregate,
                {"state": state.model_dump(mode="json"), "type": "processing_state"},
                expected_version=len(events),
                _locked=True,
            )
            return state

    def reply(
        self,
        original: RecordRef | str,
        reply: MailboxMessage,
        authenticated_sender: ActorRef,
        *,
        submitted_at: datetime | None = None,
    ) -> MailboxReceipt:
        message_id = original.record_id if isinstance(original, RecordRef) else original
        submitted = next(
            (
                event
                for event in self.store.replay_events("mailbox")
                if event.payload.get("type") == "submitted" and event.payload.get("message_id") == message_id
            ),
            None,
        )
        if submitted is None:
            raise FileNotFoundError(f"unknown submitted mailbox message {message_id!r}")
        receipt = cast(
            MailboxReceipt,
            self.store.read_record("mailbox_receipt", cast(str, submitted.payload["receipt_id"])),
        )
        if isinstance(original, RecordRef) and original != receipt.message:
            raise ValueError("original message reference does not match the submitted message")
        source = cast(MailboxMessage, self.store.resolve(receipt.message))
        if isinstance(reply.body, ResponseBody) and reply.body.question != receipt.message:
            raise ValueError("response question must reference the recorded original message")
        if reply.correlation_id != source.correlation_id:
            raise ValueError("reply correlation_id does not match the original message")
        if reply.sender != source.recipient:
            raise PermissionError("reply sender must be the original recipient")
        expected_recipient = source.sender
        if source.sender.kind == "project_lead" and reply.sender.kind == "agent":
            if reply.recipient.kind != "orchestrator":
                raise PermissionError("agent replies to Project Lead messages must route through the orchestrator")
        elif reply.recipient != expected_recipient:
            raise PermissionError("reply route must reverse the original authorized route")
        return self.submit(reply, authenticated_sender, submitted_at=submitted_at)


__all__ = ["Mailbox", "MailboxEnvelope", "MailboxProcessingState", "MailboxReceipt"]
