import { type Page, type TestInfo, expect, test } from "@playwright/test";

interface ProbeApp {
  readonly isRunning: boolean;
  readonly scene: ProbeScene;
}
interface ProbeScene {
  readonly isDisposed: boolean;
  getEngine(): ProbeEngine;
}
interface ProbeEngine {
  readonly isDisposed: boolean;
}
interface ViewerRecord {
  element: HTMLElement;
  generation: number;
  disconnected: boolean;
  app: ProbeApp | null;
  scene: ProbeScene | null;
  engine: ProbeEngine | null;
  trajectoryUrl: string | null;
}
interface WorkerRecord {
  worker: Worker;
  generation: number | null;
  terminated: boolean;
}
interface TrajectoryUrlRecord {
  url: string;
  generation: number | null;
  live: boolean;
}
interface FetchRecord {
  url: string;
  signal: AbortSignal;
  abortEvents: number;
}
interface LifecycleProbe {
  viewers: ViewerRecord[];
  workers: WorkerRecord[];
  trajectoryUrls: TrajectoryUrlRecord[];
  fetches: FetchRecord[];
  registration: {
    readonly defineCalls: number;
    readonly preservedConstructor: boolean;
  };
}

declare global {
  interface Window {
    __molhubLifecycle: LifecycleProbe;
  }
}

const inspectorPath =
  "/molhub/inspect/dataset/molcrafts/3bpa/v1?role=train_300K&frame=0&x=frame&y=energy&color=none";

const sourceRoot =
  "https://raw.githubusercontent.com/davkovacs/BOTNet-datasets/29e6d467317e4b5967b7ea5cbee54de953fa0d45/dataset_3BPA/";

test("3BPA Inspector links structures, properties, URL state, roles, and themes", async ({
  context,
  page,
}, testInfo) => {
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  observeFailures(page, consoleErrors, failedRequests);
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);

  await page.goto(inspectorPath, { waitUntil: "networkidle" });
  await waitForViewer(page);
  // Vega replaces the host's author label with its graphics-document label.
  // `data-active-frame` is MolHub's stable handle for this plot surface.
  const propertyPlot = page.locator("[data-active-frame]");
  await expect(propertyPlot.locator("canvas")).toBeVisible({ timeout: 60_000 });
  await expect(propertyPlot.locator("svg")).toHaveCount(0);

  const initial = await viewerState(page);
  expect(initial.frames).toBe(500);
  expect(initial.currentFrame).toBe(0);
  expect(initial.canvasCount).toBe(1);
  await expect(page.getByText("energy", { exact: true })).toBeVisible();
  await expect(page.getByText(/Viewer omits unsupported metadata \(dihedrals\)/)).toBeVisible();

  const slider = page.getByRole("slider", { name: "Trajectory frame" });
  await slider.focus();
  await slider.press("Home");
  await slider.press("ArrowRight");
  await slider.press("ArrowRight");
  await expect(page).toHaveURL(/frame=2/);
  await expect.poll(async () => (await viewerState(page)).currentFrame).toBe(2);
  await expect(page.locator('[data-active-frame="2"]')).toHaveCount(1);

  await propertyPlot.scrollIntoViewIfNeeded();
  const point = await visibleMolplotPoint(propertyPlot);
  await page.mouse.click(point.x, point.y);
  await expect.poll(() => new URL(page.url()).searchParams.get("frame")).not.toBe("2");
  const clickedFrame = Number(new URL(page.url()).searchParams.get("frame"));
  await expect.poll(async () => (await viewerState(page)).currentFrame).toBe(clickedFrame);

  const beforePlay = new URL(page.url()).searchParams.get("frame");
  await page.getByRole("button", { name: "Play trajectory" }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("frame")).not.toBe(beforePlay);
  await page.getByRole("button", { name: "Pause trajectory" }).click();
  const sharedFrame = Number(new URL(page.url()).searchParams.get("frame"));
  await expect(page.locator(`[data-active-frame="${sharedFrame}"]`)).toHaveCount(1);

  await page.getByRole("button", { name: "Copy link" }).click();
  await expect(page.getByRole("button", { name: "Copied" })).toBeVisible();
  const shareUrl = page.url();
  expect(shareUrl).not.toContain("blob:");
  const restored = await context.newPage();
  observeFailures(restored, consoleErrors, failedRequests);
  await restored.goto(shareUrl, { waitUntil: "networkidle" });
  await waitForViewer(restored, sharedFrame);
  await expect(restored.locator(`[data-active-frame="${sharedFrame}"]`)).toHaveCount(1);
  const restoredSearch = new URL(restored.url()).searchParams;
  expect(Object.fromEntries(restoredSearch)).toMatchObject({
    role: "train_300K",
    frame: String(sharedFrame),
    x: "frame",
    y: "energy",
    color: "none",
  });
  await restored.close();

  await attachScreenshot(page, testInfo, "inspector-light");
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  const contrast = await visibleButtonContrast(page);
  expect(contrast.filter((item) => item.ratio < 3)).toEqual([]);
  await attachScreenshot(page, testInfo, "inspector-dark");

  await page.getByLabel("Artifact role").selectOption("test_300K");
  await expect(page).toHaveURL(/role=test_300K/);
  await waitForViewer(page);
  const switched = await viewerState(page);
  expect(switched.frames).toBe(1669);
  expect(switched.currentFrame).toBe(0);
  await expect(page.locator("molvis-viewer")).toHaveCount(1);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
    )
    .toBeLessThanOrEqual(0);
  await attachScreenshot(page, testInfo, "inspector-mobile");

  expect(failedRequests).toEqual([]);
  expect(consoleErrors).toEqual([]);
});

