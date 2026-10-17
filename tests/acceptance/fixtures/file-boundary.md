# File boundary fixture

This fixture is for T-009 only. It must use a new temporary directory and
self-created, non-personal sample files. Do not point it at a real home,
workspace, or production data directory.

The fixture must contain:

- `sandbox_root/.mcp-hub-acceptance` with the exact text
  `isolated-test-environment`;
- an actual `file_allowed_root` directory below `sandbox_root`;
- an `outside_sentinel` file below `sandbox_root` but outside
  `file_allowed_root`;
- four real tool-call cases: an allowed path, an outside path, a traversal
  path, and a symlink path. The three denied cases must each include their
  observed denial text in `denied_contains`.

The file MCP process must receive only `file_allowed_root` in its own startup
arguments or equivalent execution policy. The Hub UI text is not a security
boundary. Before running AT-009, verify that the process rejects directory
escape, `..` traversal, and a symlink that resolves outside the allowed root;
then compare the sentinel hash before and after the calls.
