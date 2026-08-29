# Ganek Contributor License Agreement

<!--
Drafting record (DIY triple-check protocol):
- Pass 1 — sources: Apache Individual/Corporate CLA v2.2
  (apache.org/licenses), cla-assistant default CLA (SAP, Apache-derived).
- Pass 2 — adversarial review in a fresh context, 2026-08-30: 15 findings;
  fixes applied include per-Contribution grant timing + max-extent
  language (UrhG §§ 32/40 concerns), splitting the relicensing grant so
  only the Company receives it, Apache-pattern corporate flow (individual
  bot signature always required; corporate schedule by email, recorded
  in-repo), Project/Work definitions scoped to Ganek, severability,
  contact address.
- Pass 3 — real-world diff vs PostHog shipped practice + the
  contributor-assistant action docs, 2026-08-30.
-->

Thank you for contributing to Ganek. This agreement clarifies the terms
under which you contribute, so that your contribution can live alongside
both the AGPL-3.0 core and the commercial parts of the project (the
hosted service and the `ee/` directory) without ever needing to track
you down later.

**The short version:** you keep the copyright to your contribution. You
give Nestor Code Crafters UG (haftungsbeschränkt) a broad license to use
it — including in the hosted product and commercially licensed code.
You promise the contribution is really yours to give. Nothing here
obliges you to provide support.

Signing happens per GitHub account: our CLA bot asks you to sign with a
comment on your first pull request, once.

## Individual Contributor License Agreement

By signing, You accept and agree to the following terms and conditions
for Your present and future Contributions submitted to the Project.
Except for the licenses granted herein to Nestor Code Crafters UG
(haftungsbeschränkt), registered in Germany ("the Company") and
recipients of software distributed by the Company, You reserve all
right, title, and interest in and to Your Contributions.

1. **Definitions.** "You" means the individual signing this agreement.
   "The Project" means the Ganek software and the repositories under
   the ganek-dev GitHub organization. "Work" means the Ganek project to
   which a Contribution is submitted. "Contribution" means any original
   work of authorship, including any modifications or additions to an
   existing work, that is intentionally submitted by You to the Project
   for inclusion in, or documentation of, the Work. "Submitted" means
   any form of electronic, verbal, or written communication sent to the
   Project, including but not limited to pull requests, issues, and
   discussions, excluding communication that is conspicuously marked by
   You as "Not a Contribution."

2. **Grant of copyright license.** Each time You submit a
   Contribution, You thereby grant, effective on submission and to the
   maximum extent permitted by applicable law: (a) to the Company, a
   perpetual, worldwide, non-exclusive, no-charge, royalty-free,
   irrevocable copyright license to reproduce, prepare derivative
   works of, publicly display, publicly perform, sublicense, and
   distribute that Contribution and such derivative works, under any
   license, including copyleft, permissive, commercial, or proprietary
   licenses; and (b) to recipients of software distributed by the
   Company, a license to that Contribution under the license or
   licenses the Company distributes the containing software under.

3. **Grant of patent license.** Each time You submit a Contribution,
   You thereby grant to the Company and to recipients of software
   distributed by the Company a perpetual, worldwide, non-exclusive,
   no-charge, royalty-free, irrevocable
   (except as stated in this section) patent license to make, have
   made, use, offer to sell, sell, import, and otherwise transfer the
   Work, where such license applies only to those patent claims
   licensable by You that are necessarily infringed by Your
   Contribution alone or by combination of Your Contribution with the
   Work to which it was submitted. If any entity institutes patent
   litigation against You or any other entity (including a cross-claim
   or counterclaim in a lawsuit) alleging that Your Contribution, or
   the Work to which You contributed, constitutes direct or
   contributory patent infringement, then any patent licenses granted
   to that entity under this agreement for that Contribution or Work
   shall terminate as of the date such litigation is filed.

4. **You are entitled to grant this.** You represent that You are
   legally entitled to grant the above licenses. If Your employer has
   rights to intellectual property that You create that includes Your
   Contributions, You represent that You have received permission to
   make Contributions on behalf of that employer, that Your employer
   has waived such rights for Your Contributions to the Project, or
   that Your employer has signed the Corporate CLA below.

5. **Original work.** You represent that each of Your Contributions is
   Your original creation. Should You wish to submit work that is not
   Your original creation, You may submit it separately from any
   Contribution, identifying the complete details of its source and of
   any license or other restriction (including, but not limited to,
   related patents, trademarks, and license agreements) of which You
   are personally aware, and conspicuously marking the work as
   "Submitted on behalf of a third party: [named here]".

6. **No warranty, no support obligation.** You are not expected to
   provide support for Your Contributions, except to the extent You
   desire to provide support. Unless required by applicable law or
   agreed to in writing, You provide Your Contributions on an "AS IS"
   BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
   or implied, including, without limitation, any warranties or
   conditions of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS
   FOR A PARTICULAR PURPOSE.

7. **Notification.** You agree to notify the Project of any facts or
   circumstances of which You become aware that would make these
   representations inaccurate in any respect.

8. **Severability.** If any provision of this agreement is held
   unenforceable, the remaining provisions stay in effect, and the
   unenforceable provision applies to the maximum extent permitted by
   applicable law.

## Corporate Contributor License Agreement

Every contributor signs the Individual CLA above via the CLA bot,
including contributors acting for an employer. If the employer holds
rights to the contributions, the employer additionally accepts these
terms as a supplementary agreement: an authorized representative emails
the Project contact below stating that the corporation agrees to the
Corporate CLA and listing the GitHub accounts of covered employees.
The corporation thereby:

1. grants the licenses in sections 2 and 3 above for Contributions
   submitted by its listed employees;
2. represents that the signatory is authorized to bind the corporation;
3. agrees to keep the list of covered GitHub accounts current by email
   to the same address. The accepted agreement and its account list are
   recorded in the repository (under `signatures/corporate/`) so they
   are versioned and auditable;
4. acknowledges that it is the corporation's responsibility to notify
   the Project when an employee leaves or is no longer authorized to
   contribute on the corporation's behalf. Contributions submitted
   before such notice remain licensed.

All other terms of the Individual CLA apply to the corporation
accordingly.

**Contributions to `ee/`** are additionally governed by the terms in
[ee/LICENSE](ee/LICENSE); where the two documents overlap, this CLA
governs the license You grant, and ee/LICENSE governs Your use of the
`ee/` software.

**Project contact:** grumpy.miner.dev@gmail.com

## Why a CLA at all?

Ganek's core is AGPL-3.0 and always will be — nothing shipped under
AGPL ever moves to a commercial license (the "no clawbacks" rule in
[CONTRIBUTING](CONTRIBUTING.md)). But the same codebase will carry a
hosted service and, eventually, commercially licensed operator code
under `ee/`. Your contribution may be distributed as part of that
combined whole. This agreement is what makes that legally clean while
you keep your copyright. It is the same trade made by contributors to
projects like Cal.com and PostHog.
