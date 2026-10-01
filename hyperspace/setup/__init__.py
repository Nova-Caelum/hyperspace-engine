"""hyperspace.setup — provisioning behind the `hyperspace-setup` skill and
`hyperspace doctor` (row T5.1)."""
# `python -m hyperspace.setup` imports this package before `__main__`, and the
# import below reaches `tomllib` — so on a Python older than 3.11 the guard has
# to run here, or the traceback comes first.
from .._pyfloor import require_python

require_python()

from .provision import (  # noqa: E402
    check_python,
    doctor,
    probe_judges,
    provision,
    provision_and_report,
    provision_env,
    select_judge,
    write_launcher,
)

__all__ = [
    "check_python",
    "doctor",
    "probe_judges",
    "provision",
    "provision_and_report",
    "provision_env",
    "select_judge",
    "write_launcher",
]
