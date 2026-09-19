#!/usr/bin/env bash
# Idempotent host setup. Run as root from a verified release checkout.
set -euo pipefail
SITE=${1:-lawdocs.dock108.dev}
[[ "$SITE" =~ ^[a-zA-Z0-9.:/-]+$ ]] || exit 2
ROOT=/opt/lawdocs
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq caddy python3 curl
if ! command -v docker >/dev/null; then apt-get install -y -qq docker.io; fi
id lawdocs >/dev/null 2>&1 || useradd --system --home-dir "$ROOT" --shell /usr/sbin/nologin lawdocs
id lawdocs-deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash lawdocs-deploy
install -d -o lawdocs -g lawdocs "$ROOT/shared" "$ROOT/shared/crash" "$ROOT/shared/plea"
install -d -o lawdocs-deploy -g lawdocs-deploy "$ROOT/incoming"
install -d "$ROOT/releases" /etc/lawdocs
# The shared folders are never inside a release and are never restored on rollback.
install -m 755 deploy/release.py /usr/local/sbin/lawdocs-release
install -m 755 deploy/receive.py /usr/local/bin/lawdocs-receive
install -m 644 deploy/container.service /etc/systemd/system/lawdocs.service.next
printf 'lawdocs-deploy ALL=(root) NOPASSWD: /usr/local/sbin/lawdocs-release\n' > /etc/sudoers.d/lawdocs-deploy
chmod 440 /etc/sudoers.d/lawdocs-deploy
printf '%s\n' "$SITE" > /etc/lawdocs/site
cat > /etc/caddy/lawdocs.Caddyfile <<EOF
$SITE {
    request_body {
        max_size 65MB
    }
    reverse_proxy 127.0.0.1:8795
    header X-Robots-Tag "noindex, nofollow"
}
EOF
# Existing installations are migrated explicitly before this script; never overwrite unrelated sites.
if ! grep -q 'import /etc/caddy/lawdocs.Caddyfile' /etc/caddy/Caddyfile; then
    printf '\nimport /etc/caddy/lawdocs.Caddyfile\n' >> /etc/caddy/Caddyfile
fi
caddy validate --config /etc/caddy/Caddyfile
systemctl enable --now docker caddy
systemctl reload caddy
if [ -f deploy/deploy-key.pub ]; then
    install -d -m 700 -o lawdocs-deploy -g lawdocs-deploy /home/lawdocs-deploy/.ssh
    printf 'restrict,command="/usr/local/bin/lawdocs-receive" %s\n' "$(cat deploy/deploy-key.pub)" > /home/lawdocs-deploy/.ssh/authorized_keys
    chown lawdocs-deploy:lawdocs-deploy /home/lawdocs-deploy/.ssh/authorized_keys
    chmod 600 /home/lawdocs-deploy/.ssh/authorized_keys
fi
