# Private smart-home controls

Open **More tools → Smart home** over HTTPS. This is a separate, opt-in web area;
smart-home credentials, device status and alarm states never enter receipts,
public previews, ordinary finance/document exports or routine private backups.
Home Assistant is not required.

## What is available

- **Tapo/Kasa cameras**, including a connection path for the C212 family: status,
  privacy on/off and small pan/tilt commands when the firmware reports support.
  Turning camera state off enables the privacy mask. No camera video, audio,
  recordings, RTSP links or browser-accessible device credentials are exposed.
- **Compatible Tapo/Kasa plugs and lights**: power, brightness and colour
  temperature, only where the connected device exposes the matching capability.
- **Compatible thermostats**: target temperature only when the device reports
  Celsius and a supported writable target. The app limits changes to 5–30°C and
  the device's own range, in half-degree steps. A C212 is a camera, not a heater.
  Hub-attached devices can be addressed using their child device ID.
- **New Yale Smart Alarm**, Global-region Yale Home accounts including the UK:
  cloud-reported status, selection of one alarm area, and manual arm-home,
  arm-away and disarm commands. Yale email verification is supported. Every
  alarm command needs a fresh app authenticator/recovery code and exact typed
  confirmation. There is no force-arm, sensor bypass, panic trigger, lock-unlock
  integration or automatic alarm/camera linking. Older Sync/Smart Living hubs
  use a different service and are not supported by this connector.

The local Tapo/Kasa adapter uses the community `python-kasa` library, pinned to
0.12.0. Its camera protocol supports a number of related models, but this project
has not been tested against the owner's physical C212 or its firmware. Some Tapo
firmware requires **Tapo app → Tapo Lab → Third-Party Compatibility**. Devices
still need to be configured in their vendor app first. Manufacturer/firmware/API
changes can break compatibility; no unsupported control is invented.

The Yale adapter is independently implemented against the public mobile-cloud
protocol. It is not a Yale-certified integration. Its fixed application identifier
is public client metadata, not an account access token. Account passwords,
verification step tokens and access tokens are encrypted. The app does not read
confidential developer documentation, bypass Yale email verification, retry
alarm-changing requests or change alarm sensor settings. The actual alarm and
account have not been tested here. Keep the Yale app/keypad available and verify
operation on your own system before relying on this additional interface.

## Install and enable HTTPS

The basic web app does not need extra device libraries. For Tapo/Kasa controls,
install the reviewed optional pins in the same virtual environment as the app:

```bash
python -m pip install -r requirements-smart-home.lock
```

This vault requires Linux/macOS owner-only file permissions. Browser clients may
use any supported desktop or mobile OS. Run the web application as a dedicated
unprivileged user and keep the server, browser and device firmware updated.

**Plain HTTP is refused, even on localhost.** Existing receipt pages may continue
to use their existing transport, but credentials for Smart home must never be
entered over HTTP. Do not add an insecure exception to get around this check.

Use a private HTTPS reverse proxy on the same machine as Waitress. For example,
Caddy can issue an internal certificate for a local name:

```caddyfile
receipt.home.arpa {
    tls internal
    reverse_proxy 127.0.0.1:5050
}
```

Set your local DNS to point that name at the server. Trust Caddy's root certificate
on each client using your normal operating-system certificate settings; do not
ignore browser certificate errors. Before starting Receipt Control, set:

```bash
export RECEIPT_WEB_HOST=127.0.0.1
export RECEIPT_WEB_PORT=5050
export RECEIPT_TRUST_PROXY=1
export RECEIPT_WEB_SECURE_COOKIE=1
```

Start it using your normal Waitress launch method and visit the HTTPS name.
The existing trusted-proxy middleware accepts the forwarded HTTPS scheme only
from loopback. Preserve the original Host header. Do not trust arbitrary external
forwarded headers, expose the raw Waitress port, or enable Flask debug mode.

For access from another network, use a private VPN/tailnet with HTTPS, such as
Tailscale Serve. Limit access to your own users/devices, keep Funnel/public
publishing disabled, and retain all web authentication. HTTPS alone is not a
reason to forward the receipt app or a camera/alarm port to the public internet.
The application server must still reach the Tapo devices on their private LAN.

## First-time setup

1. Sign in to Receipt Control over HTTPS and open Smart home.
2. Confirm the existing web login password and choose a **different smart-home
   passphrase of at least 16 characters**. A long, unique password-manager phrase
   is preferable to a reused password.
3. Add the displayed setup key to an authenticator using SHA-1, six digits and
   a 30-second period. Setup keys are generated locally, never sent to an online
   QR-code service.
4. Save the eight one-use recovery codes somewhere separate from the server and
   encrypted backups. Confirm a valid authenticator code to create the vault.
5. Add devices, then check their status. Compare the reported model and MAC/hub
   serial with the intended device before trusting its identity for controls.

A previously used authenticator counter cannot be reused. Wait for the next
30-second code when necessary. Recovery codes are uppercase, one-use, and can
also authorize alarm commands. Keep the machine and authenticator clocks correct.

For Tapo/Kasa, use a fixed/reserved **private IPv4 address**. Only explicit RFC1918
LAN addresses are accepted; URLs, hostnames, public addresses, link-local/cloud
metadata addresses, loopback and custom ports are refused. Discovery is directed
to the saved host, not broadcast across the network. The app checks the reported
device category and saved identity before a command. This is an identity check,
not a claim of hardware attestation or a substitute for secure device firmware.

