# Zulip Sprint 1 Plan

This document turns Phase 1 from `ZULIP_PLAN.md` into a practical Sprint 1
execution plan for the initial Zulip deployment.

## Template Variables

Replace these values for each deployment:
- `YOUR_ZULIP_WORKDIR`: local directory for the Zulip deployment workspace
- `YOUR_DOCKER_ZULIP_DIR`: local checkout path for `docker-zulip`
- `YOUR_ZULIP_EXTERNAL_HOST`: value used in `SETTING_EXTERNAL_HOST`
- `YOUR_ZULIP_ADMIN_EMAIL`: admin/support email for the deployment
- `YOUR_HTTP_PORT`: host HTTP port if remapped
- `YOUR_HTTPS_PORT`: host HTTPS port if remapped
- `YOUR_SMTP_PORT`: host SMTP port if remapped

## Sprint Goal

Stand up a working Zulip deployment with Docker Compose, create the first human
and bot identities, establish the initial workspace structure, and leave the
system ready for bridge work in the next sprint.

## Scope

In scope:
- Docker Compose based Zulip installation
- deployment directory setup
- local secrets and environment files
- first boot and initialization
- first organization creation
- first human admin creation
- initial streams
- initial bot accounts
- manual validation and restart checks

Out of scope:
- bridge implementation
- agent-to-Zulip automation
- SMTP
- SSO
- production TLS hardening
- reverse proxy setup
- public internet exposure

## Recommended Layout

```text
YOUR_ZULIP_WORKDIR/
├── ZULIP_SETUP_GUIDE.md
├── ZULIP_PLAN.md
├── ZULIP_SPRINT_1.md
└── docker-zulip/
```

Notes:
- keep the official `docker-zulip` repository in `docker-zulip/`
- keep local secrets out of git
- keep this workspace focused on Zulip only
- remap host ports if `80/443/25` are already occupied

## Sprint Decisions

Default assumptions unless changed:
- deployment mode: Docker Compose
- TLS mode: local-first and simple
- human admins: one primary admin to start
- bot scope: only the initial bots needed for the next sprint

## Backlog

### SP1-1 Prepare the workspace

Tasks:
- confirm `YOUR_ZULIP_WORKDIR` exists
- copy the current Zulip docs into the workspace
- clone the official `docker-zulip` repository into `YOUR_DOCKER_ZULIP_DIR`
- verify Docker and `docker compose` are available

Done when:
- the workspace contains the planning docs
- `docker-zulip/` exists
- Docker commands work locally

### SP1-2 Create deployment configuration

Tasks:
- create `zulip-settings.env`
- update `compose.override.yaml`
- create `.env`
- generate strong random secrets
- add `ZULIP__EMAIL_PASSWORD=` even if SMTP is not configured yet
- remap host ports if needed

Settings template:

```env
SETTING_EXTERNAL_HOST=YOUR_ZULIP_EXTERNAL_HOST
SETTING_ZULIP_ADMINISTRATOR=YOUR_ZULIP_ADMIN_EMAIL
CERTIFICATES=self-signed
```

Done when:
- all required local config files exist
- `.env` contains non-placeholder secrets
- nothing sensitive is committed to git
- the external host matches the chosen HTTPS port

### SP1-3 Initialize the stack

Tasks:
- run `docker compose pull`
- run `docker compose run --rm zulip app:init`
- review failures
- rerun after fixes if needed

Done when:
- `app:init` completes successfully

### SP1-4 Start the server and verify browser access

Tasks:
- run `docker compose up -d`
- check container health with `docker compose ps`
- inspect logs with `docker compose logs -f zulip` if needed
- open `YOUR_ZULIP_SITE_URL` in the browser

Done when:
- Zulip is reachable in the browser
- the login or setup flow is visible

### SP1-5 Create the first organization and admin

Tasks:
- generate the organization creation link
- open the link in the browser
- create the organization
- create the first human admin account
- verify admin access to settings

Done when:
- the organization exists
- the admin user can log in
- the admin can reach organization settings

### SP1-6 Create the initial workspace structure

Tasks:
- create `research`
- create `software`
- create `human-feedback`
- create `ops`
- document the topic naming rules

Done when:
- the streams exist
- naming conventions are documented

### SP1-7 Create initial bot identities

Recommended initial bots:
- `research-manager-bot`
- `software-manager-bot`

Tasks:
- create the bot users
- store their credentials outside git
- note each bot's intended use

Done when:
- the required bots exist
- their credentials are recoverable
- credentials are not stored in tracked repo files

### SP1-8 Validate restartability

Tasks:
- stop the stack
- start the stack again
- verify the organization, streams, and bot users are still present

Done when:
- the deployment restarts cleanly without losing state

## Validation Checklist

- `docker compose pull` succeeds
- `docker compose run --rm zulip app:init` succeeds
- `docker compose up -d` succeeds
- the Zulip URL opens in the browser
- the organization creation link works
- the human admin can log in
- the admin can access settings
- the initial streams exist
- the initial bot users exist
- the stack restarts without data loss

## Risks

- external host mismatch
- custom host port mismatch between Compose and `SETTING_EXTERNAL_HOST`
- self-signed TLS warnings
- missing secrets or malformed Compose config
- over-creating bots before the bridge design is implemented
- losing track of bot credentials

## Mitigations

- keep the first deployment local-only
- create only the minimum bot set
- store credentials in a password manager or a private local secrets file
- keep the setup commands written down during execution

## Exit Criteria

Sprint 1 is complete when:
- Zulip is running in Docker
- the browser login flow works
- the first organization exists
- the human admin can log in
- the initial streams exist
- the required bot users exist
- the system is stable enough for Sprint 2 bridge work
