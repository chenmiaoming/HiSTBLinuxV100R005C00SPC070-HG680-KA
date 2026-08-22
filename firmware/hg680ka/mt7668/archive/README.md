# Archive parts

These files are ordered Base64 chunks of one XZ-compressed tar archive containing only the selected HG-680-KA MT7668 factory firmware files.

Do not consume individual parts directly. Use:

```sh
bash scripts/hg680ka/install-mt7668-stock-firmware.sh <output-directory>
```

The installer concatenates parts in lexical order, decodes/tests the XZ stream, checks the exact file set, and verifies every extracted file against `../SHA256SUMS` before installation.
