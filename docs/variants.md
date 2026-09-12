# Build variants and migration

Three related libraries exist. They are not interchangeable without matching
their environment contract.

## Live legacy two-patch build

The four-Spark GLM-5.3 Flash service currently maps a locally built NCCL
2.30.7 library with SHA-256
`ccd57342449c3f680befcb379329b935746e5299dc4de5f2516146e0411bd85f`.
It applies:

- the legacy `NCCL_SKIP_TREE_CONNECT` Tree/PAT guard; and
- SparkRing's advertise-all-listener-GIDs patch.

This is the known-working production library. It remains deployed until the
new standalone build passes the same four-rank gate.

## Public v0.1.0 legacy build

The release in `alexellis/glm-5.3-flash-4x-dgx-spark-switchless` has library
SHA-256
`8733af78fa1bff0bf495bc0ba55928580327fd9696563dba265c66b222faf620`.
It applies only the legacy Tree/PAT guard. It does not contain the listener-GID
change used by the live build. That release remains available for
reproducibility but should not be described as byte- or patch-equivalent to the
live four-Spark library.

## Standalone combined build (`master`)

The repository's `master` branch applies SparkRing's later combined patch. It
provides the same intended ring-only and listener-GID behaviour as the live
two-patch build, but its opt-in variable is:

```text
NCCL_SWITCHLESS_RING_ONLY=1
```

It does not recognise `NCCL_SKIP_TREE_CONNECT`.

## Migration rule

Before replacing a legacy library, update every rank launcher to export both:

```text
NCCL_SKIP_TREE_CONNECT=1
NCCL_SWITCHLESS_RING_ONLY=1
```

This transitional environment works with either library. Verify the new binary
identity and mapping on every rank, preserve the physical rank order, and run
the complete four-rank collective and serving gate. Only then update deployment
pins and remove the legacy variable.

Do not conflate either SparkRing implementation with Joseph Rose's unlicensed
source. The shared concept is credited, but both buildable source variants in
this repository come from the separately licensed SparkRing history.
