#!/bin/bash

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INFRA_FILE="${PV_INFRA_FILE:-${BASE_DIR}/.infra.local}"

if [ -f "$INFRA_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$INFRA_FILE"
  set +a
fi