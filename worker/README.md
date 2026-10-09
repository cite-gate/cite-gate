# cite-gate hosted MCP endpoint

A Cloudflare Worker that serves the same two tools as the local server
(`check_citations`, `check_numbers`) over MCP Streamable HTTP at `POST /mcp`.

* `src/check.js` is a JavaScript port of `cite_gate/check.py`. `test/parity.test.mjs` runs both on the
  same inputs and requires identical reports, so the two can't drift apart unnoticed.
* Hosted limit: 3,000 characters of prose per call (keeps each call well inside the free plan's CPU
  budget). Longer scripts: run the local server.
* Privacy: the endpoint does not store script text, quotes or sources. Per call it records the minute,
  the tool name, pass/fail counts, the client name your MCP client reports, a bot/self flag and a
  daily-rotating hash of the IP. Rows are kept for up to three months (the Workers Analytics Engine
  retention) and then deleted automatically. Without the `LOG` binding nothing is recorded.

```
npm test                      # needs Node 20+ and Python 3.10+ (for the parity test)
npx wrangler secret put SALT  # once, random string for the daily IP hash
npx wrangler deploy
```
