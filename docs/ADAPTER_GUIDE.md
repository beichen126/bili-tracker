# Adapter guide

Adapters implement ports in `bili_tracker.domain.ports` and keep vendor
imports outside the domain package. A source adapter declares capabilities,
probes a `SourceInput`, and acquires into a caller-owned target directory.
Transcribers return a `TranscriptArtifact`; processors return derived text;
quality gates return a verdict without mutating text.

Minimal source shape:

```python
class ExampleSource:
    id = "example"

    def capabilities(self):
        return SourceCapabilities(can_probe=True, can_acquire=True)

    def probe(self, source):
        return SourceMetadata("stable-id", "safe title", None, "display value")

    def acquire(self, source, target_dir, progress):
        # Validate containment, write atomically, report progress.
        raise NotImplementedError
```

Adapters must have contract tests for empty/invalid responses, bounded sizes,
stable error codes, cancellation and path containment. Network adapters use
the bounded HTTP client and revalidate every redirect. Never log headers,
cookies, API keys, raw response bodies or absolute local paths.

Add a fixed fixture for ordinary CI. A live smoke test must be opt-in, use
anonymous public content, and never be a pull-request gate. Update
`docs/provenance.md` and `NOTICE` when an adapter brings an external source
or license obligation.
