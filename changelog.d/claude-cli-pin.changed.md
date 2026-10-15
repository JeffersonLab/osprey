The pinned Claude Code CLI moves to 2.1.294, the first build that knows Haiku
5.5: older builds, npm's `stable` 2.1.287 among them, price it as an unknown
model and overstate a run's cost enough for a per-run budget to end it after
one turn. The dispatch worker picks it up when its image is rebuilt.
