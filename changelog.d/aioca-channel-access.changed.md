The EPICS connector speaks Channel Access through aioca instead of pyepics,
on one long-lived event loop per process, so a process that also uses aioca
(ophyd-async devices, for example) shares one CA context instead of two. Every
read now asks the IOC, so `fresh_reads` no longer changes anything. A write to
a channel that never connects reports that nothing was sent. A second
`connect()` in the same process that would point Channel Access at a
different gateway is refused rather than left on the first one.