test("Inspector lifecycle aborts stale work and disposes resources", async ({ page }) => {
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  const sourceRequests: string[] = [];
  observeFailures(page, consoleErrors, failedRequests);
  page.on("request", (request) => {
    if (request.url().startsWith(sourceRoot)) sourceRequests.push(request.url());
  });

  await installLifecycleProbe(page);
  const fixtures = await routeInspectorFixtures(page, "test_300K");
  await page.goto(inspectorPath, { waitUntil: "networkidle" });
  await waitForViewer(page);

  const initialGeneration = await currentViewerGeneration(page);
  expect(initialGeneration).toBeGreaterThan(0);

  await page.getByLabel("Artifact role").selectOption("test_300K");
  await expect.poll(() => sourceFetchCount(page, "test_300K")).toBe(1);

  await page.getByLabel("Artifact role").selectOption("test_600K");
  await expect(page).toHaveURL(/role=test_600K/);
  await waitForViewer(page);
  await expect(page.getByText("energy, final_marker", { exact: true })).toBeVisible();
  await expect(page.getByRole("slider", { name: "Trajectory frame" })).toHaveAttribute("max", "3");

  const finalGeneration = await currentViewerGeneration(page);
  expect(finalGeneration).toBeGreaterThan(initialGeneration);

  await expect
    .poll(() => staleFetchState(page, "test_300K"))
    .toEqual({ aborted: true, abortEvents: 1 });
  await expect
    .poll(() => disposedReadyViewers(page))
    .toContainEqual({
      generation: initialGeneration,
      appStopped: true,
      sceneDisposed: true,
      engineDisposed: true,
    });

  const settled = await inspectorOwnershipState(page);
  expect(settled.registration).toEqual({ defineCalls: 1, preservedConstructor: true });
  expect(settled.viewerCount).toBe(1);
  expect(settled.viewerCanvasCount).toBe(1);
  expect(settled.currentGeneration).toBe(finalGeneration);
  expect(settled.staleLiveWorkers).toBe(0);
  expect(settled.liveTrajectoryUrls).toBe(1);
  expect(settled.currentTrajectoryUrls).toBe(1);
  expect(settled.workerCreated).toBeGreaterThanOrEqual(0);
  expect(settled.workerTerminated).toBe(settled.workerCreated - settled.currentLiveWorkers);

  const finalBeforeStaleRelease = await finalInspectorState(page);
  fixtures.releaseStale();
  await fixtures.staleHandled;
  await page.waitForTimeout(100);
  expect(await finalInspectorState(page)).toEqual(finalBeforeStaleRelease);

  await page.getByRole("link", { name: "Artifact detail" }).click();
  await expect(page).toHaveURL(/\/molhub\/a\/dataset\/molcrafts\/3bpa\/v1$/);
  await expect(page.locator("molvis-viewer")).toHaveCount(0);
  await expect(page.locator("molvis-viewer canvas")).toHaveCount(0);

  const afterLeave = await inspectorOwnershipState(page);
  expect(afterLeave.viewerCount).toBe(0);
  expect(afterLeave.viewerCanvasCount).toBe(0);
  expect(afterLeave.currentLiveWorkers).toBe(0);
  expect(afterLeave.liveTrajectoryUrls).toBe(0);
  expect(afterLeave.workerTerminated).toBe(afterLeave.workerCreated);
  expect(await allReadyViewersDisposed(page)).toBe(true);

  expect(sourceRequests.length).toBeGreaterThanOrEqual(3);
  expect(sourceRequests.every((url) => url.startsWith(sourceRoot))).toBe(true);
  expect(
    failedRequests.every(
      (failure) => failure.includes("test_300K.xyz") && failure.includes("net::ERR_ABORTED"),
    ),
  ).toBe(true);
  expect(consoleErrors).toEqual([]);
});

