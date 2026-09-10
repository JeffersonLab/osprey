The virtual accelerator's channel manifest is built from whatever hierarchy
levels a facility's hierarchical channel database declares, not only the
reference facility's `ring`/`system`/`family`/`device`/`field`/`subfield`.
A database with other level names used to stop `osprey build` with
`KeyError: 'ring'`; it now builds, and it declares how its setpoints pair
with their readbacks in a `hierarchy.pairing` block beside `levels` and
`naming_pattern` (which level carries the distinguishing token, and which
token pairs -- `.S`/`M`, `GSET`/`GMES` -- mean setpoint and readback, with an
optional `where` restriction per pair). A database that declares no block
keeps the `SP`/`RB` convention when it has a `subfield` level, and otherwise
pairs nothing, which the build states. Manifest channels now carry `path`
(keyed by the declared levels), `pair_key` and `role` instead of the six
level names; a file-backed manifest in the older six-key schema is still
accepted and normalized on load. The manifest is also no longer a reason to
refuse a build that deploys no virtual accelerator: what could not be built
is reported and the build continues.
