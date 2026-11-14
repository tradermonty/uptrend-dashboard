# Protected development previews

The devcontainer starts `streamlit run app.py --server.enableCORS true --server.enableXsrfProtection true`. These explicit CLI settings keep both protections enabled, including when a local/global configuration or environment value differs. App entrypoint, port 8501 and automatic `openPreview` forwarding are unchanged. Configuration precedence and the role of these settings are described in the [Streamlit configuration reference](https://docs.streamlit.io/develop/api-reference/configuration/config.toml).

CORS and XSRF checks are request protections, not authentication or a port-visibility policy. Codespaces forwarded ports are private by default; organization/public sharing changes who can access the service. Inspect the actual visibility of port 8501 in the **Ports** tab and keep it **Private** for personal development. For VS Code local forwarding, keep the local listener on loopback and avoid sharing a tunnel/public URL. See [GitHub's forwarding documentation](https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace).

## Start and inspect

1. Rebuild/reopen the devcontainer after updating its configuration, and ensure the server started by the current `postAttachCommand` is the process serving port 8501.
2. In **Ports**, confirm the port is private, then open its forwarded URL. Authenticate to GitHub where required. Check that the dashboard loads and a selector rerun works, with no browser CORS/WebSocket errors.
3. If the embedded preview has browser/cookie/authentication limitations, open the same private forwarded URL in a browser tab. Keep the protection flags enabled.
4. If a legitimate reverse proxy rewrites the host and causes a WebSocket-origin mismatch, inspect its actual forwarded host/origin. Configure only the verified exact `browser.serverAddress` in your local settings and restart with both protection flags retained, for example:

```bash
streamlit run app.py --server.enableCORS true --server.enableXsrfProtection true \
  --browser.serverAddress YOUR-EXACT-FORWARDED-HOST
```

Replace the placeholder with the actual hostname; do not add a wildcard origin/host or commit a per-user Codespace hostname to the shared configuration. The [Streamlit server-address setting](https://docs.streamlit.io/develop/api-reference/configuration/config.toml#browser) is used for browser connection and CORS/XSRF purposes. If the failure persists, diagnose the headers/session rather than turning protections off. This repository ships no protection-disabling override.

## Verification evidence and boundary

`tests/test_devcontainer_security.py` extracts the actual devcontainer command. A subprocess runs a synthetic temporary `app.py` on a random **127.0.0.1-only** port with usage statistics disabled and no user credentials passed through its environment. It does not execute the dashboard, read the tracked database, or contact Finviz.

The tests check effective CORS/XSRF booleans despite contrary environment values; serve HTML; complete an actual WebSocket handshake and protobuf rerun that renders a known marker; accept an exact proxy-style Host/Origin pair; reject an unrelated Origin with 403; and reject a tokenless upload PUT with 403. A matching XSRF cookie/header pair makes the same deliberately invalid-session request reach ordinary application validation (400), distinguishing token protection from an unrelated route/access failure. Readiness/message waits and subprocess cleanup are bounded. The client uses the standard library, avoiding a dependency on whichever server backend Streamlit installs.

The focused tests pass in both local dependency environments. Local proxy-header simulation does **not** prove a hosted Codespace's forwarding/authentication/browser behavior. No hosted Codespace was created, port-sharing policy changed, or public deployment exercised for this change. Use steps 1–4 above for hosted verification and record the Codespace/Streamlit version and observed result; a health HTTP 200 alone is not sufficient. No exploit or unintended public exposure has been established by this configuration review.
