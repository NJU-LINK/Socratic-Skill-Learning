"""Keep Selenium's driver selection deterministic in the benchmark image.

The official Selenium Manager binary is unavailable on Linux/ARM64.  The
curated image already installs a version-matched Chromium driver, so tests
that construct ``Service()`` without a path should use that fixed binary.
"""

from __future__ import annotations

from selenium.webdriver.chrome.service import Service


_service_init = Service.__init__


def _init_with_system_driver(
    self: Service,
    executable_path: str | None = None,
    *args: object,
    **kwargs: object,
) -> None:
    _service_init(
        self,
        executable_path=executable_path or "/usr/bin/chromedriver",
        *args,
        **kwargs,
    )


Service.__init__ = _init_with_system_driver
