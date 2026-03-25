# Zulip Setup Guide for Human-in-the-Loop Agent Teams

This guide explains how to install a self-hosted Zulip server with Docker
Compose, create the first human and bot accounts, and use the Zulip web UI as
the visible discussion surface for local agent teams.

## Template Variables

Replace these values for each deployment:
- `YOUR_ZULIP_WORKDIR`: working directory that will hold the Zulip deployment
- `YOUR_DOCKER_ZULIP_DIR`: local checkout path for `docker-zulip`
- `YOUR_ZULIP_EXTERNAL_HOST`: value for `SETTING_EXTERNAL_HOST`; include the HTTPS port when it is non-default
- `YOUR_ZULIP_SITE_URL`: full Zulip base URL, including a non-default port if needed
- `YOUR_ZULIP_ADMIN_EMAIL`: admin/support email for the deployment
- `YOUR_HTTP_PORT`: host HTTP port if remapped
- `YOUR_HTTPS_PORT`: host HTTPS port if remapped
- `YOUR_SMTP_PORT`: host SMTP port if remapped
- `YOUR_SOFTWARE_STREAM_NAME`: software request stream name
- `YOUR_SOFTWARE_MANAGER_BOT_EMAIL`: email address of the manager bot account

Recommended defaults for the current V1 template:
- `YOUR_SOFTWARE_STREAM_NAME`: `software`

## When to Use This Guide

Use this guide when you want:
- a local or self-hosted chat UI where humans can watch agent discussions
- a place to intervene when the agents drift
- visible history for implementation handoffs and review
- separate bot identities for manager and future research/software roles

This guide assumes:
- Docker and `docker compose` are installed
- you are setting up a fresh Zulip server
- you want the Docker Compose deployment path, not the native installer

## Recommended Deployment Shape

Start simple:
- one Linux machine or VM
- one Zulip server
- self-signed TLS for the first local boot
- one human admin account
- one or more bot accounts for agents

Later, you can add:
- a real hostname and DNS
- Let's Encrypt or a reverse proxy
- SMTP for invitations and notifications
- stricter permissions and narrower bot scopes

## High-Level Flow

1. Prepare the host and choose `YOUR_ZULIP_EXTERNAL_HOST`.
2. Clone the official Zulip Docker Compose repository.
3. Add the required settings and secrets.
4. Initialize the Zulip deployment.
5. Start Zulip and create the first organization.
6. Create the first human admin user.
7. Create the initial streams and bot accounts.
8. Store bot credentials privately and keep them out of git.

## 1. Prepare the Host

Use a Linux host with Docker Engine and `docker compose`.

Suggested first choices for `YOUR_ZULIP_EXTERNAL_HOST`:
- `chat.example.test`
- `chat.example.test:8443`
- `zulip.internal.example`

If you later change the public hostname or HTTPS port, update Zulip settings to
match it and regenerate any setup links.

## 2. Clone the Official Docker Repository

Create `YOUR_ZULIP_WORKDIR`, then clone the official Zulip Docker repo:

```bash
git clone https://github.com/zulip/docker-zulip.git YOUR_DOCKER_ZULIP_DIR
cd YOUR_DOCKER_ZULIP_DIR
```

## 3. Create the Required Settings File

Create `zulip-settings.env` in `YOUR_DOCKER_ZULIP_DIR`:

```env
SETTING_EXTERNAL_HOST=YOUR_ZULIP_EXTERNAL_HOST
SETTING_ZULIP_ADMINISTRATOR=YOUR_ZULIP_ADMIN_EMAIL
CERTIFICATES=self-signed
```

Notes:
- `SETTING_EXTERNAL_HOST` is the browser-visible host value
- if HTTPS is remapped to a non-default port, include that port in this value
- keep the first deployment simple; switch away from self-signed TLS later if needed

## 4. Create the Docker Compose Override File

Edit the existing `compose.override.yaml` so the Zulip service reads your local
settings and secrets:

```yaml
services:
  zulip:
    env_file:
      - ./zulip-settings.env

secrets:
  zulip__postgres_password:
    environment: "ZULIP__POSTGRES_PASSWORD"
  zulip__memcached_password:
    environment: "ZULIP__MEMCACHED_PASSWORD"
  zulip__rabbitmq_password:
    environment: "ZULIP__RABBITMQ_PASSWORD"
  zulip__redis_password:
    environment: "ZULIP__REDIS_PASSWORD"
  zulip__secret_key:
    environment: "ZULIP__SECRET_KEY"
```