test("Inspector keyboard controls expose visible focus and return through artifact detail", async ({
  context,
  page,
}) => {
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  observeFailures(page, consoleErrors, failedRequests);
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await routeInspectorFixtures(page);

  await page.goto(inspectorPath, { waitUntil: "networkidle" });
  await waitForViewer(page);

  const role = page.getByLabel("Artifact role");
  await tabTo(page, role);
  await expectVisibleKeyboardFocus(role);
  // Native <select> on Chromium ignores ArrowDown while the list is closed.
  // Typeahead with real key events is the supported keyboard option-pick path
  // and fires the change React needs to update the search param.
  await page.keyboard.type("test_300K");
  await expect(role).toHaveValue("test_300K");
  await expect(page).toHaveURL(/role=test_300K/);
  await waitForViewer(page);

  const slider = page.getByRole("slider", { name: "Trajectory frame" });
  await tabTo(page, slider);
  await expectVisibleKeyboardFocus(slider);
  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(/frame=1/);

  const copyLink = page.getByRole("button", { name: "Copy link" });
  await tabTo(page, copyLink, "Shift+Tab");
  await expectVisibleKeyboardFocus(copyLink);
  await page.keyboard.press("Space");
  await expect(page.getByRole("button", { name: "Copied" })).toBeVisible();

  const artifactDetail = page.getByRole("link", { name: "Artifact detail" });
  await tabTo(page, artifactDetail, "Shift+Tab");
  await expectVisibleKeyboardFocus(artifactDetail);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/molhub\/a\/dataset\/molcrafts\/3bpa\/v1$/);

  const inspectReturn = page.getByRole("link", { name: "Inspect", exact: true }).first();
  await tabTo(page, inspectReturn);
  await expectVisibleKeyboardFocus(inspectReturn);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/molhub\/inspect\/dataset\/molcrafts\/3bpa\/v1/);
  await waitForViewer(page);

  // Role typeahead may briefly select intermediate roles; abort noise is expected.
  expect(failedRequests.filter((failure) => !failure.includes("net::ERR_ABORTED"))).toEqual([]);
  expect(consoleErrors).toEqual([]);
});

test("Inspector mobile light layout fits its viewer and primary controls", async ({
  page,
}, testInfo) => {
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  observeFailures(page, consoleErrors, failedRequests);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ colorScheme: "light" });
  await routeInspectorFixtures(page);

  await page.goto(inspectorPath, { waitUntil: "networkidle" });
  await waitForViewer(page);
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  await expect(page.getByLabel("Artifact role")).toBeVisible();
  await expect(page.getByRole("slider", { name: "Trajectory frame" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy link" })).toBeVisible();
  await expect(page.locator("molvis-viewer")).toBeVisible();
  await expect(page.locator("molvis-viewer canvas")).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
    )
    .toBeLessThanOrEqual(0);
  await attachScreenshot(page, testInfo, "inspector-mobile-light");

  expect(failedRequests).toEqual([]);
  expect(consoleErrors).toEqual([]);
});

