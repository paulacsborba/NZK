# Ref_heating: Ref case + heating system (2021 data)

Copy of `Ref/` (electricity system untouched) plus district heating (DH), decentral heat and industrial steam for the 17 NZK nodes.
Everything is built with existing MacroEnergy asset types (no changes in `src/`). Regenerate with
`python3 Ref_heating/build_heating.py <inputs_dir>` from the repo root (inputs: heating v2 CSVs, `demand_heat.csv`, temperature by province).

## Nodes (system/nodes_YYYY.json, all 7 periods)
| Node | Commodity | Locations | Notes |
|---|---|---|---|
| `dh_<LOC>` | Steam | 11 DH nodes (SEL PUS TAE INC KWJ SJG GGI CNA CNB DJJ GNA) | DH heat demand (`system/demand_heat.csv`) |
| `steam_ind_<LOC>` | Steam | 12 nodes | industrial steam demand, flat |
| `heat_dec_<LOC>` | Heat | 17 | demand not served by DH (70% of city gas, assumption) |
| `msw_<LOC>` | Biomass (proxy for municipal waste, tonnes) | 11 DH nodes | price = gate fee, -42 USD/t (= -15 USD/MWh x 2.8 MWh/t) |
The old `heat_<LOC>` Steam nodes and `Demand_heat_*` use were removed from this case (they stay in `Ref/`). Heat demand nodes use `max_nsd=0.1`, `price_nsd=1000` like electricity. Gas = `natgas_source`, CO2 = `co2_sink_KR`, electricity = `elec_<LOC>` (existing nodes).

## Assets (assets/assets_YYYY/heat_*_YY.csv)
| File | MACRO type | Capacity basis | Notes |
|---|---|---|---|
| heat_chp_gas | ThermalSteam | MW steam | back-pressure point: elec/heat = 0.9, 0.447 MWh heat per MWh gas, `elec_cogen_rate` 0.403 |
| heat_chp_waste | ThermalSteam (fuel Biomass) | MW steam | WtE; elec/heat = 0.3; no must-run/min load |
| heat_dh_gas_boiler | ThermalSteam, cogen 0 | MW steam | eff 0.92 |
| heat_dh_eboiler, heat_dh_heatpump | ElectricSteam | MW steam | eff 0.99; COP 2.8 |
| heat_dh_tes | GasStorage (commodity Steam) | MW / MWh | UNTESTED path: pump transform with zero electricity use |
| heat_waste_heat | ElectricSteam | MW steam | INC direct (elec 0), SEL/GGI via HP COP 4.2; availability folded into max capacity |
| heat_ind_chp, heat_ind_steam_boiler | ThermalSteam | MW steam | back-pressure cb 0.6, eff total 0.88; boiler 0.90 |
| heat_dec_gas_boiler | ThermalHeating | MW heat | eff 0.93 |
| heat_dec_ashp | ElectricHeating | MW heat | constant seasonal COP per node (2.7-3.4, `system/ashp_scop_2021.csv`) from 2021 temperature and demand weighting |
| heat_dec_resistance | ElectricHeating | MW heat | eff 1 |
Conventions follow Ref: 2021 = calibration (`can_expand` FALSE, existing capacity set); later periods `existing_capacity` 0, `can_expand` TRUE. WACC 0.1. Gas price and emission factor (0.18104 t/MWh) come from the existing gas nodes/assets.

## Differences from the standalone heating model
- No CHP feasibility region: ThermalSteam gives a fixed heat/power ratio (no extraction/condensing flexibility, no min load).
- ASHP COP is a seasonal constant, not hourly.
- Waste is modelled as Biomass commodity (tonnes), only fossil CO2 counted (0.175 t/MWh = 0.49 t/t).
- Heat demand shape: Renewables.ninja Demand.ninja (MERRA-2 2021) scaled to 2021 annual totals; no DHW base load, so peak/mean ~6 and summer demand ~0. Same demand in all periods.
- Costs, lifetimes, boiler/TES/industrial capacities are assumptions (see `heating_inputs/NZK_heating_assumptions.pdf`).

## Check before the first Della run
1. Existing gas CHP (e.g. GGI 2.2 GW elec, from KDHC 2021 generation) may be already inside `NaturalGasPower_21` (GGI 11.7 GW). Possible double counting of electricity capacity.
2. `GasStorage` as thermal storage and `Biomass` / `Heat` commodities have never been loaded in this repo: run period 2021 only first (`PeriodLengths` / `system_data.json` with one case) with HiGHS (`run_HiGHS.jl`).
3. `run_NZK_della.slurm` still has the original account, e-mail and `REPO` path: edit before submitting.
