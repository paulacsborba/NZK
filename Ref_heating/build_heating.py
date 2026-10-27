#!/usr/bin/env python3
"""Builds Ref_heating/ from Ref/ + heating inputs. Run from repo root:  python3 Ref_heating/build_heating.py <inputs_dir>
inputs_dir must contain: heating_system.csv (v2 heating_real), demand_heat.csv, node_inputs_real.csv, temperature_by_province.csv"""
import sys, os, json, shutil, glob
import numpy as np, pandas as pd
ROOT=os.getcwd(); SRC=f"{ROOT}/Ref"; DST=f"{ROOT}/Ref_heating"; INP=sys.argv[1]
YEARS=[2021,2025,2030,2035,2040,2045,2050]
LOCS=["SEL","PUS","TAE","INC","KWJ","USN","SJG","GGI","GWN","CNA","CNB","DJJ","JNB","JNA","GNB","GNA","JEJ"]
GASCO2=0.18104            # tCO2/MWh fuel, same as NaturalGasPower in Ref
LHV_MSW=2.8               # MWh/t municipal waste (assumption)
WACC=0.1
os.makedirs(DST,exist_ok=True)
# ---- 1. copy Ref (no logs / backups)
for p in os.listdir(SRC):
    if p.startswith("slurm-") or p.endswith(".bak") or p in("make_ref_charts.py",): continue
    s=f"{SRC}/{p}"; d=f"{DST}/{p}"
    if os.path.isdir(s):
        if os.path.exists(d): shutil.rmtree(d)
        shutil.copytree(s,d)
    else: shutil.copy2(s,d)
# ---- 2. inputs
old=pd.read_csv(f"{INP}/heating_system.csv",keep_default_na=False)
dem=pd.read_csv(f"{INP}/demand_heat.csv")
ni=pd.read_csv(f"{INP}/node_inputs_real.csv")
T=pd.read_csv(f"{INP}/temperature_by_province.csv")
dem.insert(0,"Time_Index",np.arange(1,len(dem)+1)); dem=dem.drop(columns=["hour"],errors="ignore")
dem.to_csv(f"{DST}/system/demand_heat.csv",index=False)
DH=[l for l in LOCS if f"{l}_heat_dh" in dem]; IND=[l for l in LOCS if f"{l}_steam_ind" in dem]
def old_val(typ,loc,col):
    r=old[(old.Type==typ)&(old.location==loc)]; return float(r.iloc[0][col]) if len(r) and r.iloc[0][col]!="" else 0.0
EX="edges--edge--existing_capacity"; MX="edges--edge--max_capacity"
pk_dh={l:dem[f"{l}_heat_dh"].max() for l in DH}
# seasonal COP of ASHP from real 2021 temperature (UTC->KST shift), weighted by decentral demand
def cop(t): return np.clip(3.4+0.07*(t-7),1.8,4.6)
SCOP={}
for l in LOCS:
    t=np.roll(T[f"{l}_t2m"].values,9); d=dem[f"{l}_heat_dec"].values
    SCOP[l]=round(d.sum()/(d/cop(t)).sum(),3)
# ---- 3. asset rows
def edge(prefix,**kw): return {f"edges--{prefix}--{k}":v for k,v in kw.items()}
def base_cap(prefix,end,life,inv,fom,vom,ex,mx,expand,retire):
    return edge(prefix,commodity="Steam" if end.startswith(("dh_","steam_ind_")) else "Heat",unidirectional="TRUE",has_capacity="TRUE",
        can_expand=expand,can_retire=retire,lifetime=life,capital_recovery_period=life,wacc=WACC,
        investment_cost=inv,fixed_om_cost=fom,variable_om_cost=vom,existing_capacity=ex,max_capacity=mx,end_vertex=end,
        **{"constraints--CapacityConstraint":"TRUE","constraints--MaxCapacityConstraint":"TRUE","constraints--RampingLimitConstraint":"FALSE"})