async function installLifecycleProbe(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const viewers: ViewerRecord[] = [];
    const workers: WorkerRecord[] = [];
    const trajectoryUrls: TrajectoryUrlRecord[] = [];
    const fetches: FetchRecord[] = [];
    let nextGeneration = 0;
    let defineCalls = 0;
    let incomingConstructor: CustomElementConstructor | null = null;

    const nativeFetch = window.fetch.bind(window);
    window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : null;
      const signal = init?.signal ?? request?.signal ?? null;
      const url = request?.url ?? (input instanceof URL ? input.href : String(input));
      if (signal) {
        const record: FetchRecord = { url, signal, abortEvents: 0 };
        signal.addEventListener("abort", () => {
          record.abortEvents += 1;
        });
        fetches.push(record);
      }
      return nativeFetch(input, init);
    }) as typeof window.fetch;

    const nativeCreateObjectURL = URL.createObjectURL.bind(URL);
    URL.createObjectURL = ((object: Blob | MediaSource) => {
      const url = nativeCreateObjectURL(object);
      if (object instanceof Blob && object.type === "chemical/x-xyz") {
        trajectoryUrls.push({ url, generation: null, live: true });
      }
      return url;
    }) as typeof URL.createObjectURL;
    const nativeRevokeObjectURL = URL.revokeObjectURL.bind(URL);
    URL.revokeObjectURL = ((url: string) => {
      const record = trajectoryUrls.find((candidate) => candidate.url === url && candidate.live);
      if (record) record.live = false;
      nativeRevokeObjectURL(url);
    }) as typeof URL.revokeObjectURL;

    const nativeWorker = window.Worker;
    const workerProxy = new Proxy(nativeWorker, {
      construct(target, argumentsList) {
        const worker = Reflect.construct(target, argumentsList) as Worker;
        let ownerGeneration: number | null = null;
        for (let index = viewers.length - 1; index >= 0; index -= 1) {
          const viewer = viewers[index];
          if (viewer && !viewer.disconnected && viewer.element.isConnected) {
            ownerGeneration = viewer.generation;
            break;
          }
        }
        const record: WorkerRecord = {
          worker,
          generation: ownerGeneration,
          terminated: false,
        };
        const nativeTerminate = worker.terminate.bind(worker);
        worker.terminate = () => {
          record.terminated = true;
          nativeTerminate();
        };
        workers.push(record);
        return worker;
      },
    });
    window.Worker = workerProxy as typeof Worker;

    const nativeDefine = customElements.define.bind(customElements);
    customElements.define = ((name, ctor, options) => {
      if (name === "molvis-viewer") {
        defineCalls += 1;
        incomingConstructor = ctor;
        const prototype = ctor.prototype as HTMLElement & {
          connectedCallback?: () => void;
          disconnectedCallback?: () => void;
        };
        const nativeConnected = prototype.connectedCallback;
        const nativeDisconnected = prototype.disconnectedCallback;
        prototype.connectedCallback = function connectedCallback(this: HTMLElement) {
          const generation = ++nextGeneration;
          const trajectoryUrl = this.getAttribute("src");
          const record: ViewerRecord = {
            element: this,
            generation,
            disconnected: false,
            app: null,
            scene: null,
            engine: null,
            trajectoryUrl,
          };
          const urlRecord = trajectoryUrls.find(
            (candidate) => candidate.url === trajectoryUrl && candidate.live,
          );
          if (urlRecord) urlRecord.generation = generation;
          viewers.push(record);
          this.addEventListener(
            "molvis:ready",
            (event) => {
              const app = (event as CustomEvent<{ app: ProbeApp }>).detail.app;
              record.app = app;
              record.scene = app.scene;
              record.engine = app.scene.getEngine();
            },
            { once: true },
          );
          nativeConnected?.call(this);
        };
        prototype.disconnectedCallback = function disconnectedCallback(this: HTMLElement) {
          nativeDisconnected?.call(this);
          for (let index = viewers.length - 1; index >= 0; index -= 1) {
            const record = viewers[index];
            if (record?.element === this && !record.disconnected) {
              record.disconnected = true;
              break;
            }
          }
        };
      }
      nativeDefine(name, ctor, options);
    }) as CustomElementRegistry["define"];

    window.__molhubLifecycle = {
      viewers,
      workers,
      trajectoryUrls,
      fetches,
      registration: {
        get defineCalls() {
          return defineCalls;
        },
        get preservedConstructor() {
          return (
            incomingConstructor !== null &&
            customElements.get("molvis-viewer") === incomingConstructor
          );
        },
      },
    };
  });
}

