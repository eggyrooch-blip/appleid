#!/bin/bash
# 飞连 MDM 下发脚本：以 root 执行，把 sidecar 装到当前登录用户的用户域。
# 需要随包一起下发：tokscale(二进制)、tokreport.py、com.eggyrooch.tokreport.plist、tokreport.conf
# 用法: sudo ./install.sh <下发包所在目录>
set -euo pipefail

PKG_DIR="${1:-$(dirname "$0")}"

# 找到当前 GUI 登录用户（飞连脚本是 root 跑的，必须装进用户域才能读到该用户的日志）
CONSOLE_USER=$(stat -f%Su /dev/console)
UID_NUM=$(id -u "$CONSOLE_USER")
USER_HOME=$(dscl . -read "/Users/$CONSOLE_USER" NFSHomeDirectory | awk '{print $2}')
AGENTS_DIR="$USER_HOME/Library/LaunchAgents"
PLIST="$AGENTS_DIR/com.eggyrooch.tokreport.plist"

echo "installing for user=$CONSOLE_USER uid=$UID_NUM home=$USER_HOME"

# 1) 二进制与脚本
install -m 0755 "$PKG_DIR/tokscale"      /usr/local/bin/tokscale
install -m 0755 "$PKG_DIR/tokreport.py"  /usr/local/bin/tokreport.py

# 2) 身份配置（飞连应按设备替换好里面的 EMPLOYEE_EMAIL 等）
install -m 0644 "$PKG_DIR/tokreport.conf" /etc/tokreport.conf

# 3) LaunchAgent
install -d -o "$CONSOLE_USER" "$AGENTS_DIR"
install -m 0644 -o "$CONSOLE_USER" "$PKG_DIR/com.eggyrooch.tokreport.plist" "$PLIST"

# 4) 在用户 GUI 域加载（先卸再装，便于升级覆盖）
launchctl bootout   "gui/$UID_NUM" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$PLIST"
launchctl kickstart -k "gui/$UID_NUM/com.eggyrooch.tokreport"

echo "tokreport installed and started."
