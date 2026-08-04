#!/bin/bash
# ============================================================
# scripts/pv_fix_locale.sh — System-Locale auf de_DE.UTF-8 vereinheitlichen.
#
# Behebt die WURZEL des latin-1-Bugs (Umlaute/→ crashen, Python fsencoding=iso8859-1):
#   Ursache war `LC_ALL=de_DE` in /etc/default/locale (Bastelei aus der aider-Phase).
#   `LC_ALL` ueberschreibt ALLE Kategorien, und `de_DE` (ohne .UTF-8) = ISO-8859-1.
#   Zusaetzlich war de_DE.UTF-8 gar nicht erzeugt.
#
# Vereinfachung (bewusst): genau EINE Variable `LANG=de_DE.UTF-8`, KEIN LC_ALL,
# KEINE per-Kategorie-Overrides. de_DE.UTF-8 + en_US.UTF-8 werden erzeugt
# (en_US, weil SSH-Clients haeufig `LANG=en_US.UTF-8` forwarden — AcceptEnv/SendEnv).
#
# Idempotent; auf allen 4 Pis anwendbar. Volle Wirkung fuer laufende Dienste erst
# nach Reboot (Manager-Env wird zusaetzlich sofort gesetzt).
# ============================================================
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Bitte als root ausfuehren:  sudo bash $0" >&2
  exit 1
fi

echo "=== Locale-Fix auf $(hostname) ==="

# 1. UTF-8-Locales erzeugen
sed -i 's/^# *\(de_DE\.UTF-8 UTF-8\)/\1/; s/^# *\(en_US\.UTF-8 UTF-8\)/\1/' /etc/locale.gen
locale-gen

# 2. Sauberer, EINZIGER System-Default: nur LANG (kein LC_ALL-Hammer, keine Overrides)
cat > /etc/default/locale <<'EOF'
# PV-System: eine einheitliche UTF-8-Locale (scripts/pv_fix_locale.sh).
# Bewusst NUR LANG — kein LC_ALL (ueberschreibt sonst alles) und keine per-
# Kategorie-Overrides. de_DE.UTF-8 liefert deutsche Formate in UTF-8.
LANG=de_DE.UTF-8
EOF

# 3. systemd-Dienste: persistent LANG=de_DE.UTF-8 (system.conf.d ueberlebt Reboot).
#    Login + Cron lesen /etc/default/locale bereits via pam_env; Dienste erben PID1-Env,
#    das ohne DefaultEnvironment sonst inkonsistent bliebe.
install -d /etc/systemd/system.conf.d
cat > /etc/systemd/system.conf.d/10-pv-locale.conf <<'EOF'
[Manager]
DefaultEnvironment=LANG=de_DE.UTF-8
EOF
systemctl daemon-reexec
systemctl set-environment LANG=de_DE.UTF-8
systemctl unset-environment LC_ALL LANGUAGE 2>/dev/null || true

echo "OK: Locale vereinheitlicht auf de_DE.UTF-8 (LC_ALL entfernt)."
echo "--- /etc/default/locale ---"
sed 's/^/    /' /etc/default/locale
echo "--- Python fsencoding (frische Env) ---"
env -u LC_ALL -u LANGUAGE LANG=de_DE.UTF-8 python3 -c "import sys; print('   ', sys.getfilesystemencoding())"
echo "Hinweis: laufende SSH-Session + Dienste erst nach Reconnect/Reboot voll wirksam."
