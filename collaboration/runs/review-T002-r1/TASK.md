# T-002 Review Task Packet

Read-only review. You are NOT the coordinator. Do not run commands, write files, or
declare product acceptance. Return a review; the coordinator applies it.

## What T-002 claims to deliver

A local-only single entry point that safely starts, stops and restarts the
Gateway process the Hub itself owns, with UI state consistent with real
tool availability.

Ticket: `D:\AI-Lab\MCP HUB\.harness\tickets\T-002.md`

## Code under review

- `D:\AI-Lab\MCP HUB\app\src\gateway-controller.js`  (the substance)
- `D:\AI-Lab\MCP HUB\app\src\server.js`
- `D:\AI-Lab\MCP HUB\app\src\config.js`
- `D:\AI-Lab\MCP HUB\app\bin\launch.js`
- `D:\AI-Lab\MCP HUB\app\start-hub.cmd`
- `D:\AI-Lab\MCP HUB\app\public\index.html`, `public\app.js`
- `D:\AI-Lab\MCP HUB\app\test\gateway-controller.test.js`

## Recorded manual test evidence

`D:\AI-Lab\MCP HUB\.harness\review-notes\T-002.md`

Read this first. It contains the actual observed outputs, including two failure
scenarios (port squatter, corrupted PID file) and the known-limitations section.

## Acceptance criteria being judged

1. Local single entry opens a usable interface; no terminal typing in daily use.
2. Start / stop / restart change real Gateway availability; a failed start must
   not display Running.
3. Closing the admin tab does not stop the Gateway; reopening still works.
4. Stale PID, unconfirmable process identity, and another process occupying the
   port must all produce a clear error and must never stop a process the Hub
   does not own.
5. The admin page is local-only; the iPhone's private remote path cannot open it.

## Your task

For each criterion, judge whether the recorded evidence actually establishes it,
or whether the conclusion is stronger than the evidence supports.

Look specifically for:

- **Claim gaps.** A criterion marked PASS on the basis of unit tests plus a UI
  status string, where real downstream tool calls were not shown. Distinguish
  "the code path looks right" from "this was observed".
- **Untested failure modes in gateway-controller.js.** It shells out to the
  1mcp CLI and imposes deadlines. What states can it report that are not
  `running`/`stopped`/`starting`/`error`, and are they handled? What happens if
  the CLI succeeds but writes nothing parseable? What if `parseStatus` sees an
  exit code it does not recognise?
- **The readiness contract.** `start()` deliberately ignores the CLI's own
  "Servers: X/Y ready" tally and re-checks via `--status` / `/health/ready`.
  Does that actually prove tools are callable, or only that the HTTP server
  answers? Is the difference material to criterion 2?
- **server.js route surface.** Four routes, all returning the controller result
  verbatim. Is there an authorization, CSRF or method concern for a local-only
  admin page bound to 127.0.0.1 that other processes on the machine can reach?
  Note: only the loopback binding was tested; cross-user local access was not.
- **config.js.** `hub.host` is hardcoded 127.0.0.1. Is there any path by which
  the admin page could become reachable off-host? Is `ensureGatewayConfigDir`
  doing anything unsafe?
- **Anything the evidence claims that the code cannot deliver**, and anything the
  code does that no criterion covers.

## Output format

A review, not a patch. For each finding give:

- the criterion or file it concerns
- what is wrong or missing
- a concrete counterexample or probe that would expose it
- severity: blocking or non-blocking

If you believe a criterion is not established by the evidence, say so explicitly
and name the specific additional test that would settle it. Do not soften a gap
into a note.
