# Slot Ledger: shared-depot scheduling

FICTIONAL teaching source — original Session 2 EV dossier; no real paper or measured hardware result.
Source: EV-S02
Date: 2026-10-02
Author: fictional Depot Methods Desk
Provenance: course issue #181, original public dossier v1
Reporting relationship: method note
Experiments: none
Families: none
Supersedes: none

## EV-S02:P01

Slot Ledger (slot-ledger) is a mixed-integer daily-cost model. Binary truck-leg assignments and cancellations, deadhead links and charge-slot choices enforce coverage and the truck day. For each depot, charger type and slot, the sum of simultaneous charging trucks cannot exceed the available charger count. It therefore represents limited shared capacity, including separate slow and fast pools.

## EV-S02:P02

Slot Ledger uses the deterministic 30-minute, whole-wait, lossless constant-power assumptions in EV-S01:P02. It enforces truck and charger power bounds, maintenance exclusion, intermediate battery bounds and final home state of charge at least the initial level. It may optimise cost, but a time-limited feasible solution is not an optimality certificate.
