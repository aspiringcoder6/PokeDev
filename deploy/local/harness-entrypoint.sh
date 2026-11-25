#!/bin/bash
set -euo pipefail
mkdir -p /app/workspace /app/data
node /app/harness-config.mjs
chown -R node:node /app/workspace /app/data
# The control plane may reach its Docker network and this app, not the old LAN.
iptables -A OUTPUT -d 169.254.169.254/32 -j DROP
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
callback_ip=$(getent ahostsv4 host.docker.internal | awk 'NR == 1 { print $1 }')
if [ -n "$callback_ip" ]; then
  iptables -A OUTPUT -d "$callback_ip/32" -p tcp --dport 7862 -j ACCEPT
fi
iptables -A OUTPUT -m conntrack --ctstate NEW -d 10.0.0.0/8 -j DROP
iptables -A OUTPUT -m conntrack --ctstate NEW -d 192.168.0.0/16 -j DROP
socat TCP-LISTEN:3080,fork,reuseaddr TCP:127.0.0.1:3081 &
exec su -s /bin/bash node -c '
plugin_mount_args=()
for source in /app/plugins-source/*; do
  [ -e "$source" ] || continue
  plugin_name="${source##*/}"
  [ "$plugin_name" = "node_modules" ] && continue
  plugin_mount_args+=(--ro-bind "$source" "/app/plugins/$plugin_name")
done

core_plugin_mount_args=()
core_scope=/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai
for source in "$core_scope"/*; do
  [ -e "$source" ] || continue
  package_name="${source##*/}"
  core_plugin_mount_args+=(--ro-bind "$source" "/app/plugins/node_modules/@deepseek-ai/$package_name")
done
# npm keeps this preset dependency nested; expose it beside the other DSH
# packages so Cordis can resolve the stock web profile inside the sandbox.
sandbox_local_source="$core_scope/dsh-base/node_modules/@deepseek-ai/dsh-sandbox-local"
if [ -d "$sandbox_local_source" ]; then
  core_plugin_mount_args+=(--ro-bind "$sandbox_local_source" "/app/plugins/node_modules/@deepseek-ai/dsh-sandbox-local")
fi

# Use a fresh minimal device tree, not a bind of host devices. Git needs /dev/null.
exec bwrap \
  --dir /app \
  --dev /dev \
  --ro-bind /usr /usr \
  --ro-bind /lib /lib \
  --ro-bind-try /lib64 /lib64 \
  --ro-bind /bin /bin \
  --ro-bind /sbin /sbin \
  --ro-bind-try /etc/alternatives /etc/alternatives \
  --ro-bind /etc/resolv.conf /etc/resolv.conf \
  --ro-bind /etc/ssl /etc/ssl \
  --ro-bind /etc/hosts /etc/hosts \
  --ro-bind /etc/passwd /etc/passwd \
  --ro-bind /etc/group /etc/group \
  --ro-bind /usr/local/lib/node_modules /app/node_modules \
  --ro-bind /usr/local/lib/node_modules /node_modules \
      --setenv DSH_GITHUB_WEBHOOK_SECRET "${DSH_GITHUB_WEBHOOK_SECRET:-}" \
  --dir /tmp --tmpfs /tmp \
  --dir /app/plugins \
  "${plugin_mount_args[@]}" \
  --dir /app/plugins/node_modules \
  --dir /app/plugins/node_modules/@deepseek-ai \
  "${core_plugin_mount_args[@]}" \
  --bind /app/data /app/data \
  --bind /app/workspace /app/workspace \
  --ro-bind-try /app/artifact-source /app/artifact-source \
    --ro-bind-try /app/project-sources /app/project-sources \
  --ro-bind-try /app/project-source /app/project-source \
  --chdir /app/workspace \
  --setenv HOME /app/workspace \
  --setenv PATH "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  --setenv NODE_PATH "/usr/local/lib/node_modules" \
  --unshare-user-try \
  --unshare-pid \
  --unshare-uts \
  --unshare-ipc \
  --new-session \
  --cap-drop ALL \
  --die-with-parent \
  dsh --profile web --patch /app/data/harness.patch.yml --port 3081 --no-open --trusted-host "localhost:3082" "127.0.0.1:3082" "localhost:3081" "127.0.0.1:3081" "harness:3080" "harness" "127.0.0.1" "localhost"
'