async function routeInspectorFixtures(page: Page, delayedRole?: string) {
  let releaseStale = () => {};
  const staleGate = new Promise<void>((resolve) => {
    releaseStale = resolve;
  });
  let staleHandledResolve = () => {};
  const staleHandled = new Promise<void>((resolve) => {
    staleHandledResolve = resolve;
  });

  await page.route(`${sourceRoot}**`, async (route) => {
    const filename = new URL(route.request().url()).pathname.split("/").pop() ?? "";
    const role = filename.replace(/\.xyz$/, "");
    if (role === delayedRole) await staleGate;
    await route.fulfill({
      status: 200,
      contentType: "chemical/x-xyz",
      headers: { "access-control-allow-origin": "*" },
      body: fixtureForRole(role),
    });
    if (role === delayedRole) staleHandledResolve();
  });

  return { releaseStale, staleHandled };
}

function fixtureForRole(role: string): string {
  if (role === "test_300K") return extxyzFixture(3, "stale_marker", -20);
  if (role === "test_600K") return extxyzFixture(4, "final_marker", -30);
  if (role === "test_1200K") return extxyzFixture(5, "hot_marker", -40);
  return extxyzFixture(2, "train_marker", -10);
}

function extxyzFixture(frameCount: number, marker: string, energyStart: number): string {
  return Array.from({ length: frameCount }, (_, frame) =>
    [
      "2",
      `Properties=species:S:1:pos:R:3 energy=${energyStart + frame} ${marker}=${frame}`,
      `H ${frame * 0.01} 0 0`,
      `H 0 0 ${1 + frame * 0.01}`,
    ].join("\n"),
  ).join("\n");
}

async function sourceFetchCount(page: Page, role: string): Promise<number> {
  return page.evaluate(
    (suffix) =>
      window.__molhubLifecycle.fetches.filter(
        (record) => record.url.endsWith(`/${suffix}.xyz`) && !record.url.startsWith("blob:"),
      ).length,
    role,
  );
}

async function staleFetchState(page: Page, role: string) {
  return page.evaluate((suffix) => {
    const record = window.__molhubLifecycle.fetches.find(
      (candidate) => candidate.url.endsWith(`/${suffix}.xyz`) && !candidate.url.startsWith("blob:"),
    );
    return {
      aborted: record?.signal.aborted ?? false,
      abortEvents: record?.abortEvents ?? 0,
    };
  }, role);
}

async function currentViewerGeneration(page: Page): Promise<number> {
  return page.evaluate(() => {
    const current = [...window.__molhubLifecycle.viewers]
      .reverse()
      .find((record) => !record.disconnected && record.element.isConnected && record.app);
    return current?.generation ?? -1;
  });
}

async function disposedReadyViewers(page: Page) {
  return page.evaluate(() =>
    window.__molhubLifecycle.viewers
      .filter((record) => record.disconnected && record.app && record.scene && record.engine)
      .map((record) => ({
        generation: record.generation,
        appStopped: record.app?.isRunning === false,
        sceneDisposed: record.scene?.isDisposed === true,
        engineDisposed: record.engine?.isDisposed === true,
      })),
  );
}

async function allReadyViewersDisposed(page: Page): Promise<boolean> {
  return page.evaluate(() =>
    window.__molhubLifecycle.viewers
      .filter((record) => record.app && record.scene && record.engine)
      .every(
        (record) =>
          record.disconnected &&
          record.app?.isRunning === false &&
          record.scene?.isDisposed === true &&
          record.engine?.isDisposed === true,
      ),
  );
}

