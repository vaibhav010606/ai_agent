import os
import subprocess
from config import BANNED_COMMAND_PATTERNS


def check_safety(command: str) -> tuple[bool, str]:
    """
    Checks if the command contains any banned patterns.
    Returns (is_safe, reason).
    """
    cmd_lower = command.lower()
    for pattern in BANNED_COMMAND_PATTERNS:
        if pattern in cmd_lower:
            return False, f"Command matches banned pattern: '{pattern}'"
    return True, ""


def execute_linux_command_direct(command: str) -> str:
    """
    Executes a Linux shell command and returns stdout + stderr as a string.
    Injects DISPLAY and XAUTHORITY so GUI apps can be launched.
    """
    is_safe, reason = check_safety(command)
    if not is_safe:
        return f"SAFETY VIOLATION: Execution blocked. {reason}"

    # Ensure sudo commands are non-interactive (never hang waiting for password)
    if command.strip().startswith("sudo ") and "-n" not in command:
        command = command.replace("sudo ", "sudo -n ", 1)

    # Inherit the current environment and inject display variables for GUI support
    env = os.environ.copy()
    
    # Prepend custom agent_bin to PATH
    agent_bin = os.path.abspath(os.path.join(os.path.dirname(__file__), "agent_bin"))
    env["PATH"] = f"{agent_bin}:{env.get('PATH', '')}"
    
    if "DISPLAY" not in env:
        env["DISPLAY"] = ":0"
    if "XAUTHORITY" not in env:
        # Try common locations for the Xauthority file
        home = os.path.expanduser("~")
        for candidate in [f"{home}/.Xauthority", f"/run/user/1000/gdm/Xauthority"]:
            if os.path.exists(candidate):
                env["XAUTHORITY"] = candidate
                break

    # GUI app launches should be backgrounded so they don't block the agent
    gui_keywords = ["firefox", "gedit", "nautilus", "code", "chromium",
                    "vlc", "gimp", "thunar", "mousepad", "xterm", "konsole",
                    "nemo", "libreoffice", "eog", "evince", "rhythmbox"]
    is_gui = any(kw in command.lower() for kw in gui_keywords)
    if is_gui and not command.strip().endswith("&"):
        command = command.strip() + " &"

    # Use a longer timeout for package manager commands
    pkg_cmds = ["apt", "apt-get", "snap", "dnf", "yum", "pacman", "brew"]
    timeout = 120 if any(p in command for p in pkg_cmds) else 30

    try:
        result = subprocess.run(
            command,
            shell=True,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env=env
        )

        output = result.stdout.strip()
        error = result.stderr.strip()
        response = ""

        if result.returncode == 0:
            response += "Command succeeded (exit code 0).\n"
        else:
            response += f"Command failed (exit code {result.returncode}).\n"

        if output:
            response += f"STDOUT:\n{output}\n"
        if error:
            response += f"STDERR:\n{error}\n"
        if not output and not error:
            response += "No output generated."

        return response.strip()

    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout} seconds."
    except Exception as e:
        return f"Failed to execute command. Python Error: {str(e)}"
