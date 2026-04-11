#!/bin/bash
set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_NAME="pv-monthly-pdf-report.service"
TIMER_NAME="pv-monthly-pdf-report.timer"

echo "=== Installiere monatlichen PDF-Mailversand ==="

echo "→ Service-Datei schreiben..."
sudo tee "/etc/systemd/system/${SERVICE_NAME}" > /dev/null <<EOF
[Unit]
Description=PV-System Monthly PDF Report Mailer
After=network-online.target pv-collector.service
Wants=network-online.target

[Service]
Type=oneshot
User=admin
WorkingDirectory=${BASE}
ExecStart=/usr/bin/python3 ${BASE}/scripts/monthly_pdf_report.py
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
TimeoutStartSec=900
StandardOutput=journal
StandardError=journal
EOF

echo "→ Timer-Datei schreiben..."
sudo tee "/etc/systemd/system/${TIMER_NAME}" > /dev/null <<'EOF'
[Unit]
Description=PV-System Monthly PDF Report Timer

[Timer]
OnCalendar=monthly
Persistent=true
RandomizedDelaySec=15m

[Install]
WantedBy=timers.target
EOF

echo "→ systemd reload"
sudo systemctl daemon-reload

echo "→ Timer aktivieren"
sudo systemctl enable --now "${TIMER_NAME}"

echo "\n=== Status ==="
systemctl status "${SERVICE_NAME}" --no-pager | head -15 || true
echo ""
systemctl status "${TIMER_NAME}" --no-pager | head -15 || true
echo ""
systemctl list-timers "${TIMER_NAME}" --no-pager || true

echo "\n✓ Fertig."
echo "Manueller Test (ohne Mail):"
echo "  python3 ${BASE}/scripts/monthly_pdf_report.py --dry-run --verbose"
echo "Manueller Versand:"
echo "  python3 ${BASE}/scripts/monthly_pdf_report.py --verbose"
