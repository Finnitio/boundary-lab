"""Notification: show a Windows toast when Claude Code needs attention (no-op elsewhere)."""

import json
import os
import subprocess
import sys
from xml.sax.saxutils import escape

APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
SCRIPT = """
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($env:TOAST_XML)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:TOAST_APP).Show($toast)
"""


def main():
    if sys.platform != "win32":
        return
    message = json.load(sys.stdin).get("message", "Claude Code needs your attention")
    xml = (
        "<toast><visual><binding template='ToastGeneric'>"
        f"<text>Claude Code - boundary-lab</text><text>{escape(message)}</text>"
        "</binding></visual></toast>"
    )
    env = {**os.environ, "TOAST_XML": xml, "TOAST_APP": APP_ID}
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", SCRIPT],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


if __name__ == "__main__":
    main()
