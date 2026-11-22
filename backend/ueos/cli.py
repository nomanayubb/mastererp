"""python -m ueos.cli create-staff EMAIL ROLE [--password P] | sync-registry   (uses UEOS_DATABASE_URL)"""

import argparse
import getpass

from ueos.platform import registry, staff


def main() -> None:
    ap = argparse.ArgumentParser(prog="ueos.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cs = sub.add_parser("create-staff")
    cs.add_argument("email")
    cs.add_argument("role", choices=staff.STAFF_ROLES)
    cs.add_argument("--password")
    sub.add_parser("sync-registry")
    a = ap.parse_args()
    if a.cmd == "create-staff":
        pw = a.password or getpass.getpass("Password (min 12 chars): ")
        print("created staff", staff.create_staff(a.email, pw, a.role))
    else:
        print(registry.sync_manifests())


if __name__ == "__main__":
    main()
