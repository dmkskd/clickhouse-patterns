# Refreshable MV producing state transitions with hysteresis

Profiles: `single`, `kafka`. Driver: `ch`.

Extends [kafka-produce-refreshable-mv](../kafka-produce-refreshable-mv/) from a level-only
alert to the full firing/resolved model that real alerting systems use, and adds
hysteresis so it does not flap. ClickHouse does all of it, no external stream
processor.

## Two topics, two models

Prometheus and Alertmanager use the same split, keeping the level state
internally, emit edge notifications at the boundary.

- Topic `status` (level stream): the current status of every service, produced
  every tick. This is the analog of a Prometheus rule evaluating each interval.
- Topic `alerts` (edge stream): `FIRING` / `RESOLVED`, produced only when a
  service's status changes. This is the analog of an Alertmanager notification
  with `send_resolved: true`.

See [Prometheus alerting overview](https://prometheus.io/docs/alerting/latest/overview/)
and the [Grafana webhook notifier](https://grafana.com/docs/grafana/latest/alerting/configure-notifications/manage-contact-points/integrations/webhook-notifier/)
(firing/resolved payloads).

```
topic "latency" -> latency_in -> latency_raw
                                     |
              every 5s: mv_status evaluates p90 + hysteresis
                                     |
                              status_history  (internal state)
                                 /        \
             mv_emit_status (all)      mv_emit_alerts (transitions)
                    |                          |
              topic "status"             topic "alerts"
              (firing/ok/tick)           (FIRING / RESOLVED)
```

## Hysteresis

With a single threshold, a service hovering near 1000ms produces a storm of
firing and resolved pairs. Hysteresis uses two thresholds, a trigger and a stricter
recovery, so the state only flips after a clear move:

- fire when `p90 > 1000`
- resolve only when `p90 < 800`
- in the 800..1000 band, keep the previous status

This is the same idea as Datadog recovery thresholds and Zabbix recovery
expressions, and the thermostat that switches on and off at different
temperatures. Prometheus does the time-based cousin with `for` and
`keep_firing_for`.

- [Datadog: recovery thresholds](https://www.datadoghq.com/blog/introducing-recovery-thresholds/) ([docs](https://docs.datadoghq.com/monitors/guide/recovery-thresholds/))
- [Zabbix: no more flapping](https://blog.zabbix.com/no-more-flapping-define-triggers-the-smart-way/1488/)
- [NinjaOne: tuning overlapping thresholds](https://www.ninjaone.com/blog/how-to-tune-overlapping-monitoring-thresholds-in-rmm/)
- [Prometheus: for / keep_firing_for](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)

## The state table

Hysteresis has memory, so the status inside the band depends on the previous
status.
So `mv_status` reads the last status from `status_history` and writes the new one
back (APPEND). `status_history` is internal bookkeeping, not the level topic; the
level topic is produced from it by `mv_emit_status`.

## Test

```bash
just test kafka-produce-refreshable-mv-transitions
```

`load.py` drives a full sequence: `checkout` goes high (p90 > 1000), then floods
with low latencies (p90 < 800) to recover. `health` stays healthy throughout.

Edge topic result:

```
service   type
checkout  FIRING
checkout  RESOLVED
```

The level topic check asserts `checkout` carried both `firing` and `ok` statuses,
and `health` produced no alerts.

## Notes

- The 5s refresh is the alert-latency floor, and edges are detected one tick
  after the level changes.
- Transition detection here compares consecutive statuses via the
  `is_transition` flag computed at write time; `lagInFrame` over `status_history`
  is an equivalent way to derive it after the fact.
- A real deployment would alert on closed or sliding windows and add a `for`-style
  sustain (breach must hold N ticks) on top of the two-threshold hysteresis.
