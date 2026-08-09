import { ManifestValidator } from "@molcrafts/molhub/core";

import { RegistrySource } from "./lib/registry-source.js";
import { ARTIFACTS_DIR, commandPath } from "./lib/repo.js";
import { RegistryValidator, displayPath } from "./lib/validator.js";
import { ViolationReport } from "./lib/violation.js";

const root = commandPath(process.argv[2], ARTIFACTS_DIR);
try {
  const source = new RegistrySource(root);
  const report = new ViolationReport(new RegistryValidator(source, new ManifestValidator()).run());
  if (report.isClean) {
    process.stdout.write(
      `${displayPath(root)}: ${source.manifestPaths().length} manifest(s) checked, all clean.\n`,
    );
  } else {
    process.stderr.write(`\n${displayPath(root)} did not pass validation.\n\n${report.render()}\n`);
    process.exitCode = 1;
  }
} catch (error) {
  const detail = error instanceof Error ? error.message : String(error);
  process.stderr.write(`\nvalidate could not run: ${detail}\n`);
  process.exitCode = 2;
}
