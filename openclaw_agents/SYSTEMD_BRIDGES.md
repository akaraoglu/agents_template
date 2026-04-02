# Systemd Gateway Service

Use this unit when the Zulip integration should survive terminal closures,
host restarts, and process crashes.

## Recommended Default

For deployments from this template, use the single V3 gateway service:
- `systemd/zulip-gateway-v3.service`

This is the service for the current architecture:
- one multi-bot gateway
- all visible roles DM-able
- host-side handoff execution
- no nested in-sandbox spawning

## Install The V3 Gateway Service

```bash
cp /path/to/openclaw_agents/systemd/zulip-gateway-v3.service /tmp/zulip-gateway-v3.service
sed -i 's|LOCAL_BRIDGE_USER|YOUR_LOCAL_USER|g' /tmp/zulip-gateway-v3.service
sed -i 's|LOCAL_ZULIP_GATEWAY_V3_DIR|/abs/path/to/zulip_gateway_v3|g' /tmp/zulip-gateway-v3.service

sudo cp /tmp/zulip-gateway-v3.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable zulip-gateway-v3.service
sudo systemctl restart zulip-gateway-v3.service
```

## Verify

```bash
sudo systemctl --no-pager --full status zulip-gateway-v3.service
journalctl -u zulip-gateway-v3.service -n 50 --no-pager
```

For the full gateway rollout sequence, use `ZULIP_V3_GATEWAY_SETUP.md`.

## Notes

- Replace these placeholders before installation:
  - `LOCAL_BRIDGE_USER`
  - `LOCAL_ZULIP_GATEWAY_V3_DIR`
- If you move the gateway or run it as another user, regenerate the service
  file accordingly.
- Docker continues to own Zulip itself. `systemd` owns the long-running V3
  gateway process.
