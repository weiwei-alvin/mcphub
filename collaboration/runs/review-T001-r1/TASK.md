# Review task: T-001 (code-review-audit, round 1)

## Role
You are the delegated reviewer. You inspect evidence only. You cannot execute anything, so every claim you make about runtime behaviour must be marked [UNVERIFIED] unless it is directly visible in the files below. The coordinator applies nothing from you automatically; the human operator records the final verdict.

## Files in this packet (read all of them)
- ticket-T-001.md — the approved ticket (the requirement source; do not propose changing it)
- handoff.json, handoff-narrative.md — the developer's claims
- verify-ticket-final.json — harness receipt for the automated step AT-001
- check.py, acceptance-README.md — the automated acceptance checker and its contract (unchanged by this ticket)
- fixture.json — the secret-free fixture the checker used
- gateway-mcp.json, http-loopback.mjs — test-environment configuration created for this ticket
- versions.json — recorded versions
- gateway-log-excerpt.txt — gateway log lines for the iPhone calls (source 100.88.86.52) and the unauthorized-source probe (100.79.209.7); the account login is redacted

Screenshots exist but are NOT in this packet; treat anything that depends only on screenshots as [UNVERIFIED].

## Review rules (apply each one)
- REV-1 Requirement verification: check every Acceptance criterion in the ticket against evidence. Do not accept a criterion just because the handoff says PASS.
- REV-2 Independent verification: you have no execution environment, so this is evidence inspection only. Cross-check handoff claims against the receipt, the log excerpt and the configuration files. List each key item you could not confirm as [UNVERIFIED].
- REV-3 Scope adherence: is anything built or configured beyond what T-001 requires? Flag unjustified extras.
- REV-4 Quality: check the configuration and the http-loopback.mjs shim for error-prone logic, missing error handling, or security risk (exposure beyond tailnet, credentials, admin surfaces). Do not ask for new abstractions.
- REV-5 Findings: each finding needs a stable kebab-case finding_key.
- REV-7 Verdict: recommend exactly one of PASS, FIX_REQUIRED, USER_DECISION_REQUIRED, with reasons.

## Output format (plain Markdown, no tool use needed beyond reading)
1. A table: each ticket Acceptance criterion -> evidence file and line/field -> CONFIRMED / [UNVERIFIED] / NOT MET.
2. Findings list: finding_key, criterion_ref (AT-001 or the criterion text), description, blocking (true/false), concrete counterexample or the exact evidence gap.
3. Recommended verdict and one paragraph of reasoning.

Do not claim you ran any command. Do not write files.
