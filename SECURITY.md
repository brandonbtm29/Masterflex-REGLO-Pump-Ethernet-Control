# Security policy

## Reporting a vulnerability

Please **don't** open a public issue for security problems. Use GitHub's
"Report a vulnerability" button (Security tab → Advisories) to report privately.
I'll reply within a week.

## Security model

This is a desktop app for a lab bench. It is not a server and listens on no ports.

- **EtherNet/IP has no authentication.** Anyone who can reach the pump's IP address can
  start, stop or reconfigure it, with this app or any other EtherNet/IP tool. Keep the pump
  on an isolated lab network or a direct cable, never on a network you don't control.
- **Network search** sends a standard EtherNet/IP "List Identity" broadcast on the local
  network and, if no device names itself as a pump, assumes the first device that answers
  is the pump. Check the address before you connect on a shared network.
- **Firmware helper** only copies a file you choose onto a USB drive you choose. It does
  not download or verify firmware; get firmware from Masterflex only.
- **Local files**: settings (`pump_config.json`) and run logs (`Data/run_log*.csv`) are plain
  files on your computer. Run logs can contain your experiment notes and metadata, so treat
  them like lab notebook data. None of them are committed to this repository.

Things that count as security issues here: the app sending commands you didn't ask for,
writing outside its data and settings folders, or exposing anything to the network beyond
the pump connection and the discovery broadcast.
