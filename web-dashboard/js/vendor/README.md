# Vendored browser libraries

| File | Package | Licence | Source and integrity |
|---|---|---|---|
| `qrcode-generator-2.0.4.mjs` | [`qrcode-generator`](https://www.npmjs.com/package/qrcode-generator) 2.0.4 by Kazuhiko Arase (published 7 Aug 2025) | MIT (header in the file) | `dist/qrcode.mjs` from `https://registry.npmjs.org/qrcode-generator/-/qrcode-generator-2.0.4.tgz`. The tarball matched the registry integrity `sha512-mZSiP6RnbHl4xL2Ap5HfkjLnmxfKcPWpWe/c+5XxCuetEenqmNFf1FH/ftXPCtFG5/TDobjsjz6sSNL0Sr8Z9g==`. File SHA-256 `ea91d7118a5395289170da848b7c6758b996163bfbccf312591ab65a4911b7c0`. Unmodified |

The QR library runs entirely in the browser. It makes no network requests, so no QR-generation service ever receives the destination URL. `tests/web.test.mjs` pins the SHA-256 above, and `tests/test_qr_destination.py` decodes the generated code with OpenCV.
