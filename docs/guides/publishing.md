# Publishing

Publishing bytes and registering metadata are separate steps. A `PublishingSource` uploads local
files to a platform and returns a version-pinned locator. The resulting manifest still goes through
normal validation and review.

Choose a platform-specific immutable version, record its version DOI when available, and copy its
published byte size and checksum. Never point a manifest at a mutable branch or a platform’s moving
“latest” record.

Read-only sources do not need to implement publishing. This keeps mirrors and upload targets under the
same locator model without requiring every platform driver to accept writes.
