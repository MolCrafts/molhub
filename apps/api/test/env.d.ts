declare namespace Cloudflare {
  interface Env {
    TEST_MIGRATIONS: D1Migration[];
    ADMIN_TOKEN: string;
    GITHUB_WEBHOOK_SECRET: string;
    GITHUB_TOKEN: string;
  }
}
