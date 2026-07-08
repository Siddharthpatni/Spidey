"""Safety layer for Spidey.

A local agent with shell access is powerful and dangerous. This module is the
independent guardrail that decides whether a proposed shell command may run.
The point (and the interview talking point) is that these checks live *outside*
the model's context: a poisoned prompt or a confused model cannot edit the policy.

Modes:
  * "ask"     (default) dangerous commands require a human y/N; everything else runs.
  * "enforce"           dangerous commands are blocked outright (good for CI / unattended).
  * "off"               no checks (don't use this on a machine you care about).

File tools (read/write) are separately confined to the working directory via
``within_workdir`` so the agent can't read your SSH keys or write to /etc.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

# (regex, human-readable reason). Matched case-sensitively against the raw command.
DANGEROUS: List[Tuple[str, str]] = [
    (r"\brm\s+-[a-z]*[rf]", "recursive/forced delete (rm -rf)"),
    (r"\brm\s+.*[*/]", "delete of paths or globs"),
    (r"\bmkfs\b", "filesystem format"),
    (r"\bdd\s+if=", "raw disk write (dd)"),
    (r":\s*\(\s*\)\s*\{", "fork bomb"),
    (r">\s*/dev/sd", "write to a raw disk device"),
    (r"\bchmod\s+-R\s+0*777", "world-writable recursive chmod"),
    (r"\bchown\s+-R\b", "recursive chown"),
    (r"(curl|wget)\b[^|]*\|\s*(sudo\s+)?(sh|bash|zsh)", "pipe-to-shell (curl | sh)"),
    (r"\bsudo\b", "privilege escalation (sudo)"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "power-state change"),
    (r"\bgit\s+push\b[^\n]*--force", "git force push"),
    (r"(npm\s+publish|twine\s+upload|cargo\s+publish)", "publishing a package"),
    (r"(\.ssh/|id_rsa|id_ed25519|\.aws/credentials|\.env\b)", "access to secrets/credentials"),
    (r">\s*~?/?\.(bashrc|zshrc|profile|bash_profile)", "shell startup-file modification"),
]


@dataclass
class SafetyConfig:
    mode: str = "ask"                 # "ask" | "enforce" | "off"
    command_timeout: int = 60         # seconds before a command is killed
    extra_deny: List[str] = field(default_factory=list)  # additional regex rules


def check_command(cmd: str, cfg: SafetyConfig) -> Tuple[str, str]:
    """Return a verdict for a shell command: ('allow' | 'ask' | 'deny', reason)."""
    if cfg.mode == "off":
        return "allow", "safety disabled"

    reasons: List[str] = []
    for pat in cfg.extra_deny:
        if re.search(pat, cmd):
            reasons.append(f"custom rule /{pat}/")
    for pat, why in DANGEROUS:
        if re.search(pat, cmd):
            reasons.append(why)

    if reasons:
        reason = "; ".join(dict.fromkeys(reasons))  # de-dupe, keep order
        return ("deny" if cfg.mode == "enforce" else "ask"), reason
    return "allow", "no dangerous pattern matched"


def within_workdir(workdir: Path, target: Path) -> bool:
    """True if ``target`` resolves to a path inside ``workdir`` (blocks ../ escapes)."""
    try:
        target.resolve().relative_to(workdir.resolve())
        return True
    except ValueError:
        return False