async function inspectorOwnershipState(page: Page) {
  return page.evaluate(() => {
    const probe = window.__molhubLifecycle;
    const current = [...probe.viewers]
      .reverse()
      .find((record) => !record.disconnected && record.element.isConnected && record.app);
    const liveWorkers = probe.workers.filter((record) => !record.terminated);
    const staleGenerations = new Set(
      probe.viewers.filter((record) => record.disconnected).map((record) => record.generation),
    );
    return {
      registration: {
        defineCalls: probe.registration.defineCalls,
        preservedConstructor: probe.registration.preservedConstructor,
      },
      viewerCount: document.querySelectorAll("molvis-viewer").length,
      viewerCanvasCount: document.querySelectorAll("molvis-viewer canvas").length,
      currentGeneration: current?.generation ?? null,
      workerCreated: probe.workers.length,
      workerTerminated: probe.workers.filter((record) => record.terminated).length,
      currentLiveWorkers: liveWorkers.length,
      staleLiveWorkers: liveWorkers.filter(
        (record) => record.generation !== null && staleGenerations.has(record.generation),
      ).length,
      liveTrajectoryUrls: probe.trajectoryUrls.filter((record) => record.live).length,
      currentTrajectoryUrls: probe.trajectoryUrls.filter(
        (record) => record.live && record.generation === current?.generation,
      ).length,
    };
  });
}

async function finalInspectorState(page: Page) {
  const ownership = await inspectorOwnershipState(page);
  // InspectorFact renders label + value as sibling <p>s (not a dl/dd).
  const frameProperties = page.getByText("Frame properties", { exact: true });
  return {
    role: await page.getByLabel("Artifact role").inputValue(),
    search: Object.fromEntries(new URL(page.url()).searchParams),
    metadata: await frameProperties.locator("xpath=following-sibling::*[1]").textContent(),
    sliderMax: await page.getByRole("slider", { name: "Trajectory frame" }).getAttribute("max"),
    viewerCount: ownership.viewerCount,
    viewerCanvasCount: ownership.viewerCanvasCount,
    currentGeneration: ownership.currentGeneration,
    currentLiveWorkers: ownership.currentLiveWorkers,
    liveTrajectoryUrls: ownership.liveTrajectoryUrls,
    currentTrajectoryUrls: ownership.currentTrajectoryUrls,
  };
}

async function tabTo(
  page: Page,
  target: ReturnType<Page["locator"]>,
  key: "Tab" | "Shift+Tab" = "Tab",
): Promise<void> {
  for (let presses = 0; presses < 40; presses += 1) {
    if (await target.evaluate((element) => document.activeElement === element)) return;
    await page.keyboard.press(key);
  }
  throw new Error(`Keyboard traversal did not reach ${await target.getAttribute("aria-label")}`);
}

async function expectVisibleKeyboardFocus(target: ReturnType<Page["locator"]>): Promise<void> {
  await expect(target).toBeFocused();
  const state = await target.evaluate((element) => {
    const style = getComputedStyle(element);
    const outlineVisible = style.outlineStyle !== "none" && style.outlineWidth !== "0px";
    const shadowVisible = style.boxShadow !== "none" && style.boxShadow !== "";
    return { focusVisible: element.matches(":focus-visible"), outlineVisible, shadowVisible };
  });
  expect(state.focusVisible).toBe(true);
  expect(state.outlineVisible || state.shadowVisible).toBe(true);
}

async function waitForViewer(page: Page, frame?: number): Promise<void> {
  await page.locator("molvis-viewer").waitFor({ state: "visible", timeout: 30_000 });
  await page.waitForFunction(
    (wantedFrame) => {
      const viewer = document.querySelector("molvis-viewer") as
        | (HTMLElement & {
            app?: { system: { trajectory: { currentIndex: number } } };
          })
        | null;
      return (
        viewer?.dataset.state === "ready" &&
        (wantedFrame === undefined || viewer.app?.system.trajectory.currentIndex === wantedFrame)
      );
    },
    frame,
    { timeout: 30_000 },
  );
}

async function viewerState(page: Page) {
  return page.locator("molvis-viewer").evaluate((element) => {
    const viewer = element as HTMLElement & {
      app?: { system: { trajectory: { length: number; currentIndex: number } } };
    };
    return {
      frames: viewer.app?.system.trajectory.length ?? 0,
      currentFrame: viewer.app?.system.trajectory.currentIndex ?? -1,
      canvasCount: viewer.querySelectorAll("canvas").length,
    };
  });
}

