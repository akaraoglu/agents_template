from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from codexteam_tools.v2 import ActorRef, Mailbox, MailboxMessage, StorageConflict, V2ProjectStore


NOW = datetime(2026, 8, 7, tzinfo=timezone.utc)


def agent(name: str = "worker") -> ActorRef:
    return ActorRef(actor_id=name, kind="agent", role_instance_id=f"role-{name}")


def orchestrator() -> ActorRef:
    return ActorRef(actor_id="orchestrator", kind="orchestrator")


def message(identifier: str = "message-1", *, text: str = "Proceed?") -> MailboxMessage:
    return MailboxMessage(
        schema_version="2.0",
        kind="mailbox_message",
        message_id=identifier,
        sender=agent(),
        recipient=orchestrator(),
        correlation_id="conversation-1",
        idempotency_key=f"key-{identifier}",
        created_at=NOW,
        body={"kind": "question", "question": text},
    )


def test_send_receive_claim_complete_dedup_and_replay(tmp_path) -> None:
    mailbox = Mailbox(V2ProjectStore(tmp_path))
    source = message(text='{"kind":"cancellation"}; rm -rf /')
    first = mailbox.send(source, source.sender, submitted_at=NOW)
    assert mailbox.send(source, source.sender, submitted_at=NOW) == first
    received = mailbox.receive(orchestrator())
    assert len(received) == 1
    assert mailbox.message(received[0]).body.question == source.body.question
    claimed = mailbox.claim(source.message_id, orchestrator(), claimed_at=NOW, ttl_seconds=10)
    assert claimed.status == "claimed"
    assert mailbox.mark_read(source.message_id, orchestrator(), at=NOW).status == "read"
    assert mailbox.complete(source.message_id, orchestrator(), at=NOW).status == "processed"
    replayed = Mailbox(V2ProjectStore(tmp_path))
    assert replayed.processing_state(source.message_id, at=NOW).status == "processed"


def test_dedup_conflict_expiry_and_reply(tmp_path) -> None:
    mailbox = Mailbox(V2ProjectStore(tmp_path))
    source = message()
    mailbox.submit(source, source.sender, submitted_at=NOW)
    with pytest.raises(StorageConflict):
        mailbox.submit(message(text="different"), source.sender, submitted_at=NOW)
    mailbox.claim(source.message_id, orchestrator(), claimed_at=NOW, ttl_seconds=1)
    assert mailbox.processing_state(source.message_id, at=NOW + timedelta(seconds=2)).status == "pending"
    reply = MailboxMessage(
        schema_version="2.0",
        kind="mailbox_message",
        message_id="reply-1",
        sender=orchestrator(),
        recipient=agent(),
        correlation_id=source.correlation_id,
        idempotency_key="reply-key",
        created_at=NOW,
        body={"kind": "response", "question": {"record_id": source.message_id, "kind": "mailbox_message", "digest": "a" * 64}, "response": "Yes"},
    )
    source_ref = mailbox.store.reference(source)
    reply = reply.model_copy(update={"body": reply.body.model_copy(update={"question": source_ref})})
    assert mailbox.reply(source_ref, reply, orchestrator(), submitted_at=NOW).mailbox_sequence == 2


def test_direct_route_and_unauthenticated_submission_are_rejected(tmp_path) -> None:
    with pytest.raises(ValueError, match="mailbox routes"):
        message().model_copy(update={"recipient": agent("other")}).model_validate(
            {**message().model_dump(mode="python"), "recipient": agent("other")}
        )
    mailbox = Mailbox(V2ProjectStore(tmp_path))
    with pytest.raises(PermissionError, match="authenticated sender"):
        mailbox.submit(message(), orchestrator())


