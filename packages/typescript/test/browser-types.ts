import { Molhub } from "../src/browser.js";
import { REGISTRY } from "./fixtures.js";

const hub = new Molhub({ registry: REGISTRY });

// @ts-expect-error Browser SDK deliberately has no filesystem-backed fetch method.
void hub.fetch("dataset:molcrafts/example@v1");
