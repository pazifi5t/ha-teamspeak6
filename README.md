# TeamSpeak 6 for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Validate](https://github.com/pazifi5t/ha-teamspeak6/actions/workflows/validate.yml/badge.svg)](https://github.com/pazifi5t/ha-teamspeak6/actions/workflows/validate.yml)

See who is on your self-hosted **TeamSpeak 6** server — without joining it yourself.

The integration reads the server's **WebQuery** (HTTP query) with a read-only API key. It runs locally, needs no extra service and no Python dependencies.

![Icon](custom_components/teamspeak6/brand/icon.png)

## Features

- **Sensor `Online`**: number of connected users (ServerQuery connections are filtered out), with attributes
  - `users` – sorted list of nicknames
  - `channels` – non-empty channels in server order, each with its users; spacer prefixes like `[cspacer]` are removed
  - `max_clients`
- **Events** `teamspeak6_client_joined` / `teamspeak6_client_left` with `nickname`, `channel`, `server`, `client_database_id` and `rejoin`
- **Reconnect detection**: a user who comes back within a configurable window is flagged with `rejoin: true`
- **No notification flood** after a restart of Home Assistant or the TeamSpeak server: the first poll only sets a baseline
- Channel list is refreshed every 5 minutes, or immediately when someone appears in a new channel
- Setup via the UI, re-authentication when the key is rejected, diagnostics with secrets redacted
- **Blueprint** for push notifications and an example **dashboard card**

## Requirements

- TeamSpeak 6 server with WebQuery enabled (TeamSpeak 6 no longer has the raw telnet query; SSH and HTTP query remain)
- A read-only API key
- Home Assistant 2025.2 or newer

### 1. Enable the query interfaces on the server

Either in `tsserver.yaml` under `query:` (`ssh: enable: 1`, `http: enable: 1`) or via environment variables. With a systemd service, a drop-in survives server updates:

```ini
# /etc/systemd/system/teamspeak.service.d/query.conf
[Service]
Environment=TSSERVER_QUERY_HTTP_ENABLED=1
Environment=TSSERVER_QUERY_SSH_ENABLED=1
Environment=TSSERVER_QUERY_ADMIN_PASSWORD=choose-a-strong-password
```

```sh
systemctl daemon-reload && systemctl restart teamspeak
```

Default ports: **10022** (SSH query) and **10080** (WebQuery). Keep them inside your LAN – do **not** forward them on your router.

### 2. Create a read-only API key

```sh
ssh serveradmin@127.0.0.1 -p 10022
```

```
apikeyadd scope=read lifetime=0
```

Test it from the Home Assistant host:

```sh
curl -s -H "x-api-key: YOUR_KEY" http://TS_SERVER_IP:10080/1/clientlist
```

## Installation

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories**
2. Repository: `https://github.com/pazifi5t/ha-teamspeak6`, type **Integration**
3. Install **TeamSpeak 6**, restart Home Assistant

### Manual

Copy `custom_components/teamspeak6` into your `config/custom_components/` and restart.

## Configuration

**Settings → Devices & services → Add integration → TeamSpeak 6**

| Field | Default | |
|---|---|---|
| Host | – | IP or hostname of the TeamSpeak server |
| WebQuery port | 10080 | |
| API key | – | `scope=read` is enough |
| Virtual server ID | 1 | |
| Use HTTPS / Verify SSL | off / on | for a WebQuery behind TLS |

**Options** (⚙ on the integration): polling interval (default 15 s, minimum 5 s) and reconnect window (default 60 s, 0 = off). Very short intervals can trigger the query flood protection.

## Notifications

Import the blueprint:

[![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fpazifi5t%2Fha-teamspeak6%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fteamspeak6%2Fnotify_on_join.yaml)

It notifies a Companion App device, lets you ignore nicknames (e.g. your own) and quick reconnects, and supports `{nickname}`, `{channel}` and `{server}` in the message.

Or build your own automation on the event:

```yaml
triggers:
  - trigger: event
    event_type: teamspeak6_client_joined
conditions:
  - "{{ not trigger.event.data.rejoin }}"
actions:
  - action: notify.notify
    data:
      message: "{{ trigger.event.data.nickname }} joined {{ trigger.event.data.channel }}"
```

## Dashboard card

See [`examples/markdown-card.yaml`](examples/markdown-card.yaml). It shows users grouped by channel and distinguishes "nobody online" from "server not reachable".

## Privacy

Nicknames end up in Home Assistant's state history like any other attribute. The API key is stored in the config entry and redacted from diagnostics. Nothing leaves your network.

## Disclaimer

Not affiliated with or endorsed by TeamSpeak Systems GmbH. TeamSpeak is a trademark of its owner.

## License

[MIT](LICENSE) © pazifi5t
