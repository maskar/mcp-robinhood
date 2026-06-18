# mcp-robinhood

Read-only Robinhood portfolio + market-data MCP server (FastMCP 3.x, Google OAuth).
Deployed as a Podman container on `geeksaw-vps`, fronted by Cloudflare Tunnel at
`rh.geeksaw.com`.

## Deployment (IMPORTANT — read before deploying)

**Deploy is GitHub-only. Push to `main` → CI → auto-deploy. There is NO manual deploy.**

1. `git push origin main`
2. `ci.yml` runs on the push: `ruff check .`, full `pytest -q` (no live DB needed),
   import smoke test, `compileall`.
3. On CI **success**, `deploy-geeksaw.yml` triggers (via `workflow_run`): joins
   Tailscale, SSHes to geeksaw, `rsync`s the source to the host, then
   `podman compose up -d --build` to rebuild + restart the container.

So deployed state always matches `origin/main`. To deploy a change, get it onto
`main` and let the pipeline run.

### Do NOT use the legacy justfile deploy recipes

The `justfile` still contains `deploy` / `build` / `up` / `restart` recipes that
rsync + build manually. These are **superseded** by the GitHub Actions pipeline and
must not be used for production deploys — using them bypasses CI and can leave the
container out of sync with `main`. They remain only for emergency/local debugging.

### Before working on this repo

`git fetch origin` FIRST. This repo receives pushes from other sessions and from the
deploy pipeline, so local `main` goes stale. If `origin/main` is ahead, rebase onto it
and **run the full suite locally** before pushing (a clean rebase can still be
semantically broken). Note: `gh` defaults to the `upstream` fork
(`Open-Agent-Tools/open-stocks-mcp`) — pass `--repo maskar/mcp-robinhood` to query the
right Actions runs.

## Auth

- **Google OAuth** with a single-email allowlist (`GOOGLE_ALLOWED_EMAIL`) enforces
  real-user access. Config (`GOOGLE_CLIENT_ID/SECRET/ALLOWED_EMAIL`, `PUBLIC_HOSTNAME`)
  lives in HashiCorp Vault at `secret/mcp-robinhood` (AppRole).
- **Internal bearer token** (`robinhood_internal_bearer_token` in Vault) bypasses
  Google OAuth for automated **testing only** — checked first in
  `_RobinhoodGoogleProvider.verify_token`. Send `Authorization: Bearer <token>`. The
  token is also in 1Password Homelab ("Robinhood MCP Internal Bearer Token"). This does
  NOT weaken end-user OAuth.

## Secrets

HashiCorp Vault on `rpissd` at `secret/mcp-robinhood` (KV v2, AppRole), with `.env`
fallback. The container reads Vault at startup via `VAULT_ADDR` + AppRole creds.

## Testing the deployed server

```bash
# bearer-authenticated call to the live MCP (no Google prompt):
BEARER=$(op read 'op://Homelab/Robinhood MCP Internal Bearer Token/credential')
# MCP streamable-HTTP: initialize -> capture Mcp-Session-Id -> notifications/initialized -> tools/call
# (send Authorization: Bearer $BEARER on every request)
```