async function visibleMolplotPoint(plot: ReturnType<Page["locator"]>) {
  return plot.evaluate((element) => {
    const canvas = element.querySelector("canvas");
    const context = canvas?.getContext("2d", { willReadFrequently: true });
    if (!canvas || !context) throw new Error("MolPlot Canvas renderer is not available");

    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    const startX = Math.floor(canvas.width * 0.25);
    const endX = Math.ceil(canvas.width * 0.75);
    for (let x = startX; x < endX; x += 1) {
      for (let y = 0; y < canvas.height; y += 1) {
        const offset = (y * canvas.width + x) * 4;
        if (
          Math.abs((pixels[offset] ?? 0) - 12) <= 2 &&
          Math.abs((pixels[offset + 1] ?? 0) - 93) <= 2 &&
          Math.abs((pixels[offset + 2] ?? 0) - 165) <= 2 &&
          (pixels[offset + 3] ?? 0) > 200
        ) {
          const bounds = canvas.getBoundingClientRect();
          return {
            x: bounds.left + ((x + 0.5) / canvas.width) * bounds.width,
            y: bounds.top + ((y + 0.5) / canvas.height) * bounds.height,
          };
        }
      }
    }
    throw new Error("No visible MolPlot point was found in the Canvas bitmap");
  });
}

function observeFailures(page: Page, consoleErrors: string[], failedRequests: string[]) {
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => {
    failedRequests.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText}`);
  });
}

async function attachScreenshot(page: Page, testInfo: TestInfo, name: string) {
  await testInfo.attach(name, {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png",
  });
}

async function visibleButtonContrast(page: Page) {
  return page.locator("button:visible").evaluateAll((buttons) => {
    // Modern Chromium returns oklab()/oklch() from getComputedStyle; convert
    // through a 1×1 canvas so contrast math always sees sRGB 0–255 channels.
    const canvas = document.createElement("canvas");
    canvas.width = 1;
    canvas.height = 1;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) throw new Error("2d canvas is required for contrast sampling");

    const toSrgb = (cssColor: string): [number, number, number, number] => {
      ctx.clearRect(0, 0, 1, 1);
      ctx.fillStyle = "#000";
      ctx.fillStyle = cssColor;
      ctx.fillRect(0, 0, 1, 1);
      const [red = 0, green = 0, blue = 0, alpha = 255] = ctx.getImageData(0, 0, 1, 1).data;
      return [red, green, blue, alpha / 255];
    };

    const luminance = ([red = 0, green = 0, blue = 0]: number[]) =>
      0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue);
    const linear = (channel: number) => {
      const value = channel / 255;
      return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
    };
    const composite = (foreground: number[], background: number[]) =>
      foreground.map((channel, index) =>
        index < 3
          ? channel * (foreground[3] ?? 1) + (background[index] ?? 0) * (1 - (foreground[3] ?? 1))
          : 1,
      ) as [number, number, number, number];

    const opaqueAncestorBackground = (element: Element): [number, number, number, number] => {
      let current: Element | null = element;
      while (current) {
        const color = toSrgb(getComputedStyle(current).backgroundColor);
        if ((color[3] ?? 0) >= 0.99) return color;
        current = current.parentElement;
      }
      return toSrgb(getComputedStyle(document.documentElement).backgroundColor);
    };

    return buttons.map((button) => {
      const style = getComputedStyle(button);
      const foreground = toSrgb(style.color);
      const rawBackground = toSrgb(style.backgroundColor);
      const background =
        (rawBackground[3] ?? 1) < 0.99
          ? composite(
              rawBackground,
              opaqueAncestorBackground(button.parentElement ?? document.body),
            )
          : rawBackground;
      const [lighter = 0, darker = 0] = [luminance(foreground), luminance(background)].sort(
        (left, right) => right - left,
      );
      return {
        label: button.getAttribute("aria-label") ?? button.textContent?.trim() ?? "",
        ratio: (lighter + 0.05) / (darker + 0.05),
      };
    });
  });
}
