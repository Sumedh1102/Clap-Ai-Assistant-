"""Cross-platform application launcher and closer."""

import platform
import subprocess
import shutil

_SYSTEM = platform.system()  # "Darwin", "Windows", "Linux"


def open_application(app_name: str) -> dict:
    try:
        if _SYSTEM == "Darwin":
            result = subprocess.run(
                ["open", "-a", app_name], capture_output=True, text=True
            )
            if result.returncode != 0:
                # Fallback: try as a command name
                result = subprocess.run(
                    ["open", app_name], capture_output=True, text=True
                )
        elif _SYSTEM == "Windows":
            result = subprocess.run(
                ["start", "", app_name], shell=True, capture_output=True, text=True
            )
        else:  # Linux and others
            cmd = shutil.which(app_name.lower().replace(" ", "-")) or app_name.lower()
            result = subprocess.Popen(
                [cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return {"success": True, "message": f"Launched {app_name}"}

        if result.returncode == 0:
            return {"success": True, "message": f"Opened {app_name}"}
        return {
            "success": False,
            "error": f"{app_name} could not be opened: {result.stderr.strip() or 'application not found'}",
        }
    except FileNotFoundError:
        return {"success": False, "error": f"Application not found: {app_name}"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def close_application(app_name: str) -> dict:
    try:
        if _SYSTEM == "Darwin":
            # Graceful AppleScript quit. The name is passed as an argument, never
            # interpolated into the script, so it cannot inject AppleScript.
            result = subprocess.run(
                ["osascript",
                 "-e", "on run argv",
                 "-e", "set appName to item 1 of argv",
                 "-e", "if application appName is not running then return \"not running\"",
                 "-e", "tell application appName to quit",
                 "-e", "return \"closed\"",
                 "-e", "end run",
                 app_name],
                capture_output=True, text=True,
            )
            if result.returncode == 0 and result.stdout.strip() == "not running":
                return {"success": False, "error": f"{app_name} is not running"}
            if result.returncode != 0:
                # Fallback: exact process-name match only (never -f, which can hit unrelated processes)
                kill = subprocess.run(["pkill", "-x", app_name], capture_output=True, text=True)
                if kill.returncode != 0:
                    return {"success": False, "error": f"{app_name} is not running or could not be closed"}
        elif _SYSTEM == "Windows":
            exe = app_name if app_name.lower().endswith(".exe") else app_name + ".exe"
            result = subprocess.run(
                ["taskkill", "/f", "/im", exe], capture_output=True, text=True
            )
            if result.returncode != 0:
                return {"success": False, "error": result.stderr.strip()}
        else:
            kill = subprocess.run(["pkill", "-x", app_name], capture_output=True)
            if kill.returncode != 0:
                return {"success": False, "error": f"{app_name} is not running or could not be closed"}

        return {"success": True, "message": f"Closed {app_name}"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
