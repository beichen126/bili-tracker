# Public repository decisions

These decisions define the initial public repository baseline. Product behavior can evolve through normal issues and pull requests, but changes that affect privacy, licensing or distribution must update this record.

| ID | Decision | Baseline |
|---|---|---|
| DEC-01 | Project identity | Public repository name: `bili-tracker`; package name: `bili-tracker`. |
| DEC-02 | Source license | MIT for source code. Dependencies, models and system binaries retain their own licenses. |
| DEC-03 | History policy | Clean public history; no private prototype history or runtime artifacts. |
| DEC-04 | Bilibili integration | Optional and disabled by default; core local functionality must not depend on it. |
| DEC-05 | External text processing | Optional and disabled by default; outbound data must be disclosed before use. |
| DEC-06 | Network binding | Loopback by default. Non-loopback deployment requires explicit authentication and input restrictions. |
| DEC-07 | Model distribution | Manifests may be public; model weights, credentials, media and caches are never committed or bundled. |
| DEC-08 | Support baseline | Windows 11 and Ubuntu LTS are the primary validation targets; macOS receives documented best-effort support. |

Recorded: 2026-09-09.
