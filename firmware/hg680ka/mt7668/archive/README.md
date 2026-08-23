# MT7668 stock firmware archive

The firmware payload is stored directly as:

```text
mt7668-stock-firmware.tar.xz
```

Expected archive properties:

```text
size   595036 bytes
sha256 36c59eab1c2bf37ad99bf8205fba45d15835858fb84e568c3c4a4344564e67f8
```

The archive contains only the selected HG-680-KA MT7668 factory firmware files. It is small enough to keep directly in normal Git; Git LFS and split Base64 parts are not used.

Use:

```sh
bash scripts/hg680ka/install-mt7668-stock-firmware.sh <output-directory>
```

The installer verifies the archive's exact byte size and SHA-256 before testing the XZ/tar stream, extracting it, checking the exact file set, and verifying every extracted file against `../SHA256SUMS`.