def thermal_steam(id,loc,node,fuel,fuel_node,fcons,erate,ecog,life,inv,fom,vom,ex,mx,y):
    r=dict(Type="ThermalSteam",id=id,location=loc)
    r.update({"transforms--timedata":"Steam","transforms--constraints--BalanceConstraint":"TRUE","transforms--fuel_consumption":round(fcons,5),
              "transforms--emission_rate":erate,"transforms--elec_cogen_rate":round(ecog,5)})
    r.update(base_cap("steam_edge",node,life,inv,fom,vom,round(ex,1) if y==2021 else 0,round(mx,1),"FALSE" if y==2021 else "TRUE","TRUE" if (ex>0 or y>2021) else "FALSE"))
    r.update(edge("fuel_edge",commodity=fuel,unidirectional="TRUE",has_capacity="FALSE",start_vertex=fuel_node))
    r.update(edge("elec_edge",commodity="Electricity",unidirectional="TRUE",has_capacity="FALSE",end_vertex=f"elec_{loc}"))
    r.update(edge("co2_edge",commodity="CO2",unidirectional="TRUE",has_capacity="FALSE",end_vertex="co2_sink_KR"))
    return r
def electric(Type,id,loc,node,econs,life,inv,fom,vom,ex,mx,y):
    key="steam_edge" if Type=="ElectricSteam" else "heat_edge"
    r=dict(Type=Type,id=id,location=loc); r.update({"transforms--timedata":"Steam" if Type=="ElectricSteam" else "Heat","transforms--constraints--BalanceConstraint":"TRUE","transforms--elec_consumption":round(econs,5)})
    r.update(base_cap(key,node,life,inv,fom,vom,round(ex,1) if y==2021 else 0,round(mx,1),"FALSE" if y==2021 else "TRUE","TRUE" if (ex>0 or y>2021) else "FALSE"))
    r.update(edge("elec_edge",commodity="Electricity",unidirectional="TRUE",has_capacity="FALSE",start_vertex=f"elec_{loc}"))
    return r
def thermal_heat(id,loc,node,fcons,life,inv,fom,vom,ex,mx,y):
    r=dict(Type="ThermalHeating",id=id,location=loc); r.update({"transforms--timedata":"Heat","transforms--constraints--BalanceConstraint":"TRUE","transforms--fuel_consumption":round(fcons,5),"transforms--emission_rate":GASCO2})
    r.update(base_cap("heat_edge",node,life,inv,fom,vom,round(ex,1) if y==2021 else 0,round(mx,1),"FALSE" if y==2021 else "TRUE","TRUE" if (ex>0 or y>2021) else "FALSE"))
    r.update(edge("fuel_edge",commodity="NaturalGas",unidirectional="TRUE",has_capacity="FALSE",start_vertex="natgas_source"))
    r.update(edge("co2_edge",commodity="CO2",unidirectional="TRUE",has_capacity="FALSE",end_vertex="co2_sink_KR"))
    return r
def tes(loc,y):
    p=old_val("ThermalStorage",loc,"edges--edge--existing_capacity"); pm=old_val("ThermalStorage",loc,"edges--edge--max_capacity")
    e=old_val("ThermalStorage",loc,"storage--existing_capacity"); em=old_val("ThermalStorage",loc,"storage--max_capacity")
    r=dict(Type="GasStorage",id=f"{loc}_dh_tes",location=loc)
    ex21=(y==2021)
    r.update({"transforms--timedata":"Steam","transforms--constraints--BalanceConstraint":"TRUE","transforms--charge_electricity_consumption":0.0,"transforms--discharge_electricity_consumption":0.0,
      "storage--commodity":"Steam","storage--can_expand":"FALSE" if ex21 else "TRUE","storage--can_retire":"TRUE","storage--lifetime":30,
      "storage--constraints--BalanceConstraint":"TRUE","storage--constraints--StorageCapacityConstraint":"TRUE","storage--constraints--StorageMinDurationConstraint":"TRUE","storage--constraints--StorageMaxDurationConstraint":"TRUE",
      "storage--existing_capacity":round(e,1) if ex21 else 0,"storage--max_capacity":round(em,1),"storage--investment_cost":3500,"storage--fixed_om_cost":35,"storage--min_duration":2,"storage--max_duration":24,"storage--loss_fraction":0.003})
    for k,cost in(("charge_edge",(0,0,0)),("discharge_edge",(15000,300,0))):
        r.update(edge(k,commodity="Steam",unidirectional="TRUE",has_capacity="TRUE",can_expand="FALSE" if ex21 else "TRUE",can_retire="TRUE",lifetime=30,capital_recovery_period=30,wacc=WACC,
            investment_cost=cost[0],fixed_om_cost=cost[1],variable_om_cost=cost[2],existing_capacity=round(p,1) if ex21 else 0,efficiency=0.98,**{"constraints--CapacityConstraint":"TRUE"}))
    r.update(edge("external_charge_edge",commodity="Steam",unidirectional="TRUE",has_capacity="FALSE",start_vertex=f"dh_{loc}"))
    r.update(edge("external_discharge_edge",commodity="Steam",unidirectional="TRUE",has_capacity="FALSE",end_vertex=f"dh_{loc}"))
    r.update(edge("charge_elec_edge",commodity="Electricity",unidirectional="TRUE",has_capacity="FALSE",start_vertex=f"elec_{loc}"))
    r.update(edge("discharge_elec_edge",commodity="Electricity",unidirectional="TRUE",has_capacity="FALSE",start_vertex=f"elec_{loc}"))
    return r
