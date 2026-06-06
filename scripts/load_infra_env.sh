#!/bin/bash

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INFRA_FILE="${PV_INFRA_FILE:-${BASE_DIR}/.infra.local}"

if [ -f "$INFRA_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$INFRA_FILE"
  set +a
fi

# Best-effort autodetect for local LAN capabilities.
# Explicit values from env/.infra.local always win.
if command -v ip >/dev/null 2>&1; then
  _pv_default_route="$(ip -o -4 route show to default 2>/dev/null | head -n1 || true)"

  if [ -z "${PV_LAN_IFACE:-}" ]; then
    PV_LAN_IFACE="$(awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}' <<<"${_pv_default_route}")"
    export PV_LAN_IFACE
  fi

  if [ -z "${PV_LAN_CIDR:-}" ] && [ -n "${PV_LAN_IFACE:-}" ]; then
    _pv_addr_cidr="$(ip -o -4 addr show dev "$PV_LAN_IFACE" scope global 2>/dev/null | awk '{print $4; exit}')"
    if [ -n "${_pv_addr_cidr}" ] && command -v python3 >/dev/null 2>&1; then
      PV_LAN_CIDR="$(python3 - <<'PY' "${_pv_addr_cidr}"
import ipaddress
import sys

cidr = sys.argv[1]
print(ipaddress.ip_interface(cidr).network)
PY
)"
    else
      PV_LAN_CIDR="${_pv_addr_cidr}"
    fi
    [ -n "$PV_LAN_CIDR" ] && export PV_LAN_CIDR
  fi

  if [ -z "${PV_LAN_GATEWAY:-}" ]; then
    PV_LAN_GATEWAY="$(awk '{for(i=1;i<=NF;i++) if($i=="via"){print $(i+1); exit}}' <<<"${_pv_default_route}")"
    [ -n "$PV_LAN_GATEWAY" ] && export PV_LAN_GATEWAY
  fi

  if [ -z "${PV_PRIMARY_IP:-}" ]; then
    PV_PRIMARY_IP="$(awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}' <<<"${_pv_default_route}")"
    [ -n "$PV_PRIMARY_IP" ] && export PV_PRIMARY_IP
  fi
fi

if [ -z "${PV_DNS_PRIMARY:-}" ] && [ -r /etc/resolv.conf ]; then
  PV_DNS_PRIMARY="$(awk '/^nameserver / {print $2; exit}' /etc/resolv.conf)"
  [ -n "$PV_DNS_PRIMARY" ] && export PV_DNS_PRIMARY
fi