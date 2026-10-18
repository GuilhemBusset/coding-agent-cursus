# P01 - EV Middle-Mile Linehaul Scheduling and Charging

A large e-commerce network must execute a scaled one-day schedule of 180 middle-mile linehaul legs between cross-docks and sort depots, using an electric fleet based across 8 depots.

The planner must decide:
1. Which vehicle covers each linehaul leg.
2. How vehicles sequence legs over the day.
3. When and where each vehicle charges.

## Operational rules
- Every scheduled leg must be covered or explicitly canceled (with large penalty).
- A vehicle can only start a leg if it can physically reach the origin depot in time.
- Battery state-of-charge (SoC) must remain between vehicle-specific minimum and maximum bounds.
- Charging requires an available charger at the assigned depot and respects charger power limits.
- Electricity prices vary by time block; charging in peak windows is expensive.
- Some vehicles have mandatory maintenance windows and cannot operate then.

## Objective
Minimize total daily operating cost:
- cancellation penalties,
- electricity purchase cost,
- battery degradation proxy cost (per kWh charged),
- deadhead travel cost.

## Data description
- `trips.csv`: Scheduled linehaul legs to cover (`trip_id`, origin/destination, start/end time, service distance, energy need, cancellation penalty).
- `vehicles.csv`: Fleet characteristics and operating limits (`vehicle_id`, home depot, battery size, SoC bounds, charging limit, optional maintenance window).
- `depots.csv`: Charging infrastructure available at depots (number of slow/fast chargers and their power ratings).
- `deadhead_minutes.csv`: Repositioning matrix between depots (deadhead travel time and associated energy consumption).
- `tariff_blocks.csv`: Time-of-use electricity tariff blocks (`start_time`-`end_time`) with price per kWh.

## Deliverables
Return:
- leg-to-vehicle assignment,
- charging schedule by vehicle and time block,
- canceled legs (if any),
- objective breakdown and feasibility checks (SoC and charger capacity).
