# Static presentation copies — synthetic

`recovery-trace.jsonl` and `recovery-provenance.json` are copies of the public
synthetic transient-read fixture, for projection during an outage. They are not
live recordings and contain no executable support. The provenance's `files` map
refers to the complete original fixture, not this presentation directory.

Use the [canonical source](../../../exercises/fixed/fixtures/faults/transient-read/)
and [outage/rejoin card](../../demos/replay/README.md) to run replay. New artifacts
always have `evidence_kind=replay` and identify the synthetic source.
