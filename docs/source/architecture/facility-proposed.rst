:orphan:

.. _architecture-facility-proposed:

=========================================
The Facility Description (proposed shape)
=========================================

.. admonition:: Proposal, not built
   :class: warning

   This page draws the proposed architecture for review. :doc:`facility` draws
   what the code does today; both figures are on this page for comparison.

A facility keeps a few source files. ``osprey build`` combines them into one
facility file and generates every other file from it. Nothing else describes
the machine.

.. raw:: html
   :file: ../_diagrams/facility-map-proposed.html

**Two kinds of source.** Imported sources come from outside OSPREY: a Middle
Layer export, a channel list, a NARAD or TTL file, lattice decks. An input layer
reads each one; a correction to imported data goes into the fix file, which sets,
adds or drops a record by its ID, so a newer export never loses it. Authored
sources are edited by hand: the fix file, the write limits, simulation scenarios,
knowledge pages. An input layer may seed the limits file once; after that only a
person changes it.

**One file in the middle.** The build validates the combined result against the
facility schema, which starts from the NARAD LinkML schema. The facility file
holds places, devices, channels, models and limits. Every record has a stable ID
and says where it came from. A bare channel list is a complete facility file; each
other section is optional, and a view whose section is empty is not generated.

**Every other file is a view.** The channel-finder indexes for every pipeline,
the knowledge graph, the virtual accelerator's inputs, a pyAML configuration per
model, the Bluesky devices, the limits table and the facts in the agent's prompts
are all written by the build from the facility file. Input layers never write a
view, and no view is edited by hand.

The description says nothing about how a value reaches the machine.
:doc:`safety-chain` draws every route; the limits table is one input to its
checks.

How the signal vocabulary is used
=================================

The words a channel record uses for device classes and signals come from the
NARAD dictionary. The facility file build checks them, the knowledge graph
stores them, and the agent searches by them.

.. raw:: html
   :file: ../_diagrams/facility-vocabulary.html

Today, for comparison
=====================

.. raw:: html
   :file: ../_diagrams/facility-map.html
