# Zulip Intranet Hosting Plan

This document defines the recommended intranet-only hosting model for Zulip and
future internal tools on one machine.

Use this plan when:
- the services are only for a private network
- direct raw-IP access is awkward or unstable
- you want a clean landing page for multiple internal tools
- you expect to add more services later

Use this together with:
- `ZULIP_SETUP_GUIDE.md`
- `ZULIP_PLAN.md`
- `SETUP_BLUEPRINT.md`
- `ZULIP_INTRANET_IMPLEMENTATION.md`

## Recommendation

Use one Apache front door and separate internal hostnames for each service.

Recommended shape:
- `portal.localnet` -> main landing page
- `zulip.localnet` -> Zulip
- later:
  - `docs.localnet`
  - `grafana.localnet`
  - `agents.localnet`

All of these can point to the same host IP.

## Why This Model

Benefits:
- cleaner URLs than raw ports
- easier to add more services later
- Apache becomes the single entry point
- Zulip runs on its own hostname, which is more reliable than subpath hosting
- the main portal can stay independent from Zulip

Avoid this as the main design:
- `http://YOUR_HOST/zulip/`

Prefer:
- `https://zulip.localnet/`

## Hostname Model

Choose two names first:
- `YOUR_PORTAL_HOSTNAME`
- `YOUR_ZULIP_HOSTNAME`

Example:
- `portal.localnet`
- `zulip.localnet`

Both should resolve to:
- `YOUR_HOST_IP`

For the current machine, that is currently:
- `10.80.11.167`

## DNS Options

### Option 1: Internal DNS

Best for a real team.

Requirements:
- access to the intranet DNS server
- ability to create A records for the chosen hostnames

Example:
- `portal.localnet -> 10.80.11.167`
- `zulip.localnet -> 10.80.11.167`

### Option 2: Hosts Files

Best for a small lab or a few developer machines.

Requirements:
- edit `/etc/hosts` on Linux clients
- edit `C:\Windows\System32\drivers\etc\hosts` on Windows clients

Example entry:

```text
10.80.11.167 portal.localnet zulip.localnet
```

This is enough to run the architecture without DNS admin access.

## Certificate Model

For a clean browser experience, use a certificate for the hostname, not the raw
IP.

Recommended options:

1. Internal CA
- best long-term intranet option
- create a CA once
- trust the CA on client machines
- issue certs for `portal.localnet` and `zulip.localnet`

2. Self-signed leaf certs
- acceptable for a lab
- clients will still need to trust the cert or CA manually

Important:
- Zulip should use `YOUR_ZULIP_HOSTNAME` as `SETTING_EXTERNAL_HOST`
- the certificate must match `YOUR_ZULIP_HOSTNAME`

## Apache Role

Apache should become the public intranet entrypoint.

Responsibilities:
- serve the main portal page
- reverse proxy service hostnames to local backends
- later terminate TLS for the intranet hostnames

Recommended split:
- Apache listens on `80` and `443`
- Zulip stays behind Apache as a backend service
- Apache routes by hostname

## Portal Page

The portal should be a simple internal home page.

Recommended content:
- Zulip Agents
- Documentation
- Dashboards
- Build tools
- Project links
- Admin links

The portal does not need to be complex. A static HTML page is enough.

## Zulip Placement

Zulip should live behind its own hostname.

Target:
- `https://zulip.localnet/`

Avoid mixing Zulip into the portal root URL.

Reason:
- Zulip behaves better as a top-level site
- reverse proxying is cleaner
- future upgrades are easier

## Current-to-Target Migration

Current live state:
- Apache serves the default page on `http://10.80.11.167/`
- Zulip serves directly on `https://10.80.11.167/`
- bridges currently point to the raw-IP Zulip endpoint

Target state:
- Apache serves the portal at `https://portal.localnet/`
- Apache proxies Zulip at `https://zulip.localnet/`
- bridge bot `.zuliprc` files point to `https://zulip.localnet/`
- users stop accessing Zulip by raw IP

## Rollout Order

1. Choose the hostnames
- decide `YOUR_PORTAL_HOSTNAME`
- decide `YOUR_ZULIP_HOSTNAME`

2. Make the hostnames resolve
- internal DNS or hosts files

3. Prepare certificates
- preferred: internal CA signed certs
- acceptable: self-signed certs for the chosen hostnames

4. Reconfigure Zulip
- set `SETTING_EXTERNAL_HOST=YOUR_ZULIP_HOSTNAME`
- if using self-signed certs, regenerate them for the new hostname
- keep `SETTING_FAKE_EMAIL_DOMAIN` valid if needed

5. Repoint bridges
- update every bridge bot `.zuliprc` `site=` value to:
  `https://YOUR_ZULIP_HOSTNAME`

6. Replace the Apache default page
- create a small portal landing page for `YOUR_PORTAL_HOSTNAME`

7. Add Apache reverse proxy for Zulip
- route `YOUR_ZULIP_HOSTNAME` to the Zulip backend

8. Validate from host and client machines
- portal loads
- Zulip login loads
- bot bridges reconnect
- no stale redirects to raw IP

## Suggested First Concrete Target

For the current machine, a good first target is:
- `portal.localnet`
- `zulip.localnet`
- both mapped to `10.80.11.167`

Then:
- Apache serves `portal.localnet`
- Zulip is moved to `zulip.localnet`
- all bot bridges are updated to `https://zulip.localnet`

## Recommendation Summary

Best practical architecture:
- one host
- one Apache front door
- one portal hostname
- one Zulip hostname
- later, more hostnames for more internal tools

This keeps the intranet clean and avoids turning every service into a port
management problem.
