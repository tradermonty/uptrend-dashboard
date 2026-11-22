# Issue #17: protected development preview defaults

Status: FINAL — independent plan review approved in round 1 without findings.
Base: main `2aa04503257035d06a2377fbeccf12a383bf8f37`.
Worktree `/private/tmp/uptrend-issue-17`, branch `fix/issue-17-preview-protections`.

## Selection / scope

P2 #17 has no matching assignee, claim, PR, remote branch or worktree. Active #23–#26 address other source surfaces; remaining P1 work has open PRs or dependencies/overlap. Change only devcontainer protection defaults, tests and development documentation. Recheck overlap/main before delivery and test combination with active PRs in a disposable tree.

No app/data/DB/CSV/business logic, dependencies, port-visibility mutations, hosted Codespace creation, deployment, merge, or live external API calls. The current flags are a configuration weakness; no exploit or unintended public exposure has been established.

## Implementation

1. Replace `--server.enableCORS false --server.enableXsrfProtection false` in `.devcontainer/devcontainer.json` postAttach server command with explicit `true` values. Explicit CLI values ensure these defaults win over a contrary global/env setting. Preserve app.py, port 8501, existing forwarding/openPreview behavior and other devcontainer setup.
2. Add regression tests parsing this file's JSON-with-full-line-comments style, then shell-splitting the actual launch command. Check both protection flags are explicitly true and not later overridden; preserve the intended entrypoint and forwarding configuration. No production JSONC parser or new dependency is needed.
3. Add a real local Streamlit subprocess smoke test based on the exact configured launch arguments, substituting only the interpreter, a temporary app.py and loopback/random port/headless/usage-stat settings. Temporary app writes its effective CORS/XSRF settings to a temp artifact and emits a known display marker. Never run the real data-loading app for this server test. Close sockets, terminate/wait/kill child process in finally; bound readiness/message waits and include safe diagnostics on failure. Test both available local dependency environments; CI runs its declared Python version.
4. Verify health/HTML readiness AND a successful same-origin WebSocket session that actually executes the synthetic app (send a Streamlit rerun BackMsg; inspect the marker/config artifact). Verify a proxy-style exact Host/Origin pair for a forwarded preview also connects. A random unrelated Origin WebSocket handshake must be refused with 403.
5. Verify an upload PUT without an XSRF token returns 403, then repeat the same request with a valid health-issued XSRF cookie/header pair and require ordinary application-level invalid-session validation (400). This identifies the token check even when the server hides reasons in generic 403 bodies, rather than mistaking an unrelated route failure for protection. Record effective config booleans from the running app; a health 200 alone does not establish protection or usability. Exercise the command with contrary environment flags to verify explicit CLI protections remain enabled.
6. Document private forwarding for local VS Code/Codespaces, inspecting port 8501's actual visibility, opening the forwarded app URL, and checking browser/websocket/upload behavior. If a legitimate proxy hostname needs configuration, use an exact verified browser.serverAddress and retain protection flags; do not add wildcards or infer real Codespaces acceptance from local proxy-header simulation. Do not ship a protection-disabling override. Describe CORS/XSRF as request protections, not port access control.
7. Sync a dated component revision and devcontainer startup description in `docs/design.md`; add a dedicated preview-security operating note (and README link if appropriate, avoiding shared hunks). Keep hosted preview verification as an explicit evidence limit/checklist rather than claiming it was exercised.

## Test-first / review gates

Baseline full suite. Add configuration/runtime regressions before changing flags; verify meaningful failures on old settings. Fix the defaults and run focused tests green, full pytest, diff check, and combined active-PR compatibility. Network tests use loopback only and a synthetic app, with no secrets or published data. Run sandbox escalation only for authorized local socket execution if required; no external server exposure.

Independent sub-agent plan review and corrections for at most three rounds; finalize only when all findings are resolved. Implement test-first, then independent code review and corrections for at most three rounds. If findings remain after round three, report the open gate. Otherwise commit/push a dedicated branch, open an English PR closing #17, and verify exact head/CI. Do not merge.

## Primary references checked

- Streamlit configuration: https://docs.streamlit.io/develop/api-reference/configuration/config.toml (CLI/env precedence, protection and server-address settings).
- GitHub Codespaces port forwarding: https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace (forwarded URLs and private/public sharing semantics).
- Installed Streamlit server handlers inspected to design real protocol-level checks; tests must not rely on private handler imports.

## Plan review log

- Round 1: APPROVE; no findings. Real protocol checks, cleanup, configuration precedence and hosted verification boundaries were independently checked.

## Code review log

- Round 1: APPROVE; no actionable findings. Reviewer independently ran all six focused tests and checked effective config, actual app execution, XSRF differential validation, cleanup and hosted evidence boundaries.
- Test implementation adjustment before review: newer Streamlit no longer supplies the optional Tornado client package, and generic 403 responses hide error reasons. Used a standard-library protocol client and a missing/valid-token comparison instead, without adding dependencies or weakening checks.

## Final validation

- Baseline full suite: 375 passed. Final focused tests on original disabled flags: 4 failed / 2 passed.
- All six focused tests pass in both local dependency environments. Final standalone suite: 381 passed on Python 3.14.3.
- Combined with #23 `7ddbe9c`, #24 `61ca119`, #25 `46597d0`, #26 `6d79111`: 671 passed, six existing upstream/test deprecation warnings, clean three-way documentation merge. Original worktrees unchanged.
- Runtime tests use only loopback and a synthetic temporary app, with no user credentials or live Finviz/data access. No hosted Codespace/browser-forwarding acceptance or port-visibility change was performed.
- `git diff --check` passed; no DB/CSV edits. Parallel PR heads rechecked unchanged before delivery; main is refetched at push.
