# Zulip Setup Guide for Human-in-the-Loop Agent Teams

This guide explains how to install a self-hosted Zulip server with Docker
Compose, create the first human and bot accounts, and use the Zulip web UI as
the visible discussion surface for a local research or software team.

It is written for the OpenClaw template in this repository, but the Zulip setup
itself is general and can be used for any local agent workflow.

## When to Use This Guide

Use this guide when you want:
- a local or self-hosted chat UI where humans can watch agent discussions
- a place to intervene when the agents drift in the wrong direction
- visible history for research discussions, implementation handoffs, and review
- separate bot identities for manager, research, and software roles

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

After the first successful boot, you can later add:
- a real hostname and DNS
- Let's Encrypt or a reverse proxy
- SMTP for email invitations and notifications
- stricter permissions and narrower bot scopes

## High-Level Flow

1. Prepare the server and choose a hostname.
2. Clone the official Zulip Docker Compose repository.
3. Add required settings and secrets.
4. Initialize the Zulip deployment.
5. Start Zulip and create the first organization.
6. Create the first human admin user.
7. Invite additional humans or create invitation links.
8. Create bot accounts for agent roles.
9. Create channels and working conventions for human + agent collaboration.

## 1. Prepare the Host

Use a Linux host with Docker Engine and `docker compose`.

For a first test, a machine with at least:
- 2 GB RAM minimum
- 4 GB RAM preferred

Pick the first hostname now, because it affects URLs and certificates.

Suggested first choices:
- local test machine: `localhost.localdomain`
- LAN test machine: `zulip.local` or a host in your internal DNS
- longer-lived server: `zulip.example.com`

If you use a real hostname later, update the Zulip settings to match it.

## 2. Clone the Official Docker Repository

Create a dedicated working directory and clone the official Zulip Docker repo:

```bash
git clone https://github.com/zulip/docker-zulip.git
cd docker-zulip
```

The official Docker docs use this repository as the supported deployment base.

## 3. Create the Required Settings File

Create a file named `zulip-settings.env` in the `docker-zulip` directory:

```env
SETTING_EXTERNAL_HOST=localhost.localdomain
SETTING_ZULIP_ADMINISTRATOR=admin@example.com
```

Required settings:
- `SETTING_EXTERNAL_HOST`: the hostname users will type into the browser
- `SETTING_ZULIP_ADMINISTRATOR`: the admin/support email for the server

For a local test machine, `localhost.localdomain` is acceptable.

## 4. Create the Docker Compose Override File

Create `compose.override.yaml` beside the repo's `compose.yaml`:

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

This is the smallest useful starting point.

You can add more settings later for:
- SMTP
- authentication methods
- reverse proxy and load balancer behavior
- outgoing proxy rules

## 5. Create the Secret Values

Create a `.env` file in the same directory. Do not commit it to version control.

Example:

```env
ZULIP__POSTGRES_PASSWORD=replace_with_random_value
ZULIP__MEMCACHED_PASSWORD=replace_with_random_value
ZULIP__RABBITMQ_PASSWORD=replace_with_random_value
ZULIP__REDIS_PASSWORD=replace_with_random_value
ZULIP__SECRET_KEY=replace_with_long_random_value
```

Generate strong values with `openssl`:

```bash
openssl rand -hex 24
openssl rand -hex 32
```

Recommendations:
- use different values for every secret
- keep `.env` outside version control
- store a backup copy securely if the deployment matters

## 6. Choose Your First TLS Mode

For the first local boot, keep it simple:
- use Zulip's default self-signed certificate behavior

This is enough to verify that the server works.

For a longer-lived deployment, move to one of these:
- Let's Encrypt through Zulip's supported TLS flow
- a reverse proxy that terminates TLS in front of Zulip

Do not optimize TLS on day one unless you already have DNS and a public host.

## 7. Initialize the Zulip Deployment

From the `docker-zulip` directory:

```bash
docker compose pull
docker compose run --rm zulip app:init
```

What this does:
- starts the dependency containers
- checks configuration
- initializes the database and deployment state

The important success marker is the end of the initialization phase without
errors.

If `app:init` fails:
- inspect the error carefully
- fix the settings or secret configuration
- rerun the command

## 8. Start Zulip

Once initialization succeeds:

```bash
docker compose up zulip --wait
```

For background mode:

```bash
docker compose up -d
```

