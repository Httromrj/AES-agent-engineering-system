# VPS operations preparation

The research cycle is a bounded, one-shot Python command. It fetches only the HTTPS feeds in `research/sources.json`, times out after 15 seconds per source, limits each response to 2 MB and each feed to 50 entries, writes digests and audit metadata to AES state storage, and prevents overlapping runs with an OS lock. It does not access project files, call a model, change Git state, or deploy code.

## Required preflight before installing anything

Run the inventory helper on the target host through the already approved access method:

```bash
python3 scripts/vps_preflight.py --output /tmp/aes-vps-inventory.json
```

Review the report locally before sharing it. It reports OS/runtime, CPU count, memory, disk capacity, running service names, listening TCP sockets, container tools, and available cgroup limits. It does not query Google Cloud metadata, credentials, IAM, firewall rules, backups, billing, or service logs. Gather those separately through the authorized Google Cloud control plane. Do not paste credentials into the report.

Before installation, identify the project and VM, approved SSH or IAP access, OS support, CPU/RAM/disk headroom, network egress and inbound firewall, existing workloads, service manager, backup/restore path, and responsible owner. Estimate resource bounds from the measured host and a pilot run. Do not expose a gateway or administrative API publicly. The inventory helper only reads state; it does not install or alter services.

## Example systemd schedule (template only)

After preflight and review, an operator may adapt these files. Replace paths and account names with the verified host layout. Create the state directory with owner-only access, configure `AES_STATE_DIR`, set CPU/memory limits from measured capacity, and verify restore behavior before enabling the timer.

`aes-research.service`:

```ini
[Unit]
Description=AES scheduled innovation research
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=aes
Group=aes
WorkingDirectory=/opt/aes-agent-engineering-system
Environment=AES_STATE_DIR=/var/lib/aes-agent-engineering-system
ExecStart=/usr/bin/python3 scripts/innovation.py research --per-source 10
RuntimeMaxSec=15min
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
ReadWritePaths=/var/lib/aes-agent-engineering-system
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
```

`aes-research.timer`:

```ini
[Unit]
Description=Weekly AES research cycle

[Timer]
OnCalendar=weekly
Persistent=true
RandomizedDelaySec=30min
Unit=aes-research.service

[Install]
WantedBy=timers.target
```

The repository intentionally does not enable this timer or install these files. First confirm available resources, set service CPU and memory limits, inspect the diff, and test a manual run under the dedicated account. A timer starts research only; review and adoption of recommendations remain governed by the consumer project and human approval.

## Coolify deployment path

Coolify can deploy a GitHub-backed application and run recurring commands inside its running container. This repository does not yet include a production container definition, so do not point Coolify at the repository root and assume it is ready to deploy. First add and review a dedicated, unprivileged runtime definition with Python and this repository's source; keep the runtime separate from any public-facing application.

Once that runtime is reviewed and deployed:

1. Connect the AES GitHub repository, select the intended branch, choose the Dockerfile build strategy, set Base Directory to the repository root, and Dockerfile Location to `deployment/coolify/Dockerfile`.
2. Do not configure a public domain or exposed port for the research runner. Do not add provider API keys; this cycle uses public HTTPS feeds and makes no model calls.
3. Mount persistent storage at `/var/lib/aes-agent-engineering-system` and set `AES_STATE_DIR` to that path. Container-local state is lost when Coolify replaces a container.
4. Add a Coolify Scheduled Task named `AES weekly innovation research`, with command `python scripts/innovation.py research --per-source 10`, schedule `0 9 * * 1`, and a timeout sized after a manual run. Set the server timezone to the intended local timezone before relying on that schedule.
5. Run the task once manually and inspect its execution status and output in Coolify. Confirm the dated digest and run metadata are present in the mounted state volume. Configure and test a backup of that volume outside the VPS.
6. Keep GitHub auto-deploy limited to reviewed changes on the selected branch. A scheduled scan/research run does not approve proposals, edit consumer repositories, or deploy updates to them.

Coolify scheduled tasks require the application container to be running, use the deployment server's timezone, and record execution output. Review the current Coolify documentation for the exact controls and behavior: [scheduled tasks](https://coolify.io/docs/applications/operations/scheduled-tasks), [Dockerfile applications](https://coolify.io/docs/applications/builds/dockerfile), and [persistent storage and backups](https://coolify.io/docs/applications/operations/overview).

The Coolify dashboard and connected GitHub repository are not accessible from this workspace, and the VPS has not been inventoried. Therefore no Coolify resource, deployment, schedule, volume, or server configuration has been created or changed. Complete the read-only VPS preflight through an approved Coolify terminal/session before choosing container limits or installing the runner.
