#!/bin/bash
# =============================================================
# install_steuerbox_proxy.sh — nginx HTTPS-Reverse-Proxy fuer die
# Steuerbox (Rolle E) einrichten. NUR Primary.
#
#   extern 11933 (ssl, LAN) -> intern 127.0.0.1:11934 (Flask)
#
# Idempotent: Cert wird nur erzeugt, wenn nicht vorhanden.
# =============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Rollen-Guard: auf Failover nichts tun
source "$SCRIPT_DIR/role_guard.sh" 2>/dev/null || { echo "role=failover -> skip"; exit 0; }

CRT=/etc/ssl/certs/steuerbox.crt
KEY=/etc/ssl/private/steuerbox.key
SITE_SRC="$REPO_ROOT/config/nginx/steuerbox.conf"
SITE_DST=/etc/nginx/sites-available/steuerbox

LAN_IP="$(hostname -I | awk '{print $1}')"
HOSTN="$(hostname)"

echo "== Steuerbox-Proxy Setup auf $HOSTN ($LAN_IP) =="

# 1) Self-signed Cert (LAN, self-signed) — nur falls fehlend
if [ ! -f "$CRT" ] || [ ! -f "$KEY" ]; then
    echo "-> erzeuge self-signed Zertifikat (CN=steuerbox.pv.local)"
    sudo openssl req -x509 -nodes -newkey rsa:2048 \
        -keyout "$KEY" -out "$CRT" -days 3650 \
        -subj "/CN=steuerbox.pv.local" \
        -addext "subjectAltName=DNS:steuerbox.pv.local,DNS:${HOSTN},IP:${LAN_IP},IP:127.0.0.1"
    sudo chmod 600 "$KEY"
    sudo chmod 644 "$CRT"
else
    echo "-> Zertifikat vorhanden, behalte es bei"
fi

# 2) nginx-Site installieren (LAN-CIDR aus infra ableiten)
LAN_CIDR="${PV_LAN_CIDR:-$(echo "$LAN_IP" | sed 's/\.[0-9]*$/.0\/24/')}"
echo "-> installiere nginx-Site (11933 ssl -> 127.0.0.1:11934), LAN=${LAN_CIDR}"
sudo cp "$SITE_SRC" "$SITE_DST"
sudo sed -i "s#__LAN_CIDR__#${LAN_CIDR}#g" "$SITE_DST"
sudo ln -sf "$SITE_DST" /etc/nginx/sites-enabled/steuerbox

# 3) Stale NQ-Proxy (Alt-Rolle des Pi5) entfernen, falls vorhanden
if [ -L /etc/nginx/sites-enabled/nq-proxy ]; then
    echo "-> entferne stale nq-proxy Site (Alt-Rolle NQ)"
    sudo rm -f /etc/nginx/sites-enabled/nq-proxy
fi

# 4) Test + Reload
echo "-> nginx -t"
sudo nginx -t
sudo systemctl reload nginx
echo "== fertig. Test: curl -k https://$LAN_IP:11933/api/ops/health =="
