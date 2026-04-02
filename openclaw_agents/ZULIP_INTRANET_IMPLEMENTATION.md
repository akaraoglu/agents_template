# Zulip Intranet Implementation Runbook

This runbook turns the intranet hosting recommendation into an exact
implementation sequence for the current machine.

Use this together with:
- `ZULIP_INTRANET_HOSTING_PLAN.md`
- `ZULIP_SETUP_GUIDE.md`
- `ZULIP_PLAN.md`

## Goal

Target user-facing URLs:
- `https://portal.localnet/`
- `https://zulip.localnet/`

Target host:
- `10.80.11.167`

Target architecture:
- Apache is the front door
- Apache serves the main portal page
- Apache reverse-proxies Zulip
- Zulip backend stays local to the host
- bridges point to `https://zulip.localnet`

## Important Prerequisite

Clients must be able to reach the chosen front-door port on the host.

Recommended:
- `443` for TLS

If `443` is blocked between client and host, this hostname-based design is still
the right model, but it must be fronted on a port that the client subnet can
actually reach.

### HTTP Fallback Without Touching Docker

If the live Docker Zulip publishing must remain unchanged and clients can reach
Apache on port `80` but not the Docker-published `443`, use Apache on `80` as
the user-facing intranet entrypoint.

Recommended fallback shape:
- users open `http://zulip.localnet/`
- Apache listens on `80`
- Apache reverse-proxies to the existing Zulip backend on
  `https://127.0.0.1:443`
- Docker remains unchanged

Tradeoff:
- this keeps the current Docker layout intact
- but the client-facing path is HTTP until the network path to `443` is fixed
  or Apache is later allowed to own public `443`

## Chosen Names

Use:
- `portal.localnet`
- `zulip.localnet`

Map both to:
- `10.80.11.167`

## Step 1: Make the Names Resolve

### Option A: Internal DNS

Create A records:

```text
portal.localnet -> 10.80.11.167
zulip.localnet  -> 10.80.11.167
```

### Option B: Hosts Files

On every client and on the host, add:

Linux `/etc/hosts`:

```text
10.80.11.167 portal.localnet zulip.localnet
```

Windows `C:\Windows\System32\drivers\etc\hosts`:

```text
10.80.11.167 portal.localnet zulip.localnet
```

## Step 2: Pick the TLS Strategy

Recommended:
- use one internal CA
- issue certificates for `portal.localnet` and `zulip.localnet`
- trust the CA on client machines

Acceptable for a lab:
- self-signed certs for `portal.localnet` and `zulip.localnet`
- import and trust them on client machines

Important:
- hostname-based access is better than raw-IP access
- certificates must match the hostname the user actually opens

## Step 3: Decide the Apache Role

Recommended Apache model:
- Apache owns public `80/443`
- Apache serves `portal.localnet` directly
- Apache proxies `zulip.localnet` to the Zulip backend on `127.0.0.1:8080`

This means:
- users never hit Zulip by raw IP
- users never need to know backend ports
- the backend can remain an internal host-local detail

## Step 4: Move Zulip to Hostname-Based Access

Update Zulip settings:

```env
SETTING_EXTERNAL_HOST=zulip.localnet
SETTING_ZULIP_ADMINISTRATOR=YOUR_ZULIP_ADMIN_EMAIL
CERTIFICATES=self-signed
SETTING_FAKE_EMAIL_DOMAIN=bots.localnet
```

Notes:
- `SETTING_FAKE_EMAIL_DOMAIN` is required when raw-IP or nonstandard host
  values would otherwise break bot-domain generation
- if the existing self-signed cert was generated for another host, back it up
  and regenerate it for `zulip.localnet`

## Step 5: Keep the Zulip Backend Local

Recommended backend exposure:
- keep container HTTP on a host-local backend port such as `8080`
- stop using the raw public Zulip `443` endpoint as the user-facing URL
- Apache becomes the only public entrypoint

For the current `docker-zulip` shape, this means:
- Apache proxies to `http://127.0.0.1:8080`
- users access `https://zulip.localnet/`

## Step 6: Apache Portal Virtual Host

Create a simple portal vhost for `portal.localnet`.

Recommended content:
- Zulip Agents
- Documentation
- Dashboards
- Admin links
- Project links

The portal page can be static HTML.

Recommended behavior:
- `https://portal.localnet/` shows the main page
- one of the main links points to `https://zulip.localnet/`

## Step 7: Apache Zulip Reverse Proxy

Create a hostname-specific Apache vhost for `zulip.localnet`.

