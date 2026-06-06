#!/bin/bash
# Lightweight LAN capability check for production maintenance.
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${BASE_DIR}/scripts/load_infra_env.sh"

DEFAULT_ROUTE="$(ip -o -4 route show to default 2>/dev/null | head -n1 || true)"
LAN_IFACE="${PV_LAN_IFACE:-$(awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}' <<<"${DEFAULT_ROUTE}")}"
LAN_CIDR="${PV_LAN_CIDR:-$(ip -o -4 addr show dev "${LAN_IFACE}" scope global 2>/dev/null | awk '{print $4; exit}') }"
LAN_GW="${PV_LAN_GATEWAY:-$(awk '{for(i=1;i<=NF;i++) if($i=="via"){print $(i+1); exit}}' <<<"${DEFAULT_ROUTE}")}"
DNS_PRIMARY="${PV_DNS_PRIMARY:-$(awk '/^nameserver / {print $2; exit}' /etc/resolv.conf 2>/dev/null)}"

echo "== Netzwerk-Basis =="
echo "iface: ${LAN_IFACE:-unknown}"
echo "cidr:  ${LAN_CIDR:-unknown}"
echo "gw:    ${LAN_GW:-unknown}"
echo "dns:   ${DNS_PRIMARY:-unknown}"
echo

HOST_LIST="${PV_CRITICAL_HOSTS:-}"
if [[ -z "${HOST_LIST}" ]]; then
  HOST_LIST="failover=${PV_FAILOVER_IP:-192.0.2.105},inverter=${PV_INVERTER_IP:-192.0.2.122},wattpilot=${PV_WATTPILOT_IP:-192.0.2.176},primary=${PV_PRIMARY_IP:-192.0.2.181}"
fi

echo "== Kritische Hosts (ICMP Reachability) =="
IFS=',' read -r -a pairs <<<"${HOST_LIST}"
for pair in "${pairs[@]}"; do
  name="${pair%%=*}"
  ip="${pair#*=}"
  if [[ -z "${name}" || -z "${ip}" || "${name}" == "${ip}" ]]; then
    continue
  fi
  if ping -c 1 -W 1 "${ip}" >/dev/null 2>&1; then
    echo "OK    ${name} (${ip})"
  else
    echo "WARN  ${name} (${ip}) nicht erreichbar"
  fi
done

echo
echo "Hinweis: Die Liste stammt aus .infra.local (PV_CRITICAL_HOSTS) und bleibt lokal/gitignored."
