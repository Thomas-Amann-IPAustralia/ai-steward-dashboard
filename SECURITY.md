# Security

## Reporting a vulnerability

Please report security problems privately through GitHub: open the
repository's **Security** tab and choose **Report a vulnerability**. Do not
open a public issue.

Reports are acknowledged within five working days. Please include what you
found, how to reproduce it, and what an attacker could do with it.

## What is in scope

- The public dashboard at
  <https://thomas-amann-ipaustralia.github.io/ai-steward-dashboard/>.
- The pipeline in this repository (`main.py`, `transparency_watch.py`,
  `news_watch.py`, `steward/`) and the GitHub Actions workflows that run and
  deploy it.

The monitored websites themselves are out of scope; report problems with
them to their owners.

## Repository settings the workflows expect

- **Secrets in environments.** `GEMINI_API_KEY` and the optional `PROXY_*`
  secrets belong to the `pipeline` environment, which only the collect job
  uses. The optional data-publisher App's key belongs to the `data-publish`
  environment. Restrict both environments to the `main` branch.
- **Pushing past the main-branch ruleset.** A ruleset on `main` that requires
  pull requests and the `python` and `frontend` status checks would also
  block the nightly data commit, because the workflow's own token cannot be
  exempted from a ruleset. A GitHub App can. Create one with
  *Contents: read and write* on this repository only, install it, save its
  client ID as the `DATA_PUBLISHER_CLIENT_ID` variable and a private key as
  the `DATA_PUBLISHER_PRIVATE_KEY` secret of the `data-publish` environment,
  and add the App to the ruleset's bypass list. The publish job then pushes
  as the App; until it exists, it pushes with the workflow's token, as
  before.

## How the project protects itself

The design decisions, and the reviews behind them, are recorded in
[`docs/reviews/`](docs/reviews/). In short:

- Every request the pipeline makes is limited to public addresses (checked
  again on every redirect), capped in size, and its error text is scrubbed of
  secrets before anything is published.
- Third-party text reaches the model only inside fenced, labelled blocks, and
  the model's output is schema-checked and rendered without links or images.
- The job that reads third-party content holds no token that can write to the
  repository or deploy the site. Writing and deploying happen in separate
  jobs that run no third-party code.
- The site is served with a Content-Security-Policy that allows nothing but
  its own origin.
