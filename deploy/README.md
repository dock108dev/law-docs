# Hosted operations

Lawdocs is at https://lawdocs.dock108.dev on Hetzner `62.238.114.86`. HTTPS is handled by Caddy. No login is configured. The app listens only on loopback; host networking preserves that binding inside the container.

## Releases and data

- `lawdocs.service` starts the tested container image named `lawdocs:<commit>`.
- `/etc/lawdocs/release.env` records the active commit and service UID/GID.
- `/opt/lawdocs/shared/crash` and `/opt/lawdocs/shared/plea` contain live jobs. They are mounted at `/data` and never copied into release images or rollback backups.
- Original upload timestamps govern deletion after 48 hours. Cleanup runs at startup, before requests, and every minute. The migrated plea timestamp mapping is stored separately in the shared folder.
- `/opt/lawdocs/releases` retains small deployment receipts. Only three successful release images are retained. Uploaded release archives are removed by the SSH receiver.
- Previous local deployment evidence is archived on the Mac under `report_workspace-archive/2026-09-18/server-qualification`; it is not on the server or in Git.

## Automatic deployment

A passing main-branch Actions run builds one production image and transports its checksummed archive. The dedicated SSH key can invoke only the release receiver; it cannot run arbitrary shell commands or forward ports. A candidate starts on an isolated temporary store before live traffic switches. New uploads are paused while existing processing drains. Failed activation restores the previous service and commit; persistent jobs stay in place. Post-deploy checks use synthetic jobs and remove only their returned IDs.

Production secrets: `HETZNER_DEPLOY_KEY`, `HETZNER_KNOWN_HOSTS`. Repository variable: `HETZNER_HOST`. The `production` environment allows only main-branch deployments. SHA-pinned actions and hash-locked dependencies are reviewed through pull requests. Changes to host provisioning/receiver scripts are installed with the manual bootstrap workflow.

## Fresh host / bootstrap

Start an authorized Ubuntu host and point the intended DNS name at it. Install the dedicated bootstrap public key from the owner's local SSH files. Add that host's verified SSH host key to the `bootstrap` environment secret `HETZNER_KNOWN_HOSTS`.

Run **Install on a fresh host** in Actions, supplying the hostname/IP, domain, and successful **CI and deployment** run ID. The workflow installs Docker, Caddy, the service account, deploy key, and service definitions, then installs the existing tested artifact. Its artifact is retained for one day; run CI again if it has expired. The bootstrap environment uses its own `HETZNER_BOOTSTRAP_KEY` and permits only main. The workflow is also an idempotent way to update host provisioning on the existing server.

The CI runner performs a clean installation on its disposable Linux host before production deployment, including an intentionally broken release and exact-commit rollback check. It does not create billable Hetzner instances automatically.

## Routine operations

Use `systemctl status lawdocs`, `journalctl -u lawdocs`, and `docker logs lawdocs` for diagnosis. The public `/api/health` response reports the release commit, readiness, active requests, and retention hours. Do not copy old job snapshots into the shared store; that can resurrect expired reports. Local job stores are independent of the server after a point-in-time migration.

The legacy native runtime remains available on the original host as an initial migration fallback; its data paths link to the shared store, so it does not retain a second copy of uploads.
