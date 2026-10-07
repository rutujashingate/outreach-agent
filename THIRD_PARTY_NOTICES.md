# Third-party notices

The application code is licensed under the repository's [MIT License](LICENSE). Dependencies retain their own licenses.

## Playwright browser sandbox profile

`docker/seccomp_profile.json` is copied without modification from [Microsoft Playwright v1.63.0](https://github.com/microsoft/playwright/blob/v1.63.0/utils/docker/seccomp_profile.json). Copyright Microsoft Corporation. It is provided under the Apache License, Version 2.0; the upstream [license is included here](docker/PLAYWRIGHT_LICENSE).

This profile extends Docker's default system-call restrictions to allow Chromium sandbox user namespaces. Its inclusion does not change the license of this project's original code or documentation.
