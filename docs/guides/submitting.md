# Submitting

Open the Product Web’s **Submit** page. It builds a complete manifest with any number of artifacts and
ordered locators, validates through the shared contract, and sends it to the submission API. You do
not need to edit GitHub YAML to make a proposal.

After submission, keep the receipt URL. Reviewers see the canonical YAML and source metadata, then
approve it into a pull request or reject it with a required note. Contributor email is stored for the
workflow but omitted from the reviewer queue and logs.

GitHub remains available for maintainers and bulk changes: create the same path
`artifacts/<kind>/<namespace>/<name>/<version>.yaml` in `molhub-registry` and open a pull request.
