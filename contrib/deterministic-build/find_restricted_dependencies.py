#!/usr/bin/env python3
import sys

try:
    import requests
except ImportError as e:
    sys.exit(f"Error: {str(e)}. Try 'sudo python3 -m pip install <module-name>'")


def is_blacklisted(pkg: str, *, pulled_in_by: str) -> bool:
    if pkg == "colorama" and pulled_in_by == "qrcode":
        # colorama 0.4.6+ requires hatchling to build, see https://github.com/spesmilo/electrum/commit/590abec33934a2da41e47ecd9c5f48bdc758aae5
        # qrcode only needs colorama for CLI use, which we don't need
        return True
    return False


def want_restricted_pkg(pkg: str, restriction: str, *, pulled_in_by: str) -> bool:
    #print(f"xxxxx. want_restricted_pkg(). {pkg=}. {restriction=}. {pulled_in_by=}", file=sys.stderr)
    if is_blacklisted(pkg, pulled_in_by=pulled_in_by):
        return False
    # See: https://www.python.org/dev/peps/pep-0496/
    # Hopefully we don't need to parse the whole microlanguage
    if "extra" in restriction and "[" not in pkg:
        return False
    for marker in ["os_name", "platform_release", "sys_platform", "platform_system"]:
        if marker in restriction:
            return True
    return False


for p in sys.stdin.read().split():
    p = p.strip()
    if not p:
        continue
    assert "==" in p, "This script expects a list of packages with pinned version, e.g. package==1.2.3, not {}".format(p)
    p, v = p.rsplit("==", 1)
    try:
        data = requests.get("https://pypi.org/pypi/{}/{}/json".format(p, v)).json()["info"]
    except ValueError:
        raise Exception("Package could not be found: {}=={}".format(p, v))
    try:
        for r in data["requires_dist"]:  # type: str
            if ";" not in r:
                continue
            # example value for "r" at this point: "pefile (>=2017.8.1) ; sys_platform == \"win32\""
            dep, restricted = r.split(";", 1)
            dep = dep.strip()
            restricted = restricted.strip()
            dep_basename = dep.split(" ")[0]
            if want_restricted_pkg(dep, restricted, pulled_in_by=p):
                print(dep_basename, sep=" ", file=sys.stdout)
                print("Installing {} from {} although it is only needed for {}".format(dep, p, restricted), file=sys.stderr)
    except TypeError:
        # Has no dependencies at all
        continue

