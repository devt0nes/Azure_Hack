"""
Compatibility shim for the canonical shared agent catalog.

This file intentionally loads the repo-level `shared/agent_catalog.py` by file
path under a different module name to avoid circular imports when this shim is
itself imported as `agent_catalog`.
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_BACKEND_SHARED_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _BACKEND_SHARED_DIR.parent.parent
_CANONICAL_CATALOG = _REPO_ROOT / "shared" / "agent_catalog.py"

_SPEC = spec_from_file_location("canonical_shared_agent_catalog", _CANONICAL_CATALOG)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Could not load canonical agent catalog from {_CANONICAL_CATALOG}")

_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

AGENT_CATALOG = _MODULE.AGENT_CATALOG
build_builtin_agent_catalog = _MODULE.build_builtin_agent_catalog
normalize_agent_document = _MODULE.normalize_agent_document

