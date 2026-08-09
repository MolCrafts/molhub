import { type Page, type TestInfo, expect, test } from "@playwright/test";

const inspectorPath =
  "/molhub/inspect/dataset/molcrafts/3bpa/v1?role=train_300K&frame=0&x=frame&y=energy&color=none";

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
    const parse = (value: string) => {
      const channels = value.match(/[\d.]+/g)?.map(Number) ?? [];
      return [channels[0] ?? 0, channels[1] ?? 0, channels[2] ?? 0, channels[3] ?? 1];
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
      );

    return buttons.map((button) => {
      const style = getComputedStyle(button);
      const parent = getComputedStyle(button.parentElement ?? document.body);
      const foreground = parse(style.color);
      const rawBackground = parse(style.backgroundColor);
      const background =
        (rawBackground[3] ?? 1) < 1
          ? composite(rawBackground, parse(parent.backgroundColor))
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