## 5. Create the Secret Values

Create a local `.env` file in the same directory. Do not commit it.

```env
ZULIP__POSTGRES_PASSWORD=REPLACE_WITH_RANDOM_VALUE
ZULIP__MEMCACHED_PASSWORD=REPLACE_WITH_RANDOM_VALUE
ZULIP__RABBITMQ_PASSWORD=REPLACE_WITH_RANDOM_VALUE
ZULIP__REDIS_PASSWORD=REPLACE_WITH_RANDOM_VALUE
ZULIP__SECRET_KEY=REPLACE_WITH_LONG_RANDOM_VALUE
ZULIP__EMAIL_PASSWORD=
```

Generate strong values with `openssl`:

```bash
openssl rand -hex 24
openssl rand -hex 32
```

Recommendations:
- use different values for every secret
- keep `.env` outside version control
- store a secure backup if the deployment matters

## 6. Handle Host Port Conflicts

If ports `25`, `80`, or `443` are already in use, remap the host ports in
`compose.yaml`.

Example:

```yaml
ports:
  - name: smtp
    target: 25
    published: YOUR_SMTP_PORT
    app_protocol: smtp
  - name: http
    target: 80
    published: YOUR_HTTP_PORT
    app_protocol: http
  - name: https
    target: 443
    published: YOUR_HTTPS_PORT
    app_protocol: https
```

If you remap HTTPS, make sure `YOUR_ZULIP_EXTERNAL_HOST` includes that port.

## 7. Initialize the Zulip Deployment

From `YOUR_DOCKER_ZULIP_DIR`:

```bash
docker compose pull
docker compose run --rm zulip app:init
```

If `app:init` fails:
- inspect the error
- fix the settings or secret configuration
- rerun the command

## 8. Start Zulip

Once initialization succeeds:

```bash
docker compose up -d
```

Useful checks:

```bash
docker compose ps
docker compose logs -f zulip
```

Access Zulip at:

```text
YOUR_ZULIP_SITE_URL
```

## 9. Generate the Organization Creation Link

After the server is running:

```bash
./manage.py generate_realm_creation_link
```

Open the generated link in a browser.

If the link does not include the correct host or port:
- fix `SETTING_EXTERNAL_HOST`
- restart the Zulip service
- generate the link again

## 10. Create the First Human Admin Account

In the browser:

1. Open the organization creation link.
2. Choose the organization name.
3. Complete the registration form.
4. Create the first user account.

Use this first human account for:
- initial organization setup
- stream creation
- bot creation policy
- invitation policy
- bot account management

## 11. Create Streams

For the current software-team V1, the minimum stream is:
- `YOUR_SOFTWARE_STREAM_NAME`

Additional recommended streams for later expansion:
- `research`
- `human-feedback`
- `ops`

Recommended topic format:
- `task: <name>`
- `bug: <name>`
- `feature: <name>`
- `review: <name>`

## 12. Create Bot Accounts

For agent identities, create bot users rather than normal human accounts.

Recommended bot type:
- `Generic` bot

For the current V1 software flow, create at minimum:
- one manager bot for the software stream

Recommended defaults:
- stream: `software`
- bot display name: `software-manager-bot`

After creating the bot, store its credentials outside git. A private Zulip
credential file should contain:
- `email`
- `key`
- `site`

Treat bot API keys as secrets.

## 13. Human UI Workflow

Recommended human workflow:
- read the stream topic before replying
- intervene in the same topic when redirecting the team
- keep one topic per work item
- use direct, explicit instructions when stopping, redirecting, or narrowing scope

Useful human actions:
- clarify requirements
- approve or reject a proposed direction
- ask for a summary
- pause work
- request a follow-up task

## Validation Checklist

- `docker compose pull` succeeds
- `docker compose run --rm zulip app:init` succeeds
- `docker compose up -d` succeeds
- the setup link opens in the browser
- the first organization exists
- the human admin can log in
- the required streams exist
- bot credentials are stored privately
- no secrets were committed to git

## Security Notes

- Keep `.env`, bot `zuliprc` files, and bridge runtime state out of git.
- Prefer secure defaults in examples. Only disable TLS verification for short-lived local self-signed testing.
- Keep human admins separate from bot identities.
- Do not reuse bot credentials across unrelated environments.
