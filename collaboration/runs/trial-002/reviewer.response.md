**Bug**: String-prefix check (`str(target).startswith(str(base))`) fails when `base` is a prefix of another directory name (e.g., `/home/user/project` vs `/home/user/project_evil`).

**Counterexample**:
```
root = "/home/user/project"
candidate = "../project_evil/secret.txt"
```
- `base` → `/home/user/project`
- `target` → `/home/user/project_evil/secret.txt`
- `"project_evil/secret.txt".startswith("project")` → **True** (incorrectly passes)

**Fix** (Python 3.9+):
```python
if not target.is_relative_to(base):
    raise ValueError("outside root")
```
Or pre-3.9:
```python
if os.path.commonpath([base, target]) != base:
    raise ValueError("outside root")
```