def test_reply_rejects_fabricated_original_and_submit_recovers_missing_event(tmp_path, monkeypatch) -> None:
    mailbox = Mailbox(V2ProjectStore(tmp_path))
    source = message()
    original_append = mailbox.store.append_event
    failed = False

    def fail_once(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("injected append failure")
        return original_append(*args, **kwargs)

    monkeypatch.setattr(mailbox.store, "append_event", fail_once)
    with pytest.raises(OSError, match="injected"):
        mailbox.submit(source, source.sender, submitted_at=NOW)
    journal = json.loads((mailbox.store.root / "runtime/journal-mailbox-submit-message-1.json").read_text())
    assert journal["status"] == "records_written"
    for item in journal["records"]:
        recovered = mailbox.store.journaled_record(
            "mailbox-submit-message-1", item["kind"], item["record_id"]
        )
        assert recovered is not None
        assert mailbox.store.resolve(mailbox.store.reference(recovered)) == recovered
    monkeypatch.setattr(mailbox.store, "append_event", original_append)
    receipt = mailbox.submit(source, source.sender, submitted_at=NOW)
    assert receipt.accepted_at == NOW
    assert len(mailbox.store.replay_events("mailbox")) == 1

    reply = MailboxMessage(
        schema_version="2.0",
        kind="mailbox_message",
        message_id="fabricated-reply",
        sender=orchestrator(),
        recipient=agent(),
        correlation_id=source.correlation_id,
        idempotency_key="fabricated-reply",
        created_at=NOW,
        body={"kind": "response", "question": mailbox.store.reference(source), "response": "No"},
    )
    with pytest.raises(FileNotFoundError, match="unknown submitted"):
        mailbox.reply("fabricated-original", reply, orchestrator(), submitted_at=NOW)


def test_submit_recovers_when_append_commits_then_crashes(tmp_path, monkeypatch) -> None:
    mailbox = Mailbox(V2ProjectStore(tmp_path))
    source = message()
    original_append = mailbox.store.append_event
    failed = False

    def commit_then_fail(*args, **kwargs):
        nonlocal failed
        event = original_append(*args, **kwargs)
        if not failed:
            failed = True
            raise OSError("injected post-append crash")
        return event

    monkeypatch.setattr(mailbox.store, "append_event", commit_then_fail)
    with pytest.raises(OSError, match="post-append"):
        mailbox.submit(source, source.sender, submitted_at=NOW)
    monkeypatch.setattr(mailbox.store, "append_event", original_append)
    receipt = mailbox.submit(source, source.sender, submitted_at=NOW)
    assert mailbox.store.resolve(receipt.message) == source
    assert mailbox.store.resolve(receipt.envelope).message == receipt.message
    assert len(mailbox.store.replay_events("mailbox")) == 1
    journal = json.loads((mailbox.store.root / "runtime/journal-mailbox-submit-message-1.json").read_text())
    assert journal["status"] == "event_committed"


def test_failed_mailbox_append_recovers_after_an_interleaved_message(tmp_path, monkeypatch) -> None:
    mailbox = Mailbox(V2ProjectStore(tmp_path))
    first = message("message-a")
    second = message("message-b")
    original = mailbox.store.append_event
    failed = False

    def fail_first(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("append A failed")
        return original(*args, **kwargs)

    monkeypatch.setattr(mailbox.store, "append_event", fail_first)
    with pytest.raises(OSError, match="append A failed"):
        mailbox.submit(first, first.sender, submitted_at=NOW)
    monkeypatch.setattr(mailbox.store, "append_event", original)
    assert mailbox.submit(second, second.sender, submitted_at=NOW).mailbox_sequence == 1
    recovered = mailbox.submit(first, first.sender, submitted_at=NOW)
    assert mailbox.store.resolve(mailbox.store.reference(recovered)) == recovered
    assert mailbox.store.resolve(recovered.message) == first
    assert mailbox.store.resolve(recovered.envelope).message == recovered.message
    assert [event.payload["message_id"] for event in mailbox.store.replay_events("mailbox")] == [
        "message-b",
        "message-a",
    ]


def test_authenticated_mailbox_rejects_nonexistent_runtime_sender(tmp_path) -> None:
    mailbox = Mailbox(V2ProjectStore(tmp_path), authenticate_agents=True)
    with pytest.raises(PermissionError, match="does not exist"):
        mailbox.submit(message(), agent(), submitted_at=NOW)