Useful checks:

```bash
docker compose ps
docker compose logs -f zulip
```

## 9. Generate the Organization Creation Link

After the server is running:

```bash
./manage.py generate_realm_creation_link
```

Or, if needed:

```bash
docker compose exec -u zulip zulip \
  /home/zulip/deployments/current/manage.py generate_realm_creation_link
```

Open the generated link in a browser.

On a self-hosted server, this is how you create the first organization and the
first human account.

## 10. Create the First Human Admin Account

In the browser:

1. Open the organization creation link.
2. Choose the organization name.
3. Complete the registration form.
4. Create the first user account.

This first human account should be your admin or owner account.

Use this account for:
- initial organization setup
- channel creation
- bot creation policy
- invitation policy
- bot account management

Do not use a bot account as the primary administrator.

## 11. Invite Additional Human Users

Once logged in as an admin:

1. Click the gear icon in the top right.
2. Select `Invite users`.
3. Enter email addresses or create an invitation link.
4. Choose the role for each invitee.
5. Select default channels if desired.
6. Send the invitation or copy the reusable link.

For a small internal team, invitation links are often simpler than configuring
full email on day one.

Recommended human roles:
- you: owner or administrator
- other operators: administrator or member, depending on responsibility
- observers: member

## 12. Create Bot Accounts for Agents

For agent identities, create bot users rather than trying to let the AI create
normal human accounts on its own.

Recommended bot types:
- `Generic` bot for agent personas that act like users through the API
- `Outgoing webhook` bot only if you want Zulip to call your service when the
  bot is mentioned or direct-messaged
- `Incoming webhook` bot only for one-way posting into Zulip

For your current design, `Generic` bot accounts are the cleanest default.

### Create a bot in the UI

1. Click the gear icon in the top right.
2. Select `Personal settings`.
3. On the left, click `Bots`.
4. Click `Add a new bot`.
5. Enter the bot name and email.
6. Select the bot type.
7. Save the bot.

If you are an administrator, you can also manage bots from:
- `Organization settings -> Bots`

Suggested bot names:
- `research-manager`
- `explorer`
- `skeptic`
- `feasibility`
- `software-manager`
- `planner`
- `coder`
- `tester`

### Download bot credentials

After creating a bot, download its `zuliprc` file or copy its API details from
the bot management UI.

Treat bot API keys as secrets:
- anyone with the API key can act as that bot
- rotate keys if they leak
- store them outside git

## 13. Configure Who Can Create Bots

By default, Zulip may allow non-guest users to create bots.

For a controlled agent deployment, restrict this:

1. Click the gear icon.
2. Select `Organization settings`.
3. Open `Organization permissions`.
4. Configure who can create any bot.
5. Save changes.

Recommended policy:
- only owners and administrators can create bots

## 14. Create the Initial Channels

Before inviting many users or wiring in agents, create a minimal channel layout.

Recommended starting channels:
- `research`: research discussion and idea refinement
- `software`: implementation requests and build coordination
- `human-feedback`: human intervention, redirects, approvals
- `ops`: deployment, logs, and system notes

Why channels instead of many channels per idea:
- Zulip already uses topics inside channels
- most work should be separated by topic, not by creating a new channel

Example topic usage:
- channel `research`, topic `new onboarding idea`
- channel `software`, topic `implementation brief: onboarding idea`
- channel `human-feedback`, topic `redirect research round 2`

## 15. Human Web UI Guide

This is the most important part if you want to supervise the agents directly.

### Main UI Areas

In the Zulip web app:
- left sidebar: channels, direct messages, and inbox navigation
- center pane: the current conversation
- top bar: current channel or DM context
- compose area: send a new message or reply
- top-right gear menu: settings, invitations, permissions, and bot management

### The Most Important Zulip Concept: Topics

Zulip is built around:
- channels for audience
- topics for the actual conversation

That means:
- keep one broad channel for a work area
- use topics to separate each discussion thread

For human supervision, this is ideal because:
- each idea stays in one readable thread
- agents can discuss without mixing unrelated work
- you can intervene in one topic without disturbing the rest

### How You Read Agent Conversations

Recommended operator flow:

1. Open `Inbox` to see active conversations.
2. Click the research or software topic you want to review.
3. Read the thread in context.
4. Reply in the same topic when you want to steer the agents.

