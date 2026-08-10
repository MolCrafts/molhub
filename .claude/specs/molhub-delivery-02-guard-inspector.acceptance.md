---
slug: molhub-delivery-02-guard-inspector
criteria:
  - id: ac-001
    summary: "Stale fetch signal is directly aborted"
    type: runtime
    pass_when: |
      The named Playwright lifecycle test retains the actual AbortSignal passed
      to the delayed stale role fetch and observes both its abort event and
      signal.aborted === true after rapid role switching.
    status: pending
  - id: ac-002
    summary: "MolVis instrumentation preserves registration"
    type: code
    pass_when: |
      The init script patches the incoming molvis-viewer constructor prototype
      before invoking the original customElements.define exactly once; it does
      not replace the constructor, register a second element, or copy MolVis
      implementation code.
    status: pending
  - id: ac-003
    summary: "Old app scene and engine are disposed"
    type: runtime
    pass_when: |
      References captured from molvis:ready for every disconnected old viewer
      satisfy app.isRunning === false, scene.isDisposed === true, and
      scene.getEngine().isDisposed === true.
    status: pending
  - id: ac-004
    summary: "Stale and final workers are cleaned up"
    type: runtime
    pass_when: |
      Worker instrumentation records creation and terminate calls; after role
      switching no worker from an old viewer generation remains live, and after
      route leave the tracked live Worker set is empty.
    status: pending
  - id: ac-005
    summary: "Inspector reaches a quiescent final state"
    type: runtime
    pass_when: |
      After the final role settles there is exactly one molvis-viewer, exactly
      one molvis-viewer canvas, no live worker owned by a stale generation, and
      only the current chemical/x-xyz trajectory Blob URL; after route leave
      viewer/canvas/live-worker/live-trajectory-URL counts are all zero.
    status: pending
  - id: ac-006
    summary: "Stale completion cannot overwrite current state"
    type: runtime
    pass_when: |
      Releasing the delayed stale response after the final viewer is ready does
      not change the final role, URL frame, metadata, viewer count, current app,
      worker ownership or trajectory Blob ownership.
    status: pending
  - id: ac-007
    summary: "Lifecycle evidence is direct and complete"
    type: runtime
    pass_when: |
      Product AC-006 is advanced to passed only when the same named Playwright
      run succeeds with direct fetch-signal, Worker, app, scene and engine
      assertions; DOM removal or requestfailed evidence alone is insufficient.
    status: pending
  - id: ac-008
    summary: "Keyboard focus is real and visible"
    type: runtime
    pass_when: |
      Playwright reaches and operates role selection, trajectory frame, Copy
      link and artifact-detail return using only Tab/Shift+Tab, arrows,
      Enter and Space; each focused target matches :focus-visible and has a
      non-none computed outline or box-shadow.
    status: pending
  - id: ac-009
    summary: "Mobile-light evidence remains honest"
    type: runtime
    pass_when: |
      At 390 × 844 with light color scheme, the viewer and primary controls are
      visible, horizontal overflow is zero, and a full-page screenshot is
      attached while durable product AC-012 remains pending manual review.
    status: pending
  - id: ac-010
    summary: "Production Inspector code remains unchanged"
    type: code
    pass_when: |
      The implementation diff for this spec contains no changes under
      apps/web/app/src; all added behavior is deterministic browser evidence
      and its thin regression runner.
    status: pending
  - id: ac-011
    summary: "Regression runs only the named lifecycle test"
    type: runtime
    pass_when: |
      node regressions/molhub-delivery-02-guard-inspector.mjs invokes the Web
      test:e2e command with an exact anchored grep for
      "Inspector lifecycle aborts stale work and disposes resources", contains
      no browser harness of its own, and exits with the Playwright result.
    status: pending
  - id: ac-012
    summary: "Inspector browser suite passes"
    type: runtime
    pass_when: |
      The Web production build and inspector.spec.ts Playwright suite exit 0
      with no unexpected console errors, failed requests or external source
      traffic in the new deterministic scenarios.
    status: pending
  - id: ac-013
    summary: "Full repository checks remain green"
    type: runtime
    pass_when: |
      CLAUDE.md mol_project.build.check and mol_project.build.test both exit 0
      after the Inspector evidence changes.
    status: pending
---

# Acceptance criteria

Product AC-006 只有在 named lifecycle test 同时直接证明 fetch signal、Worker、app、scene 和 engine cleanup 后才能标绿。Keyboard 与 mobile-light 自动化只增强 AC-012 的证据，人工视觉判断继续 pending。
