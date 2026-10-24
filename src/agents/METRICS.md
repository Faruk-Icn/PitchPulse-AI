# Live analysis contract

The pass difficulty index is a geometry heuristic, not a calibrated probability.
Pitch coordinates are mapped from percentages onto a 105 × 68 metre pitch. For
each observed defender, the algorithm finds the distance to the pass segment.
It combines the nearest defender's lane distance (exponential decay over 6 m)
with the cosine of the pass angle toward the attacking goal. The final index is
`0.8 × lane risk + 0.2 × forward risk`, in the range 0–1.

Tactical pressure counts observed defenders within 10 m of the pass origin.
Density is defenders per 100 m² of that circle. The weighted pressure index
adds `1 − distance/10 m` for each nearby defender and maps the sum to 0–1 with
`1 − exp(−sum)`. The fixed circle is used even at pitch boundaries.

Both metrics require fresh opposing position events. They return `null` when
none are available. Neither model uses player speed, tracking frames or a
fitted outcome dataset.

The consumer emits an `analysis` JSON record as soon as deterministic agents
finish. If Foundry is configured, it emits a later `narrative` record after the
Storyteller responds. It starts Event Hubs reception from the earliest retained
event and deduplicates sequences only in process memory. There is no persistent
checkpoint store, so restarts replay retained events and consumers must account
for duplicate output. Production use needs a durable checkpoint and output sink.

Run `python -m scripts.benchmark_agent_pipeline` to measure the local analysis
path. Its timings exclude Event Hubs transport, stdout delivery and Foundry.