Recommended shape:
- terminate TLS in Apache
- proxy to `http://127.0.0.1:8080`
- preserve host headers

Example Apache vhost outline:

```apache
<VirtualHost *:443>
    ServerName zulip.localnet

    SSLEngine on
    SSLCertificateFile /path/to/zulip.localnet.crt
    SSLCertificateKeyFile /path/to/zulip.localnet.key

    ProxyPreserveHost On
    RequestHeader set X-Forwarded-Proto "https"
    ProxyPass / http://127.0.0.1:8080/
    ProxyPassReverse / http://127.0.0.1:8080/
</VirtualHost>
```

Required Apache modules typically include:
- `ssl`
- `proxy`
- `proxy_http`
- `headers`
- `rewrite`

### HTTP Fallback Proxy Shape

If Apache must stay on `80` because client access to `443` is blocked, use this
shape instead:

```apache
<VirtualHost *:80>
    ServerName zulip.localnet

    ProxyPreserveHost On
    SSLProxyEngine On
    SSLProxyVerify none
    SSLProxyCheckPeerCN off
    SSLProxyCheckPeerName off
    SSLProxyCheckPeerExpire off

    RequestHeader set X-Forwarded-Proto "http"
    RequestHeader set X-Forwarded-Port "80"

    ProxyPass / https://127.0.0.1:443/ retry=0 timeout=60 keepalive=On
    ProxyPassReverse / https://127.0.0.1:443/
</VirtualHost>
```

In this fallback mode:
- client URL becomes `http://zulip.localnet/`
- bridge `.zuliprc` `site=` values must use `http://zulip.localnet`
- this is intended as the safe intranet workaround when Docker must not be
  changed

## Step 8: Replace the Apache Default Page

The current Apache default Ubuntu page should be replaced by the portal site.

Target:
- `http://portal.localnet/` redirects to `https://portal.localnet/`
- `http://zulip.localnet/` redirects to `https://zulip.localnet/`

Do not use the default Apache page as the long-term user entrypoint.

## Step 9: Repoint The Gateway Bots

Every visible bot `.zuliprc` should use:

```ini
[api]
site=https://zulip.localnet
```

This includes:
- `AgentSmith`
- `Neo`
- `Yoda`
- `Niaobe`
- `Architect`
- `Morpheus`
- `Oracle`
- any future visible roles

After changing the `site=` values:
- restart the gateway service
- verify the bots reconnect

## Step 10: Restrict Access If Needed

If you do not want the whole intranet to use the service, restrict access at the
Apache layer and/or host firewall.

Apache example:

```apache
<Location />
    Require ip 10.80.60.185
    Require ip 10.80.11.0/23
</Location>
```

Host firewall example:
- allow only selected client IPs or subnets to `80/443`

This is the right way to limit access without using awkward raw-port workarounds.

## Step 11: Validation

From the host:
- `curl -k -I https://zulip.localnet/login/`
- `curl -k -I https://portal.localnet/`

From a Windows client:

```powershell
curl -k -I https://zulip.localnet/login/
curl -k -I https://portal.localnet/
```

Also verify:
- the portal page loads
- Zulip login loads
- bridge bots reconnect
- no redirects point to raw IP URLs
- the browser cert hostname matches the chosen hostname

## Step 12: Cleanup After Migration

Once the hostname-based front door works:
- stop treating `https://10.80.11.167/` as the canonical Zulip URL
- update local notes and scripts to use `zulip.localnet`
- update bridge docs and bot examples to the hostname form

## Current-Machine Suggested Rollout

Recommended exact target for this host:
- portal hostname: `portal.localnet`
- Zulip hostname: `zulip.localnet`
- host IP: `10.80.11.167`
- Apache public entrypoint: `80/443`
- Zulip backend: `127.0.0.1:8080`

Rollout order:
1. Add hosts-file or DNS entries
2. Prepare portal and Zulip hostname certificates
3. Update Zulip `SETTING_EXTERNAL_HOST=zulip.localnet`
4. Regenerate Zulip self-signed cert if still using self-signed mode
5. Add Apache vhosts for `portal.localnet` and `zulip.localnet`
6. Repoint all bridge `.zuliprc` files to `https://zulip.localnet`
7. Restart Apache, Zulip, and the bridges
8. Validate from host and client

## Recommendation Summary

Best path for this machine:
- keep Apache as the public intranet gateway
- give Zulip its own hostname
- give the main page its own hostname
- use Apache proxying, not raw-IP access, as the long-term user interface
- apply access restrictions at Apache or firewall if you do not want broad
  intranet visibility
