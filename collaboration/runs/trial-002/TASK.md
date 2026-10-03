# Synthetic collaboration qualification

Created: 2026-10-02. No personal, confidential or production data.

The function in bounded.py must return the resolved path when it is the root
itself or a descendant of root. Reject sibling-prefix paths and traversal
outside root with ValueError. Existing symlinks must be resolved before the
containment check. This is only a path check; it does not promise race-free
filesystem access. Use Python standard library only.

Coder owns bounded.py only. Reviewer is read-only. Tester owns
test_bounded.py only. Codex executes tests and controls acceptance.
Never infer production or T-001 acceptance from this fixture.
