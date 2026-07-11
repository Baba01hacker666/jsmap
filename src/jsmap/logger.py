import sys
from datetime import datetime

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[97m"
    GRAY = "\033[90m"
    BG_RED = "\033[41m"
    BG_YLW = "\033[43m"
    BG_GRN = "\033[42m"
    BG_CYN = "\033[46m"
    BG_BLU = "\033[44m"


def banner():
    print(f"""\
{C.MAGENTA}{C.BOLD}
     ██╗███████╗███╗   ███╗ █████╗ ██████╗       ███████╗██╗   ██╗██╗████████╗███████╗
     ██║██╔════╝████╗ ████║██╔══██╗██╔══██╗      ██╔════╝██║   ██║██║╚══██╔══╝██╔════╝
     ██║███████╗██╔████╔██║███████║██████╔╝      ███████╗██║   ██║██║   ██║   █████╗
██   ██║╚════██║██║╚██╔╝██║██╔══██║██╔═══╝       ╚════██║██║   ██║██║   ██║   ██╔══╝
╚█████╔╝███████║██║ ╚═╝ ██║██║  ██║██║           ███████║╚██████╔╝██║   ██║   ███████╗
 ╚════╝ ╚══════╝╚═╝     ╚═╝╚═╝  ╚═╝╚═╝           ╚══════╝ ╚═════╝ ╚═╝   ╚═╝   ╚══════╝
{C.RESET}{C.YELLOW}  Enhanced Modular Suite  ·  Structured Output  ·  ng build Integration{C.RESET}
{C.GRAY}  Phase 1: Download  |  Phase 2: Extract  |  Phase 3: Reconstruct  |  Phase 4: Build{C.RESET}
""")


def _log(prefix, color, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{C.GRAY}[{ts}]{C.RESET} {color}{prefix}{C.RESET} {msg}")


def info(m):
    _log("[*]", C.CYAN, m)


def success(m):
    _log("[+]", C.GREEN, m)


def warn(m):
    _log("[!]", C.YELLOW, m)


def error(m):
    _log("[-]", C.RED, m)


def critical(m):
    print(f"{C.BG_RED}{C.WHITE}[!!]{C.RESET} {C.RED}{C.BOLD}{m}{C.RESET}")


def section(m):
    print(f"\n{C.BOLD}{C.BLUE}{'─' * 68}\n  {m}\n{'─' * 68}{C.RESET}")


def dim(m):
    print(f"{C.GRAY}    {m}{C.RESET}")


def step(n, m):
    print(f"\n{C.BG_CYN}{C.WHITE} PHASE {n} {C.RESET} {C.BOLD}{m}{C.RESET}\n")


def substep(m):
    print(f"  {C.BG_BLU}{C.WHITE} ► {C.RESET} {C.BOLD}{m}{C.RESET}")
