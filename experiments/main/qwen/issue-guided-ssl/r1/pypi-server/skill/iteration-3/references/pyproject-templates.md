# pyproject.toml Templates Reference

## 1. Src-layout with setuptools (most common)

```toml
[build-system]
requires = ["setuptools>=64", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "my-package"
version = "1.0.0"
description = "My package"
requires-python = ">=3.8"

[tool.setuptools.packages.find]
where = ["src"]
```

File structure:
```
/app/
├── pyproject.toml
└── src/
    └── my_package/
        ├── __init__.py
        └── module.py
```

## 2. Flat layout with setuptools

```toml
[build-system]
requires = ["setuptools>=64", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "my-package"
version = "1.0.0"

[tool.setuptools.packages.find]
where = ["."]
```

File structure:
```
/app/
├── pyproject.toml
└── my_package/
    ├── __init__.py
    └── module.py
```

## 3. Explicit packages list (no auto-discovery)

When auto-discovery fails or you need precise control:

```toml
[tool.setuptools]
packages = ["my_package", "my_package.submodule"]
```

Or for src-layout:
```toml
[tool.setuptools]
packages = ["my_package"]
package-dir = {"" = "src"}
```

## 4. Package data (non-Python files)

```toml
[tool.setuptools.package-data]
"my_package" = ["data/*.json", "templates/*.html"]
```

## 5. Multiple packages in one project

```toml
[tool.setuptools.packages.find]
where = ["src"]
include = ["my_package*", "my_utils*"]
```

## 6. Legacy setup.py compatibility

If the project uses setup.py, add minimal pyproject.toml:
```toml
[build-system]
requires = ["setuptools>=64", "wheel"]
build-backend = "setuptools.build_meta"
```

The setup.py handles metadata; pyproject.toml just declares the build system.

## 7. Hatchling backend

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "my-package"
version = "1.0.0"

[tool.hatch.build.targets.wheel]
packages = ["src/my_package"]
```

## 8. Flit backend

```toml
[build-system]
requires = ["flit_core>=3.2"]
build-backend = "flit_core.buildapi"

[project]
name = "my_package"
version = "1.0.0"
```

Flit auto-discovers from the module name matching the project name.

## Common Pitfalls

1. **Missing `where = ["src"]`** → empty wheel for src-layout projects
2. **Package name vs import name** → distribution name `my-package` maps to import `my_package` (PEP 503 normalization: hyphens → underscores)
3. **Missing `__init__.py`** → directory not recognized as a package
4. **Version mismatch** → ensure pyproject.toml version matches what you install
5. **Namespace packages** → if using `pkgutil` or `pkg_resources` namespace style, discovery works differently