# BP-point yields
Q_G=0.85/(1+0.9); P_G=0.9*Q_G                     # per MWh gas fuel
Q_W=0.80/(1+0.30); P_W=0.30*Q_W                   # per MWh waste (LHV)
Q_I=0.88/(1+0.6); P_I=0.6*Q_I
files={}
def add(name,row): files.setdefault(name,[]).append(row)
for y in YEARS:
    files.clear(); s=str(y)[2:]
    for l in DH:
        pk=pk_dh[l]; nd=f"dh_{l}"
        exg=old_val("CHP_gas",l,EX)/0.9            # MW_elec -> MW_steam at BP (cb=0.9)
        add("chp_gas",thermal_steam(f"{l}_chp_gas",l,nd,"NaturalGas","natgas_source",1/Q_G,GASCO2,P_G,30,1.2e6*0.9,36000*0.9,3.5*0.9,exg,max(pk,1.2*exg),y))
        w=old_val("CHP_waste",l,EX); wmx=old_val("CHP_waste",l,MX)
        add("chp_waste",thermal_steam(f"{l}_wte_chp",l,nd,"Biomass",f"msw_{l}",1/(Q_W*LHV_MSW),round(0.35*0.5*LHV_MSW,4),P_W*LHV_MSW,30,3.5e6/Q_W,120000/Q_W,8/Q_W,w*Q_W,wmx*Q_W,y))
        add("dh_gas_boiler",thermal_steam(f"{l}_dh_gas_boiler",l,nd,"NaturalGas","natgas_source",1/0.92,GASCO2,0.0,25,90000,1800,1,old_val("HeatOnlyBoiler",l,EX),old_val("HeatOnlyBoiler",l,MX),y))
        add("dh_eboiler",electric("ElectricSteam",f"{l}_dh_eboiler",l,nd,1/0.99,20,70000,1000,0.5,0,old_val("ElectricBoiler",l,MX),y))
        add("dh_heatpump",electric("ElectricSteam",f"{l}_dh_hp",l,nd,1/2.8,20,900000,8000,2,0,old_val("LargeHeatPump",l,MX),y))
        add("dh_tes",tes(l,y))
    for l,tp,ec,inv,fom,vom,mx in (("INC","direct",0.0,250000,3000,3,120*0.85),("SEL","hp",1/4.2,600000,6000,2,80*0.9),("GGI","hp",1/4.2,600000,6000,2,250*0.9)):
        if l in DH: add("waste_heat",electric("ElectricSteam",f"{l}_wasteheat_{tp}",l,f"dh_{l}",ec,30 if tp=="direct" else 20,inv,fom,vom,0,mx,y))
    for l in IND:
        nd=f"steam_ind_{l}"; pks=dem[f"{l}_steam_ind"].max()
        add("ind_chp",thermal_steam(f"{l}_ind_chp_gas",l,nd,"NaturalGas","natgas_source",1/Q_I,GASCO2,P_I,30,1.0e6*0.6,30000*0.6,3*0.6,old_val("IndustrialCHP",l,EX)/0.6,pks,y))
        add("ind_steam_boiler",thermal_steam(f"{l}_steam_boiler_gas",l,nd,"NaturalGas","natgas_source",1/0.90,GASCO2,0.0,25,80000,1500,1,old_val("SteamBoiler",l,EX),old_val("SteamBoiler",l,MX),y))
    for l in LOCS:
        nd=f"heat_dec_{l}"
        add("dec_gas_boiler",thermal_heat(f"{l}_dec_gas_boiler",l,nd,1/0.93,20,150000,3000,1,old_val("DecentralGasBoiler",l,EX),old_val("DecentralGasBoiler",l,MX),y))
        add("dec_ashp",electric("ElectricHeating",f"{l}_dec_ashp",l,nd,1/SCOP[l],15,1.0e6,20000,0,old_val("DecentralASHP",l,EX),old_val("DecentralASHP",l,MX),y))
        add("dec_resistance",electric("ElectricHeating",f"{l}_dec_resistance",l,nd,1.0,20,100000,1000,0,old_val("DecentralElectricHeater",l,EX),old_val("DecentralElectricHeater",l,MX),y))
    d=f"{DST}/assets/assets_{y}"
    for name,rows in files.items():
        pd.DataFrame(rows).to_csv(f"{d}/heat_{name}_{s}.csv",index=False)