For Yale, use the separate Yale account form. Check status to begin sign-in. If
Yale asks for verification, explicitly request the email code and enter it in the
Yale email-code field. Select the intended hub and area, check status again, and
verify its serial before trusting it. **Reconnect Yale** clears the saved vendor
session if it expires. This never changes the physical alarm state.

## Access, commands and expiry

- Both the normal app login and a separate passphrase plus authenticator/recovery
  code are required. Failed unlocks are rate-limited using owner-only persistent
  counters, including a global attempt limit.
- The opaque unlock cookie is Secure, HttpOnly, SameSite=Strict and scoped to
  `/smart-home`. Decryption keys stay only in server memory. It expires after
  five minutes, does not extend with activity, and is invalidated on lock/logout,
  process restart or passphrase change. Multiple-process deployments fail closed
  rather than sharing keys; use the normal single Waitress process.
- Every POST also needs the app's CSRF token, same-origin HTTPS, a one-use
  operation ticket and a still-valid unlock. Physical changes require explicit
  confirmation; alarm changes require a new MFA/recovery code and typed command.
- No devices are polled just by opening a page. Status is requested manually and
  labelled with its check time. A failed check clears the displayed result.
- Private pages use no-store headers, restrictive CSP, framing protections and
  a same-origin referrer policy that suppresses external referrers. Browser page content is cleared on expiry/navigation when scripts
  run; the server independently refuses expired requests. No software can erase
  copies, screenshots or data already seen by an authorized browser.
- Device requests run in disposable, bounded workers. Credentials travel to the
  worker over stdin, not shell arguments. SDK logging and worker stderr output
  are suppressed. Errors exposed by the app are fixed/redacted messages.
- Yale requests use a fixed verified-HTTPS cloud endpoint, no proxy environment
  credentials or redirects, bounded responses and no automatic command retry.
  A cloud failure or unknown status never becomes a false “disarmed” result.
  Cloud status can lag, especially during an exit delay; verify with the vendor
  app or keypad. After any timeout, check state before retrying a command.

## Storage, backup and recovery

The ignored `data/smart_home/` directory is owner-only (0700); vault and limiter
files are owner-only (0600), with no-follow checks for private reads and directory
symlinks. Credentials, account tokens, device selections and a small audit history
are inside an authenticated Fernet ciphertext. The key is derived using scrypt
(N=131072, r=8, p=1) and a random salt. No decryption key is stored on disk.

Use **Download encrypted smart-home backup** while unlocked. The file stays
encrypted and contains no passphrase/key. Routine receipt backups intentionally
exclude it. Back up recovery codes separately. MFA protects the web unlock; an
offline copy's confidentiality depends on the strength of the passphrase and KDF.

To restore a saved encrypted vault, stop the app, preserve the current encrypted
file first, and put the chosen backup at `data/smart_home/vault.enc` with owner-only
permissions. Restart, unlock with that backup's passphrase and a current code from
its authenticator (or an unused recovery code from that backup). A restored old
backup may restore previously consumed recovery codes: retire old copies and
change device/account credentials if an old backup may have been exposed. Do not
edit the encrypted JSON or merge it through the ordinary private-backup screen.

Changing the passphrase re-encrypts the current file and locks every smart-home
session. It cannot revoke or re-encrypt backups already copied elsewhere. If the
passphrase and recovery access are lost, there is no secret master-key recovery;
use the vendor apps to control devices and reconfigure a new vault deliberately.

## Limits and threat model

This protects against someone reaching the website without the extra unlock,
accidental plaintext/Git/receipt disclosure, cross-site requests, ordinary stale
form replay and unintended generic device commands. It does not protect an
unlocked browser or compromised server/admin account, malicious extensions,
keyloggers, memory dumps, insecure vendor firmware or cloud compromise. Use disk
encryption, appropriate OS permissions, secure Wi-Fi/device network segmentation
and trusted clients. Keep original vendor controls available. Device/account
configuration and MFA enrollment must be completed by the owner; no real device
or alarm was accessed while implementing this feature.

## References

- [python-kasa source and supported hardware](https://github.com/python-kasa/python-kasa)
- [TP-Link third-party compatibility](https://www.tapo.com/uk/faq/714/)
- [Yale Smart Alarm product/app support](https://yalehome.co.uk/support/product-support/apps-and-integrations/)
- [Public newer-alarm protocol integration reference](https://github.com/hiall-fyi/yale_smart_alarm_ce/)
- [TOTP specification](https://www.rfc-editor.org/rfc/rfc6238)
- [OWASP password/KDF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
- [Caddy local HTTPS](https://caddyserver.com/docs/automatic-https)
- [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve)


## Private house layout

Each Yale alarm card has an **Edit private house layout** panel. Add named rooms,
group them by floor, and set their positions and sizes as percentages of the drawing.
After checking Yale status, select a reported sensor and place it within a room.
Room names, geometry and sensor positions are encrypted inside the same vault as
the connection details. They are not included in daily receipts, public previews,
or ordinary backups. The separate encrypted smart-home backup includes the layout.
Editing the diagram does not change Yale areas, sensor configuration or alarm state.

The responsive floor plan uses text and symbols as well as colour. It distinguishes
an explicitly reported alarm trigger, an open door/window, motion, tamper, a fault,
an offline sensor and unavailable trigger information. A closed contact or an
unreported PIR trigger does **not** mean the whole house is clear. Yale may report
an alarm area as triggered without identifying which individual PIR caused it; the
page explicitly says so. Missing or failed sensor reports produce unknown markers,
never an invented all-clear. The plan is an on-demand snapshot updated with the
status button, not a continuously monitored alarm or emergency notification system.
Keep using the Yale app/keypad and its alarm notifications.
