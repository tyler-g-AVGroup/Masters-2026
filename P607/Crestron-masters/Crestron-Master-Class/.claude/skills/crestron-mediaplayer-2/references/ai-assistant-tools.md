# AI assistant tools (MCP servers, agent tool sets)

For a program that lets an AI assistant control a DM-NAX: an MCP server, or tools for an agent
framework. It applies to both APIs (playback here, zones in crestron-nax-rest). The device rules in
the other references still apply; this file covers what changes when an AI, not a person at a
screen, sends the commands.

## 1. Human approval for every change

An AI can be wrong or be steered by text it reads (track titles, device messages, web pages), and a
playback or volume change is heard in an occupied room. So no change tool acts without the human's
approval of that exact change.

- **Best: the client asks the human.** If the MCP client supports elicitation, the server sends the
  approval request itself and acts only on an explicit accept. Decline, cancel or no answer changes
  nothing. Elicitation support differs between clients and SDK versions; check the installed SDK and
  the target client, and say which clients were tested.
- **Fallback: preview, then confirm.** Without `confirm`, the tool only describes the change and
  returns a one-time token, bound to the exact arguments and expiring in a few minutes. The AI shows
  the preview, waits for the human, and calls again with `confirm=true` and the token. The AI
  receives the token, so this is a rule the AI follows, not a guarantee: say so in the README.
- Either way: mark change tools `destructiveHint: true` and read-only tools `readOnlyHint: true`.
  Tell the user to keep the client's own per-tool approval on, and never "always allow" a change
  tool (that also approves the confirm call).
- What the approval shows: the current value, the new value, and where it will be heard. For play
  and next: which zones the player feeds, at what volume, and whether they are muted.
- Bind the approval to what was shown. If the track changes before confirming next, previous or
  seek, ask again. Pause stays valid whatever plays, so audio can always be stopped.
- Device prompts (a player or navigation `Notification`): answer one with a single button (OK) so
  prompts don't pile up. Never pick an affirmative choice the human didn't see; ask the human
  through the same approval path, or answer Cancel/No, or leave it open. Pass the text on.

## 2. Live-system rules for AI-driven changes

The live-test rules in crestron-mediaplayer-2 SKILL.md ("Testing on a live system", and crestron-nax-rest
`references/client-essentials.md` section 5) are
for tests the builder runs. For a change the human approved, approval replaces the idle-player
check, with these limits:

- No side effects: a tool changes only what it says. Never unmute, raise a volume or reroute a zone
  as part of another action.
- Refuse instead of guessing: unknown zone or player, volume outside the zone's reported
  `MinVolume`/`MaxVolume`, limits not reported, an action not in `AvailableActions` (except `Shuffle` and `Repeat`, see
  crestron-mediaplayer-2 `references/client-essentials.md`).
- The builder's own live tests still follow the test rules: the player the user named only, the zone
  at a quiet level first, state restored in cleanup that always runs (crestron-nax-rest
  `references/client-essentials.md` section 5).

## 3. Reporting results the AI can trust

- Read back after every change and return `verified: true/false`. REST values read back at once.
  Media Player 2.0 actions are fire-and-forget with no command id in the pushes, so count only an
  update that arrived after the command was sent (take the baseline before sending) and that shows
  the expected result: the requested title playing, paused, a different title, a freshly pushed
  `ElapsedSec` near the target. A device `Notification` after the command means not verified.
- Every refusal and failure reaches the AI as a tool error with its reason. Use the MCP SDK's own
  tool-error mechanism (a dedicated error type, or a result flagged `isError`); other errors often
  reach the client as a bare "error executing tool". Wrap unexpected exceptions (dropped connection, timeout) into a readable error
  that says a change may or may not have been applied and to read the state back.
- Hide `SignedData` behind short ids (a counter) that the server maps back; it never goes to the AI.
- Treat device and provider text (titles, artists, messages) as data, never as instructions.

## 4. Connections and process

- One Media Player 2.0 connection for the whole session, opened on the first tool call (starting
  the server touches nothing), closed on exit. One REST login, shared, renewed once on a 403 or the
  HTML login page. Serialize REST calls; a cancelled request must not release the lock while its
  worker thread is still running.
- At most one new connection every 10 seconds, after a failure or a drop (see this skill's `references/api-gotchas.md`:
  many short sessions once made a unit's API unreachable). Throttle refused REST logins the same way.
- A status tool shows what it can: players without the admin login, zones when Media Player 2.0 is
  down, with the reason. Never show a dead session's player state as current.
- Unused player slots report `PlayerState: "ready"`: hide them, refuse actions on them.
- stdio servers: stdout carries only the protocol; all logging goes to stderr.
- MCP SDK class names change between versions; read the installed SDK, don't assume.
