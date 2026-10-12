#!/usr/bin/env bash
# SUPERSEDED — this helper was replaced by the compact single-file Python
# version `deploy_grpc_store.py` in the same directory (and embedded in
# SKILL.md §2 Step 6).  The Python version is shorter, has no nested-heredoc
# quoting traps, fixes PYTHONPATH injection for the functional probe, and is
# safe to re-type when the skill package is not mounted inside the container.
# Do not use this file.  Run:
#   python3 "$(dirname "$0")/deploy_grpc_store.py" --help
echo "ERROR: deploy_grpc_store.sh is superseded - use deploy_grpc_store.py (see SKILL.md §2 Step 6)" >&2
exit 2