import { SubmissionApi } from "./http.js";
import { GitHubRegistryPublisher } from "./publisher.js";
import { D1SubmissionRepository } from "./repository.js";
import { SubmissionService } from "./service.js";

export default {
  async fetch(request: Request, env: Env, _context: ExecutionContext): Promise<Response> {
    const repository = new D1SubmissionRepository(env.DB);
    const publisher = new GitHubRegistryPublisher({
      token: secret(env, "GITHUB_TOKEN") ?? "",
      repository: env.GITHUB_REPOSITORY,
      baseBranch: env.GITHUB_BASE_BRANCH,
    });
    const api = new SubmissionApi(new SubmissionService(repository, publisher), env.WEB_ORIGIN, {
      adminToken: secret(env, "ADMIN_TOKEN"),
      webhookSecret: secret(env, "GITHUB_WEBHOOK_SECRET"),
      rateLimiter: env.SUBMISSION_RATE_LIMITER,
    });
    return api.handle(request);
  },
} satisfies ExportedHandler<Env>;

function secret(
  env: Env,
  name: "GITHUB_TOKEN" | "ADMIN_TOKEN" | "GITHUB_WEBHOOK_SECRET",
): string | null {
  const value = Reflect.get(env, name);
  return typeof value === "string" && value ? value : null;
}
