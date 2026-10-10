# P01 · EV linehaul scheduling and charging

An e-commerce network runs a one-day schedule of 40 middle-mile linehaul legs between eight
cross-docks and sort depots (`D_A` to `D_H`). It has a fleet of 10 electric trucks, each based
at a home depot. Decide:

1. which truck covers each leg, or which legs to cancel;
2. how each truck sequences its legs over the day;
3. when, where and on which charger type each truck charges.

The goal is the cheapest day that respects the rules below. The data is in [`data/`](data/),
and the checker (`p01_checker.py`) applies exactly these rules.

## Time

Times are `HH:MM` from `00:00` to `24:00`, and every interval is half-open: `[start, end)`.
The day is cut into 48 fixed **charging slots** of 30 minutes, starting at `00:00`, `00:30`,
..., `23:30`. Tariff blocks start and end on slot boundaries.

## Rules

1. **Coverage** (`coverage`, `integrality`). Each leg is covered by exactly one truck, or it is
   cancelled and pays its `cancel_penalty`. Covering and cancelling are yes/no decisions: every
   assignment and cancellation is 0 or 1, never a fraction.
2. **A truck's day** (`sequence`). A truck starts at its `home_depot` at `00:00` holding
   `initial_soc_kwh`, and drives the legs it covers in order of start time.
   - At `00:00` it deadheads (drives empty) from home to the origin of its first leg.
   - As soon as a leg ends, it deadheads to the origin of its next leg, or home after its last
     leg. It cannot wait somewhere else first.
   - Each deadhead takes the `minutes` and uses the `energy_kwh` in `deadhead_minutes.csv`. A
     deadhead from a depot to itself takes 0 minutes and 0 kWh.
   - Each deadhead must arrive no later than the next leg's `start_time`, and the final
     deadhead must reach home by `24:00`.
   - A truck that covers no leg stays at home all day.
3. **Waiting.** Between arriving at a depot and the start of the next leg, a truck waits at that
   depot. After its final return it waits at home until `24:00`. A truck is either driving (a
   leg or a deadhead) or waiting.
4. **Charging** (`charging-window`, `charging-power`). A truck can charge in a slot only if the
   whole slot lies inside one of its waits (`charging-window`). It then charges at that wait's
   depot, on one charger, either `slow` or `fast`, for that slot, and at most once per slot. The
   energy it receives in the slot is never negative and is at most (`charging-power`)
   `min(max_charge_kw, charger kW) x 0.5 h`, where the charger kW is the depot's `slow_kw` or
   `fast_kw`. Charging has no losses: the kWh charged are the kWh added to the battery.
5. **Charger capacity** (`charger-capacity`). At each depot, in each slot, the number of trucks
   charging on slow chargers is at most `chargers_slow`, and the number charging on fast
   chargers is at most `chargers_fast`.
6. **Maintenance** (`maintenance`). During `[maintenance_start, maintenance_end)` a truck does
   not drive and does not charge. No leg or deadhead may overlap the window, and no charging
   slot may overlap it. Waiting through it is fine.
7. **State of charge (SoC)** (`soc`). A leg or deadhead uses its `energy_kwh` over its
   duration, and a charge adds its kWh during its slot. A truck never drives and charges at the
   same time, so the SoC rises only during charges and falls only during drives. It must stay
   between `min_soc_kwh` and `max_soc_kwh` throughout the day, which means after every drive
   and after every charge. The truck must end the day at home with at least its `initial_soc_kwh`.

## Objective

Minimise the total daily cost:

- the `cancel_penalty` of every cancelled leg;
- for every kWh charged, the `price_per_kwh` of the tariff block that contains the slot, plus
  `degradation_cost_per_kwh`;
- for every deadhead minute, `deadhead_cost_per_minute`.

## What the checker certifies

The checker replays a solution file (its format is in [`README.md`](README.md)) against these
rules, with no solver. Each failure line starts with the name of the contract it breaks. The
rule contracts are named in parentheses above. The others are:

- `data`: the CSVs in `data/` are the pinned instance, unedited;
- `format`: the solution file is valid JSON in the documented format;
- `status`: the reported status is `optimal` or `feasible`;
- `objective`: the reported objective equals the cost recomputed from the decisions;
- `optimality`: a feasible plan costs no more than the known optimum.

## Data

| File | Columns |
| --- | --- |
| `trips.csv` | `trip_id`; `origin_depot`, `destination_depot`; `start_time`, `end_time`; `service_km` (information only); `energy_kwh` used by the leg; `cancel_penalty` |
| `vehicles.csv` | `vehicle_id`; `home_depot`; `battery_kwh` (information only: the usable range is `min_soc_kwh` to `max_soc_kwh`); `min_soc_kwh`, `initial_soc_kwh`, `max_soc_kwh`; `max_charge_kw`, the truck's own charging power limit; `maintenance_start`, `maintenance_end` (both empty when there is no window) |
| `depots.csv` | `depot`; `chargers_slow`, `chargers_fast` (counts); `slow_kw`, `fast_kw` (power of one charger) |
| `deadhead_minutes.csv` | `from_depot`, `to_depot`, `minutes`, `energy_kwh`, for every ordered pair of depots |
| `tariff_blocks.csv` | `block_id`; `start_time`, `end_time` (half-open, covering `00:00` to `24:00`); `price_per_kwh` |
| `parameters.csv` | `parameter`, `value`, `unit`: `deadhead_cost_per_minute` and `degradation_cost_per_kwh` |

The instance is a revised subset of P01 from the 2025 workshop pack. The rules above are the
precise version of that pack's statement, and they are what the checker certifies.
