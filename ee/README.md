# ee/ — commercial code (empty by design)

This directory is reserved for the code that runs Ganek **as a
service** — billing, plan quotas, tenant administration, custom-domain
provisioning, and enterprise IT integration (SAML/SCIM) when they are
built. It is covered by the [commercial license](LICENSE) in this
directory, not by the repository's AGPL-3.0 license.

Today it contains no code. That is deliberate: the boundary is declared
**before** anything closed exists, so you can hold us to it.

The rules (also published in [CONTRIBUTING](../CONTRIBUTING.md)):

- **The litmus test.** Anything a single company self-hosting Ganek
  needs in order to hire is AGPL core, forever. Only the
  SaaS-operator plane and enterprise IT integration live here.
- **No clawbacks.** Nothing shipped under AGPL ever moves into `ee/`.
- **Self-hosters are never metered.** Cloud plan limits are enforced by
  `ee/` hooks in the hosted product only; the open product has no
  hidden switches.
- **Security is never paid.** Account-security basics land in core.
