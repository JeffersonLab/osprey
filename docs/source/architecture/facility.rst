:orphan:

.. _architecture-facility:

========================
The Facility Description
========================

.. admonition:: Draft for review
   :class: warning

   Describes main plus the pyAML integration branch; the dashed parts exist
   only on that branch.

The facility description is everything a deployment knows about its machine:
which channels exist and how they are organised, how its devices relate, what
its procedures say, how to simulate it, how to measure it, and what may be
written. None of it is built into OSPREY. A facility supplies it as files under
``data/``, plus one rule under ``rules/`` at the profile root. A file is
optional unless the part that reads it is deployed: a virtual accelerator, for
example, refuses to start without its machine seeds, state channels, limits and
wiring. ``osprey build`` copies ``data/`` into ``build/``, derives the parts
marked in teal and renders the agent's files. The agent reaches most parts
through an MCP server; the identity rule and the ontology's terminology tables
reach it through its prompts instead.

.. raw:: html
   :file: ../_diagrams/facility-map.html

Five things are worth reading off the map.

**The channel namespace comes from one of two places.** In the file-backed
channel-finder modes (``in_context``, ``hierarchical``, ``middle_layer``) it is
the channel database. In graph mode, which the control-assistant preset uses
by default (``channel_finder_mode: graph``), build stages no channel database:
the channels come from the TTL corpus. The deployment runs one channel-finder
server, and the pipeline chooses its module.

**The TTL corpus reaches the graph at deploy, not at build.** The file named by
``services.graphdb.ttl_path`` (the preset points it at
``data/demo_machine.ttl``) is indexed into a DuckDB keyword index at build, in
graph mode, and seeded into Neo4j at the first deploy, into an empty store only.
A new or changed TTL does not reach a running store on redeploy; ``osprey
knowledge seed-graph`` reseeds it. A TTL is generated in one of two ways, and
neither runs at build: ``osprey mml emit`` writes ``<token>.ttl`` from the
export, and ``osprey knowledge build-ttl`` writes one from the hierarchical
channel database, the ``in_context`` descriptions and ``channel_limits.json``.
Either way the ontology types the devices at that moment; ``build-ttl`` uses the
table passed as ``--ontology`` and otherwise the packaged demo table. After
build the ontology's only reader is the renderer of the agents' terminology
tables. A written TTL takes effect once ``ttl_path`` points at it.

**The simulator has its own inputs.** The virtual accelerator's manifest is
built from the channel tier files (or, in a graph-only tree, the graph index),
the machine seeds, ``machine_state_channels.json``, the channel limits and the
pyat-coupled part of the wiring. The wiring ties channels to elements of the
lattice, and the container runs that lattice only when ``VA_LATTICE`` is set,
which build writes into ``.env``. The channel limits also clamp what the
simulator accepts. The pyAML configuration refers to the same lattice, so a
measurement on the simulator runs against the model it serves. The agent's
lattice tools and the pyat-specialist do not use this lattice: ``lattice_init``
loads whatever path the agent passes, and the pyat-specialist computes on the
bundled demo ring (``build_ring()``).

**A Middle Layer export can supply most of it at once.** ``osprey mml import``
files the Matlab export into ``data/mml/`` (``ao.json``, ``ad.json``, and from a
2.0 export also ``va.json``, ``response.json`` and the lattice decks).
``osprey mml map --init`` writes ``data/mml/mapping.yaml``, which you complete
by hand. ``osprey mml emit`` then reads ``data/mml/`` and writes the channel
database, the ontology, the TTL corpus, the knowledge pages and, from a 2.0
export only, the lattice, wiring, machine seeds, state channels and limit
entries into ``data/``, beside anything written by hand. It does not write
scenarios. Nothing reaches the running stack until ``osprey build``, and a new
TTL also needs ``ttl_path`` repointed and the graph reseeded.

**The agent reaches each part through a server, often via a subagent.** Address
lookups go to the channel-finder subagent, questions of structure to the
facility-knowledge-graph subagent, procedures and terms to the
facility-knowledge subagent, and lattice computations to the pyat-specialist,
which runs its code in the python executor. The main agent also calls the
graph, facility-knowledge and python servers directly. Bluesky devices are
derived at build from the channel roster; ``bluesky_devices.yml`` overrides
them when present. The facility identity rule is auto-loaded into the main
agent's prompt; a subagent reaches it only through the workspace
``facility_description`` tool, which the data-visualizer is granted.

The description says nothing about how a value reaches the machine. A channel
write, Python the agent wrote, a Bluesky plan and a notebook cell each have their
own route and their own gates; the channel limits above are one input to those
gates. :doc:`safety-chain` draws every route.

What a facility provides
========================

.. list-table::
   :header-rows: 1
   :widths: 24 28 48

   * - File
     - Written by
     - Read by
   * - Middle Layer export
     - ``mml_export.m``, in Matlab
     - ``osprey mml import``, which writes ``data/mml/``
   * - ``data/mml/`` and ``data/mml/mapping.yaml``
     - ``osprey mml import``; ``osprey mml map --init``, then you
     - ``osprey mml map --check``, ``verify`` and ``emit``
   * - ``channel_databases/tiers/tierN/<mode>.json``
     - you, or ``osprey mml emit`` (``middle_layer``)
     - the channel-finder server in that mode, ``build-ttl`` (hierarchical and
       ``in_context``), the VA manifest and the Bluesky device derivation; none
       is staged in graph mode
   * - graph corpus (``.ttl``)
     - you, ``osprey mml emit`` or ``osprey knowledge build-ttl``
     - Neo4j at the first deploy, whenever ``services.graphdb`` is configured;
       the graph index at build, in graph mode; ``seed-from-ttl``
   * - ``facility_ontology.json``
     - you, or ``osprey mml emit``
     - TTL generation (``emit``, ``build-ttl --ontology``); after build, the
       agents' terminology tables
   * - ``facility_knowledge/``
     - you, or ``osprey mml emit``; stubs from ``seed-from-ttl``
     - the facility-knowledge server
   * - ``rules/facility.md`` (profile root)
     - you; build writes a placeholder when it is absent
     - the main agent's prompt; the ``facility_description`` tool
   * - ``simulation/lattice.json``, ``va_bindings.json``
     - ``osprey mml emit`` from a 2.0 export, or you
     - the virtual accelerator and its manifest
   * - ``simulation/machine.json``
     - you, or ``osprey mml emit``
     - the virtual accelerator, its manifest and the mock connector
   * - ``simulation/scenarios/``
     - you (``emit`` checks them)
     - the virtual accelerator and the mock connector
   * - ``machine_state_channels.json``
     - ``osprey mml emit``, or you
     - the VA manifest, which refuses a tree without it
   * - ``pyaml/<token>.yaml``
     - ``osprey mml emit`` (pyAML branch)
     - ``pyaml_measure``, in the python executor, once ``pyaml.configuration``
       names it
   * - ``bluesky_devices.yml``
     - you (optional)
     - build, in place of the devices it derives from the channel roster
   * - ``channel_limits.json``
     - you; ``osprey mml emit`` adds entries for the channels it binds
     - the limits check, when enabled; the virtual accelerator and its
       manifest; ``build-ttl``

See also
========

- :doc:`safety-chain`: every check a write passes
- :doc:`virtual-accelerator`: inside the simulator container
- :doc:`retrieval-paths`: how each channel-finder pipeline answers a search
- :doc:`/how-to/control-systems/switch-control-target`: moving a session between
  the live machine, the virtual accelerator and the stand-in
