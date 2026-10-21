# Status

Baseline recorded from v0.1.0. The Windows installer is 317,249,622 bytes and the packaged sidecar reproduces the fixed Parakeet Ultra transcript and French translation exactly.

Three local rounds reduced the unpacked sidecar from 731,991,359 to 653,638,809 bytes (10.7%). The winning package keeps the fixed model revisions, model hashes and inference settings. Its packaged sidecar produces the exact baseline Dutch and French text. A fresh Marian conversion also succeeds with the reduced Transformers package set.

GitHub Actions produced a 281,664,578-byte Windows installer, 35,585,044 bytes (11.2%) below v0.1.0. The Windows installer installed and started successfully in the release smoke test.
