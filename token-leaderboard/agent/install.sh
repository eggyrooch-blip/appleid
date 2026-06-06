#!/bin/bash
# 方式一：MDM / 飞连 下发（root 执行，装到当前登录用户的用户域）。
# 下发包需含：collectors/、identity.py、tokreport.py、com.eggyrooch.tokreport.plist、
#            tokreport.conf，以及（可选，COLLECTORS 含 tokscale 时）tokscale 二进制。
# 用法: sudo ./install.sh <下发包目录>
set -euo pipefail

PKG_DIR="${1:-$(dirname "$0")}"
LIB_DIR="/usr/local/lib/tokreport"

CONSOLE_USER=$(stat -f%Su /dev/console)
UID_NUM=$(id -u "$CONSOLE_USER")
USER_HOME=$(dscl . -read "/Users/$CONSOLE_USER" NFSHomeDirectory | awk '{print $2}')
AGENTS_DIR="$USER_HOME/Library/LaunchAgents"
PLIST="$AGENTS_DIR/com.eggyrooch.tokreport.plist"

echo "installing for user=$CONSOLE_USER uid=$UID_NUM"

# 1) 程序（整包，含可插拔采集源）
install -d "$LIB_DIR" "$LIB_DIR/collectors"
install -m 0755 "$PKG_DIR/tokreport.py" "$LIB_DIR/tokreport.py"
install -m 0644 "$PKG_DIR/identity.py"  "$LIB_DIR/identity.py"
install -m 0644 "$PKG_DIR"/collectors/*.py "$LIB_DIR/collectors/"
[ -f "$PKG_DIR/tokscale" ] && {
  install -m 0755 "$PKG_DIR/tokscale" /usr/local/bin/tokscale
  # 去掉下载隔离属性，否则 Gatekeeper 会拦未签名二进制
  xattr -dr com.apple.quarantine /usr/local/bin/tokscale 2>/dev/null || true
} || true

# 2) 配置（飞连按设备替换好 EMPLOYEE_EMAIL 等；不填则自动用 git email）
install -m 0644 "$PKG_DIR/tokreport.conf" /etc/tokreport.conf

# 3) LaunchAgent（用户域才能读到该用户的 ~/.claude、~/.codex）
install -d -o "$CONSOLE_USER" "$AGENTS_DIR"
install -m 0644 -o "$CONSOLE_USER" "$PKG_DIR/com.eggyrooch.tokreport.plist" "$PLIST"

launchctl bootout   "gui/$UID_NUM" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$PLIST"
launchctl kickstart -k "gui/$UID_NUM/com.eggyrooch.tokreport"
echo "tokreport installed and started."
