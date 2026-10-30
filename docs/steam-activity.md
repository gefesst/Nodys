# Local Steam activity

noda detects Steam activity without account linking on Windows and macOS. It is
client-reported information, not verified Steam account ownership or Steam online
status. Sharing is enabled by default and can be disabled immediately under
Settings → Активность. The device preference survives restart and logout.

## Data flow

- `client/integrations/steam.py`: read-only, bounded KeyValues parser, current-OS-user
  process enumeration via pinned psutil, Steam library manifests and executable
  paths. No passwords, tokens, process memory, command lines, or environment access.
- Windows: HKCU SteamPath and ActiveProcess/ActiveUser select the local identity.
- macOS: Steam's local registry AutoLoginUser selects the matching loginusers entry;
  unique MostRecent is the fallback when that registry value is absent. These are
  cached local hints, not proof that Steam is currently authenticated. An ambiguous
  or missing identity produces no published activity.
- Games must have a running executable inside their installed library directory.
  Known helper/launcher/crash processes are excluded. Multiple detected games produce
  no single game claim. Custom launchers, external executable paths and unsupported
  metadata can yield no game. Private Steam games can still be detected locally;
  the settings page explicitly explains this independent sharing behavior.
- `application/steam_presence.py`: one background detector, sampled every 5 seconds;
  Qt only polls completed futures. Changed state is sent through authenticated
  heartbeat; unchanged state is renewed every 15 seconds. No startup readiness gate.
  Disable discards pending scans and queues an empty update behind any older request.
- Only display nickname, game title and AppID are sent. Local paths, Steam login
  account names, SteamIDs, and the process list are never transmitted.
- `storage/steam_activity.py`: session-keyed state with a 45-second lease and ordered
  updates. Revoked/expired/offline sessions do not expose activity. Read results are
  enriched only after existing friendship/channel authorization; `find_user` does
  not reveal activity. Nothing is used for authentication or permissions.
- Friends, mini-profile and voice participants display plain-text, elided activity.
  Friends and room activity labels update in place without rebuilding the list.
  Remote refresh timing also depends on the existing screen polling interval.

## Validation

`python tools/check.py` includes Steam platform fixtures, extra libraries, macOS app
bundles, account switches, missing/partial metadata, helper exclusion, session
revocation, TTL, out-of-order updates, disable during a scan and channel access.
`tools/ui_review.py --synthetic-voice --relogin-cycles 5 --output <empty-folder>`
includes the settings page at two sizes and actual server-backed activity visibility
and clearing between two accounts. CI runs on Windows, macOS and Linux.

Native macOS read-only detection was exercised on the development machine. Native
Windows Steam and real running games still require device acceptance testing;
Windows CI validates the adapter logic with fixtures, not a logged-in Steam client.