# ---- 4. commodities / time_data
cm=json.load(open(f"{DST}/system/commodities.json"))
for c in("Heat","Biomass"):
    if c not in cm["commodities"]: cm["commodities"].append(c)
json.dump(cm,open(f"{DST}/system/commodities.json","w"),indent=4)
td=json.load(open(f"{DST}/system/time_data.json"))
for c in("Heat","Biomass"):
    td["HoursPerSubperiod"][c]=8760; td["HoursPerTimeStep"][c]=1
json.dump(td,open(f"{DST}/system/time_data.json","w"),indent=2)
# ---- 5. nodes
cons={"BalanceConstraint":True,"MaxNonServedDemandConstraint":True,"MaxNonServedDemandPerSegmentConstraint":True}
def dnode(typ,ids,hdrs):
    return {"type":typ,"global_data":{"time_interval":typ,"max_nsd":[0.1],"price_nsd":[1000],"constraints":cons},
            "instance_data":[{"id":i,"demand":{"timeseries":{"path":"system/demand_heat.csv","header":h}}} for i,h in zip(ids,hdrs)]}
wmax={l:max(3*old_val("CHP_waste",l,EX),50)/LHV_MSW for l in DH}
for y in YEARS:
    p=f"{DST}/system/nodes_{y}.json"; n=json.load(open(p))
    n["nodes"]=[x for x in n["nodes"] if not (x["type"]=="Steam" and x["instance_data"][0]["id"].startswith("heat_"))]
    n["nodes"]+= [dnode("Steam",[f"dh_{l}" for l in DH],[f"{l}_heat_dh" for l in DH]),
                  dnode("Steam",[f"steam_ind_{l}" for l in IND],[f"{l}_steam_ind" for l in IND]),
                  dnode("Heat",[f"heat_dec_{l}" for l in LOCS],[f"{l}_heat_dec" for l in LOCS]),
                  {"type":"Biomass","global_data":{"time_interval":"Biomass","constraints":{"BalanceConstraint":True}},
                   "instance_data":[{"id":f"msw_{l}","supply":{"segment1":{"price":[round(-15*LHV_MSW,2)],"min":[0.0],"max":[round(wmax[l],2)]}}} for l in DH]}]
    json.dump(n,open(p,"w"),indent=2)
# ---- 6. slurm + notes
s=open(f"{DST}/run_NZK_della.slurm").read().replace('CASE="$REPO/Ref"','CASE="$REPO/Ref_heating"').replace("nzk_ref","nzk_ref_heating")
open(f"{DST}/run_NZK_della.slurm","w").write(s)
pd.DataFrame({"node":LOCS,"ASHP_SCOP_2021":[SCOP[l] for l in LOCS]}).to_csv(f"{DST}/system/ashp_scop_2021.csv",index=False)
print("DH",DH); print("IND",IND); print(SCOP)
