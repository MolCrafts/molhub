---
spec: python-native-dataset-protocol-02-helpers
created: 2026-08-12
criteria:
  - id: ac-001
    summary: Decorated instances expose manifest, cache_dir, fetch, open
    type: code
    pass_when: |
      tests/test_dataset/test_definition.py::TestDataset constructs a class
      decorated with @dataset and asserts the instance has .manifest (a
      DatasetManifest), .cache_dir (pathlib.Path), .fetch, and .open.
    status: pending
  - id: ac-002
    summary: Default source fetch uses injected ArtifactHub by coordinate
    type: code
    pass_when: |
      For a decorated class with coordinate dataset:example/dummy@v1 and
      source is None, instance.fetch("main") calls fake hub.fetch with that
      coordinate and roles=["main"], and returns the Path the fake mapped to
      "main".
    status: pending
  - id: ac-003
    summary: Bare locator without coordinate uses DownloadCache or file path
    type: code
    pass_when: |
      An undecorated Dataset subclass with source="file://<tmp-file>"
      returns that file from fetch() with zero hub.fetch calls; another
      undecorated Dataset subclass with source="https://example.invalid/x.bin"
      calls DownloadCache.fetch once with that exact URL (monkeypatched;
      no live HTTP).
    status: pending
  - id: ac-004
    summary: Dict source fetch and open address roles by key
    type: code
    pass_when: |
      A no-coordinate class with source={"structures": file_a, "properties":
      file_b} yields file_a from fetch("structures") and the bytes of file_b
      from open("properties").
    status: pending
  - id: ac-005
    summary: Construction and manifest access do not call hub.fetch
    type: code
    pass_when: |
      After Cls(hub=fake) and reading .manifest (and .cache_dir), fake.calls
      is empty in tests/test_dataset/test_definition.py.
    status: pending
  - id: ac-006
    summary: Zero-byte files are treated as missing
    type: code
    pass_when: |
      fetch and open raise FileNotFoundError when the fake hub returns a
      0-byte path or when a file:// locator points at a 0-byte file.
    status: pending
  - id: ac-007
    summary: Registered decorated classes cannot hardcode upstream URLs
    type: code
    pass_when: |
      Decorating a class with @dataset("dataset:example/dummy@v1") and
      source="https://example.invalid/x.bin" raises ValueError whose message
      contains both the coordinate and that URL
      (tests/test_dataset/test_definition.py::TestDatasetSource).
    status: pending
  - id: ac-008
    summary: cache_dir follows files/kind/ns/name@version layout
    type: code
    pass_when: |
      With MOLHUB_HOME set to a tmp root, a dummy at
      dataset:example/dummy@v1 has cache_dir equal to
      <root>/files/dataset/example/dummy@v1 (exact Path equality; not
      dataset_example).
    status: pending
  - id: ac-009
    summary: open() is a binary context manager over fetch bytes
    type: code
    pass_when: |
      with ds.open("main") as fh: fh.read() equals the exact bytes of the
      file fetch("main") returned; urllib.request.urlopen is not called.
    status: pending
  - id: ac-010
    summary: definition.py does not module-import Molhub
    type: code
    pass_when: |
      ast.parse of src/molhub/dataset/definition.py has no module-level
      Import/ImportFrom name Molhub; the constructor annotates
      hub: ArtifactHub | None = None. ArtifactHub in hub.py still exposes
      only fetch.
    status: pending
  - id: ac-011
    summary: New public helpers have Google-style docstrings
    type: docs
    pass_when: |
      source, cache_dir, fetch, and open in
      src/molhub/dataset/definition.py have Google-style docstrings
      (Args/Returns/Raises as applicable) naming role strings and the
      $MOLHUB_HOME/files/<kind>/<ns>/<name>@<ver> layout.
    status: pending
  - id: ac-012
    summary: Regression dummy fetch/open/cache_dir without construct-time hub
    type: runtime
    pass_when: |
      regressions/python-native-dataset-protocol-02-helpers.py exits 0.
      It decorates a dummy at dataset:example/dummy@v1, injects a fake
      ArtifactHub that returns a temp file whose bytes are the literal
      b"molhub-dataset-helpers-v1", open() reads exactly those bytes,
      cache_dir equals <MOLHUB_HOME>/files/dataset/example/dummy@v1, and
      constructing the class records zero hub.fetch calls.
    status: pending
out_of_scope:
  - load() and MapDataset/InMemoryDataset (03)
  - migrating built-in datasets
  - extending ArtifactHub with open
  - HTTP range / HttpsSource streaming
  - pydantic / Trajectory / FrameCollection
  - parsing figshare:// zenodo:// hf:// on the Python class
---

# Acceptance — python-native-dataset-protocol-02-helpers

资源助手完成：实例暴露 manifest/cache_dir/fetch/open；坐标走 ArtifactHub；裸 locator 走 DownloadCache 或本地文件；构造不取字节；0 字节视为缺失；入册类禁止硬编码上游 URL。
