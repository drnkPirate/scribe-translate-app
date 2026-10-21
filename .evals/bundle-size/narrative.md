# Status

Baseline recorded from v0.1.0. The Windows installer is 317,249,622 bytes and the packaged sidecar reproduces the fixed Parakeet Ultra transcript and French translation exactly.

Three local rounds reduced the unpacked sidecar from 731,991,359 to 653,638,809 bytes (10.7%). The winning package keeps the fixed model revisions, model hashes and inference settings. Its packaged sidecar produces the exact baseline Dutch and French text. A fresh Marian conversion also succeeds with the reduced Transformers package set.

The Windows installer size remains the release gate and must be measured by GitHub Actions before publishing.
