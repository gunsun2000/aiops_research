from __future__ import annotations

import os

from aiops_k8s_agents.control_plane_web import main as _control_plane_main
from aiops_k8s_agents import experiment_bulk_delete as _experiment_bulk_delete  # noqa: F401


DEFAULT_CONTROL_PLANE_PORT = "18180"


def main() -> None:
    """Start the web control plane on the project-specific default port.

    An explicitly supplied PORT environment variable still wins, so research
    servers can choose another port without changing code.
    """
    os.environ.setdefault("PORT", DEFAULT_CONTROL_PLANE_PORT)
    _control_plane_main()


if __name__ == "__main__":
    main()
