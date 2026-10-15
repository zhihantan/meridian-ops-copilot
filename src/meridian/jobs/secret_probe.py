"""Secret read probe (T08): read a Unity Catalog secret as the job's identity, print its fingerprint.

Shows that a rotated value is picked up on the next run with no code, config or deploy change. The
value itself is never printed or logged.

    secret_probe.py --catalog C --bronze-schema S --secret <catalog>.secrets.t08_probe
"""

from __future__ import annotations

import sys
from pathlib import Path

# Serverless Python file tasks run without __file__, so the bundle passes --src-dir.
sys.path.insert(0, sys.argv[sys.argv.index("--src-dir") + 1] if "--src-dir" in sys.argv
                else str(Path(__file__).resolve().parents[2]))

from meridian.jobs.common import fingerprint, parser, read_uc_secret


def main() -> None:
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--secret", required=True, help="catalog.schema.name")
    args = p.parse_args()
    value = read_uc_secret(args.secret)
    if value is None:
        raise SystemExit(f"{args.secret} is not readable by this job's identity")
    print(f"read {args.secret}: fingerprint {fingerprint(value)} (run {args.run_id})")


if __name__ == "__main__":
    main()