Do not create a new topic for every intervention unless you are intentionally
changing the workstream.

### How You Intervene

Use one of these patterns:
- reply directly in the same topic to redirect the team
- post in `human-feedback` and have the orchestrator treat it as control input
- mention a specific bot or manager when you need a targeted response

Good intervention examples:
- "Do not optimize for novelty here. Optimize for maintainability."
- "Pause research and convert the current idea into an implementation brief."
- "Reject the current direction. Focus on lower operational complexity."

### How You Start a New Topic

In a channel:
1. Click the new topic button next to the channel name, or use the compose box.
2. Enter a clear topic name.
3. Write the opening message.
4. Send it.

Good topic names:
- `idea: research team discussion UI`
- `implementation brief: zulip bridge`
- `review: round 3 results`

Bad topic names:
- `hi`
- `question`
- `misc`

### How You Send a Direct Message

Use direct messages only when:
- the discussion is truly private
- you want to talk to one human operator
- you need a targeted bot test

Do not use DMs for normal team discussion. Keep that in channels and topics so
history remains visible and reviewable.

## 16. Suggested Human + Agent Operating Model

Use Zulip as the conversation surface, not the hidden source of truth.

Recommended split:
- Zulip: visible discussion, approvals, interventions, handoffs
- your orchestrator: scheduling, agent execution, structured state, retries
- repo files: persistent project context, specs, briefs, and implementation
  artifacts

This keeps the system understandable:
- humans read and guide the discussion in Zulip
- the orchestrator handles the mechanics
- the repository stores the durable project artifacts

## 17. Suggested Initial Account Layout

Human accounts:
- `you@example.com`: owner or administrator
- optional second human admin for backup access

Bot accounts:
- `research-manager-bot`
- `explorer-bot`
- `skeptic-bot`
- `feasibility-bot`
- `software-manager-bot`
- `planner-bot`
- `coder-bot`
- `tester-bot`

Keep bot naming predictable. It makes stream/topic review much easier.

## 18. First-Day Checklist

- Docker host is ready.
- `docker-zulip` repo is cloned.
- `zulip-settings.env` is created.
- `compose.override.yaml` is created.
- `.env` secrets file is created and not committed.
- `docker compose run --rm zulip app:init` succeeds.
- `docker compose up zulip --wait` succeeds.
- organization creation link is generated.
- first human admin account is created.
- initial channels are created.
- bot creation is restricted to admins.
- first bot identities are created.

## 19. Common Pitfalls

- Putting secrets into git.
- Using bot accounts as admin users.
- Creating too many channels instead of using topics.
- Letting agents post everywhere without a channel/topic plan.
- Trying to automate everything before the human UI flow is clear.
- Adding email, SSO, and reverse proxy complexity before the base server works.

## 20. Recommended Next Step After Installation

After Zulip is working, the next practical step is:

1. create the channels and bots
2. define one simple human intervention pattern
3. bridge one manager bot into one topic
4. test the full loop with a small idea discussion

Do not start by wiring the whole team at once.

## References

- Official self-hosting overview: <https://zulip.com/self-hosting/>
- Official server install docs: <https://zulip.readthedocs.io/en/stable/production/install.html>
- Official Docker docs: <https://zulip.readthedocs.io/projects/docker/en/latest/>
- Docker Compose getting started:
  <https://zulip.readthedocs.io/projects/docker/en/latest/how-to/compose-getting-started.html>
- Docker Compose settings:
  <https://zulip.readthedocs.io/projects/docker/en/latest/how-to/compose-settings.html>
- Docker Compose secrets:
  <https://zulip.readthedocs.io/projects/docker/en/latest/how-to/compose-secrets.html>
- Create an organization:
  <https://zulip.com/help/create-an-organization>
- Invite users:
  <https://zulip.com/help/invite-new-users>
- Bots overview:
  <https://zulip.com/help/bots-overview>
- Add a bot:
  <https://zulip.com/help/add-a-bot-or-integration>
- Manage a bot:
  <https://zulip.com/help/manage-a-bot>
- Restrict bot creation:
  <https://zulip.com/help/restrict-bot-creation>
- Getting started with Zulip:
  <https://zulip.com/help/getting-started-with-zulip>
- Introduction to topics:
  <https://zulip.com/help/introduction-to-topics>
- Create channels:
  <https://zulip.com/help/create-channels>
