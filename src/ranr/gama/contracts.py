"""Schemas and independent checks of GAMA records; no simulation or prediction."""
from __future__ import annotations
import math
import json

from pathlib import Path
import hashlib
from ..paths import ROOT

TERMINAL = frozenset({"completed", "no_feasible_station", "voluntary_deferred", "declined", "abandoned", "deadline_missed", "stranded", "unresolved"})
INTENT_TERMINAL = frozenset({"completed", "failed", "unresolved"})
OBJECTIVE_VERSION = "intent-service-5"
OBSERVATION_VERSION = "station-observation-5"
OBJECTIVE_SPEC = json.loads((ROOT / "configs/gama/objective.json").read_text())
OBJECTIVE_CONFIG_HASH = hashlib.sha256(json.dumps(OBJECTIVE_SPEC, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
TIME_FIELDS = ("travel_min", "waiting_min", "charging_min", "deferred_min", "retry_delay_min", "other_elapsed_min")


def finite_tree(value):
    if isinstance(value, (bool, str)) or value is None:
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(finite_tree(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return all(finite_tree(v) for v in value)
    return False


def validate_objective_identity(record):
    if record.get("objective_version", record.get("version")) != OBJECTIVE_VERSION or record.get("objective_config_hash") != OBJECTIVE_CONFIG_HASH:
        raise ValueError("Incompatible objective version/configuration hash; historical data cannot train this objective")
    return True


def _unique(rows, field):
    if any(field not in r for r in rows):
        raise ValueError(f"Missing {field}")
    result = {r[field]: r for r in rows}
    if len(result) != len(rows):
        raise ValueError(f"Duplicate {field}")
    return result


def validate_charging_ledger(intents, attempts, outcomes, resolutions):
    needs = _unique(intents, "intent_id")
    requests = _unique(attempts, "request_id")
    results = _unique(outcomes, "request_id")
    final = _unique(resolutions, "intent_id")
    if needs.keys() != final.keys() or requests.keys() != results.keys():
        raise ValueError("Missing intent or request outcomes")
    _unique(attempts, "attempt_id")
    _unique(attempts, "key")
    time_tol = OBJECTIVE_SPEC["time_tol_min"]
    energy_tol = OBJECTIVE_SPEC["energy_abs_tol_kwh"]
    groups = {k: [] for k in needs}
    for attempt in attempts:
        identity = attempt["intent_id"]
        if identity not in needs or attempt["vehicle_id"] != needs[identity]["vehicle_id"]:
            raise ValueError("Orphan or mismatched request")
        if attempt["attempt_id"] != attempt["request_id"] or attempt.get("source") != "physical_energy" or attempt.get("passenger", False):
            raise ValueError("Invalid attempt identity or physical gate")
        if attempt["at"] < needs[identity]["at"] - time_tol or abs(attempt["deadline"] - needs[identity]["deadline"]) > time_tol:
            raise ValueError("Retry changed immutable intent deadline")
        result = results[attempt["request_id"]]
        if result["status"] not in TERMINAL or result["intent_id"] != identity or result["vehicle_id"] != attempt["vehicle_id"] or result["key"] != attempt["key"]:
            raise ValueError("Attempt outcome identity/status mismatch")
        if any(result.get(f,-1)<0 for f in ("travel_min","waiting_min","charging_min")) or abs(result["service_time_min"]-sum(result[f] for f in ("travel_min","waiting_min","charging_min")))>time_tol:
            raise ValueError("Invalid attempt duration accounting")
        if result["status"]=="completed" and result["requested_kwh"]-result["delivered_kwh"]>energy_tol:
            raise ValueError("Incomplete energy labeled completed")
        if not finite_tree(result) or result["finished_min"] < attempt["at"] - time_tol:
            raise ValueError("Invalid attempt timestamp")
        if abs(result['issued_min'] - attempt['at']) > time_tol:
            raise ValueError('Attempt outcome issuance time mismatch')
        if result["delivered_kwh"] < 0 or result["delivered_kwh"] > result["requested_kwh"] + energy_tol:
            raise ValueError("Invalid attempt energy")
        groups[identity].append(attempt)
    for identity, intent in needs.items():
        row = final[identity]
        if not finite_tree(intent) or not finite_tree(row) or intent["cause"] not in {"low_soc", "trip_energy", "shift_energy"}:
            raise ValueError("Invalid intent or physical need origin")
        if abs(intent["deadline"] - intent["at"] - 360.) > time_tol or abs(row["deadline"] - intent["deadline"]) > time_tol:
            raise ValueError("Invalid immutable intent deadline")
        if row["vehicle_id"] != intent["vehicle_id"] or row["status"] not in INTENT_TERMINAL or abs(row["issued_min"] - intent["at"]) > time_tol:
            raise ValueError("Intent outcome identity/status mismatch")
        if intent["cause"] == "low_soc" and intent["soc_at_need"] > intent["threshold"] + 1e-6:
            raise ValueError("Low-SOC intent above threshold")
        group = sorted(groups[identity], key=lambda x: x["attempt"])
        for field in ('target_soc', 'soc_at_need', 'threshold'):
            if abs(row[field] - intent[field]) > OBJECTIVE_SPEC['soc_tol_percent']:
                raise ValueError('Immutable intent field mismatch: ' + field)
        # Physical intent records carry these fields; older synthetic fixtures may not.
        for field in ('initial_required_kwh', 'battery_capacity_kwh', 'initial_battery_kwh'):
            if field in intent and abs(row[field] - intent[field]) > energy_tol:
                raise ValueError('Immutable intent energy mismatch: ' + field)
        children = [results[r['request_id']] for r in group]
        if any(child['finished_min'] > row['finished_min'] + time_tol for child in children):
            raise ValueError('Attempt finishes after intent')
        if any(results[a['request_id']]['finished_min'] > b['at'] + time_tol for a, b in zip(group, group[1:])):
            raise ValueError('Overlapping recommendation attempts')
        if abs(sum(child['delivered_kwh'] for child in children) - row['delivered_kwh']) > energy_tol:
            raise ValueError('Attempt delivered energy differs from intent total')
        for field in ('travel_min', 'waiting_min', 'charging_min'):
            if abs(sum(child[field] for child in children) - row[field]) > time_tol:
                raise ValueError('Attempt duration differs from intent total: ' + field)
        if row['status'] == 'completed' and (not children or children[-1]['status'] != 'completed'
                or abs(children[-1]['finished_min'] - row['finished_min']) > time_tol):
            raise ValueError('Intent completion differs from final attempt')
        if [r["attempt"] for r in group] != list(range(1, len(group)+1)) or intent["attempts"] != len(group):
            raise ValueError("Missing or repeated recommendation attempt")
        if any(b["at"] <= a["at"] for a,b in zip(group,group[1:])):
            raise ValueError("Retry has no elapsed time")
        if row["attempt_ids"] != [r["attempt_id"] for r in group]:
            raise ValueError("Intent attempt history mismatch")
        elapsed = row["finished_min"] - row["issued_min"]
        if elapsed < -time_tol or any(row[f] < 0 for f in TIME_FIELDS) or abs(sum(row[f] for f in TIME_FIELDS) - elapsed) > time_tol:
            raise ValueError("Invalid or overlapping time ledger")
        capacity=row["battery_capacity_kwh"]
        if capacity<=0 or abs(row["initial_battery_kwh"]-row["soc_at_need"]*capacity/100.)>energy_tol:
            raise ValueError("Initial battery energy/SOC mismatch")
        expected_initial=max(0.,row["target_soc"]*capacity/100.-row["initial_battery_kwh"])
        if abs(expected_initial-row["initial_required_kwh"])>energy_tol:
            raise ValueError("Initial charging demand was underreported")
        if min(row["grid_kwh"],row["charging_loss_kwh"])<0 or abs(row["final_soc"]*capacity/100.-row["final_battery_kwh"])>energy_tol:
            raise ValueError("Invalid grid losses or final SOC")
        required = row["initial_required_kwh"] + row["consumed_kwh"]
        if row["consumed_kwh"] < 0 or row["delivered_kwh"] < 0 or abs(required-row["requested_kwh"]) > energy_tol:
            raise ValueError("Intent energy duplicated or underreported")
        tolerance = energy_tol + OBJECTIVE_SPEC["energy_rel_tol"] * abs(row["final_battery_kwh"])
        if abs(row["final_battery_kwh"] - (row["initial_battery_kwh"]-row["consumed_kwh"]+row["delivered_kwh"])) > tolerance:
            raise ValueError("Intent energy conservation violated")
        if row["delivered_kwh"] > required + energy_tol or abs(row["grid_kwh"] - row["delivered_kwh"] - row["charging_loss_kwh"]) > energy_tol:
            raise ValueError("Invalid battery/grid energy accounting")
        complete = required-row["delivered_kwh"] <= energy_tol
        if row["energy_complete"] is not complete:
            raise ValueError("Energy completion flag inconsistent")
        completed = row["status"] == "completed"
        if completed and (not complete or abs(row["completion_time_min"]-elapsed)>time_tol or row["actual_completion_time"]!=row["finished_min"]):
            raise ValueError("Incomplete energy or invalid completion timestamp")
        if not completed and (row["actual_completion_time"] is not None or row["completion_time_min"] is not None):
            raise ValueError("Incomplete intent has fabricated completion time")
        on_time = completed and row["finished_min"] <= intent["deadline"]+time_tol
        if row["on_time"] is not on_time or row["right_censored"] is not (row["status"]=="unresolved"):
            raise ValueError("Intent timing/censoring flags inconsistent")
        if completed and not on_time and not row["deadline_missed"]:
            raise ValueError("Late completion hid deadline violation")
        if row["finished_min"] < intent["deadline"]-time_tol and row["deadline_missed"]:
            raise ValueError("Energy shortfall mislabeled deadline violation")
        if not complete and row["finished_min"]>=intent["deadline"]-time_tol and not row["deadline_missed"]:
            raise ValueError("Unresolved overdue intent hid deadline violation")
    return True


def planned_ev_days(initial_fleet, traffic_plan, start, end):
    if end <= start:
        raise ValueError("Invalid measurement window")
    minutes = sum(end-start for r in initial_fleet if r["kind"] != "car")
    minutes += sum(max(0., min(float(r["depart"]),end)-max(float(r["at"]),start)) for r in traffic_plan if r["kind"]!="car")
    result = minutes/1440.
    if not math.isfinite(result) or result<=0:
        raise ValueError("Missing or zero planned EV-day exposure")
    return result


def validate_charging_files(folder):
    load = lambda name: json.loads((folder/name).read_text())
    validate_charging_ledger(*(load(n) for n in ("charging_intents.json","request_attempts.json","outcomes.json","intent_outcomes.json")))
    metrics = load("metrics.json")
    validate_objective_identity(metrics)
    config = load("configuration.json")
    start,end = config["warmup_minutes"], config["warmup_minutes"]+config["measure_minutes"]
    exposure = planned_ev_days(load("initial_fleet.json"),load("traffic_plan.json"),start,end)
    if not math.isclose(exposure,metrics["planned_ev_days"],rel_tol=1e-8,abs_tol=1e-7):
        raise ValueError("Planned exposure was changed by realized trajectories")
    if load("completion.json")["finished_min"]+1e-7 < end+360:
        raise ValueError("Incomplete required Drain")
    intents = load("charging_intents.json"); outcomes = load("intent_outcomes.json")
    needs=_unique(load("charging_needs.json"),"intent_id")
    if set(needs)!={r["intent_id"] for r in intents}:
        raise ValueError("Eligible physical charging need missing an intent")
    for intent in intents:
        need=needs[intent["intent_id"]]
        if need["vehicle_id"]!=intent["vehicle_id"] or abs(need["at"]-intent["at"])>1e-7:
            raise ValueError("Physical need/intent mismatch")
    intervals = load("intent_time_intervals.json")
    by_intent = {r["intent_id"]: [] for r in intents}
    for row in intervals:
        if row["intent_id"] not in by_intent or row["state"]+"_min" not in TIME_FIELDS or row["end"]<=row["begin"]:
            raise ValueError("Invalid physical state interval")
        by_intent[row["intent_id"]].append(row)
    for row in outcomes:
        cursor = row["issued_min"]; totals = dict.fromkeys(TIME_FIELDS,0.)
        for interval in sorted(by_intent[row["intent_id"]],key=lambda x:x["begin"]):
            if abs(interval["begin"]-cursor)>1e-7:
                raise ValueError("Missing or overlapping state intervals")
            totals[interval["state"]+"_min"]+=interval["end"]-interval["begin"];cursor=interval["end"]
        if abs(cursor-row["finished_min"])>1e-7 or any(abs(totals[k]-row[k])>1e-7 for k in TIME_FIELDS):
            raise ValueError("Active-session time accounting missing")
    activities = load("activity_plan.json"); mobility = load("mobility_outcomes.json")
    plans = _unique(activities,"activity_id"); observed=_unique(mobility,"activity_id")
    if plans.keys()!=observed.keys():
        raise ValueError("Missing planned mobility obligations")
    for key,plan in plans.items():
        r=observed[key]
        if any(plan[k]!=r[k] for k in plan) or r["status"] not in {"completed","missed","unresolved"}:
            raise ValueError("Planned mobility ledger changed")
        if r["status"]=="completed" and (r["actual_start"] is None or r["actual_completion"] is None or r["actual_completion"]<r["actual_start"]):
            raise ValueError("Invalid mobility completion")
    cohort=[r for r in outcomes if start<=r["issued_min"]<end]
    unmet=sum(0. if r["energy_complete"] else max(0.,r["requested_kwh"]-r["delivered_kwh"]) for r in cohort)
    missed=sum(not r["on_time"] for r in cohort)
    unserved=sum(start<=r["at"]<end and r["status"]!="completed" for r in mobility)
    stranded=load("stranded_ev_ids.json")
    _unique([{"id":v} for v in stranded],"id")
    for key,value in (("unmet_kwh",unmet),("not_on_time_count",missed),("mobility_unserved_count",unserved),("stranded_vehicle_count",len(stranded))):
        if abs(metrics[key]-value)>1e-6:
            raise ValueError("Fitness count differs from complete ledgers: "+key)
    expected=[len(stranded)/exposure,unserved/exposure,missed/exposure,unmet/exposure,metrics["operational_objective"]]
    if any(abs(a-b)>1e-7 for a,b in zip(expected,metrics["fitness_vector"])):
        raise ValueError("Fitness vector decomposition mismatch")
    return validate_fitness(metrics)


def validate_fitness(record):
    validate_objective_identity(record)
    vector=record.get("fitness_vector")
    if record.get("fitness_valid") is not True or not isinstance(vector,list) or len(vector)!=5 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>=0 for v in vector):
        raise ValueError("Invalid fitness: "+str(record.get("failure_reason","missing vector")))
    if record.get("operational_objective") is None or not math.isfinite(record["operational_objective"]) or record["operational_objective"]<0:
        raise ValueError("Invalid operational objective")
    if not math.isfinite(record.get("planned_ev_days",0)) or record.get("planned_ev_days",0)<=0:
        raise ValueError("Invalid exposure")
    expected=[record[k]/record["planned_ev_days"] for k in ("stranded_vehicle_count","mobility_unserved_count","not_on_time_count","unmet_kwh")]+[record["operational_objective"]]
    if any(not math.isfinite(x) or x<0 for x in expected) or any(abs(a-b)>1e-7 for a,b in zip(vector,expected)):
        raise ValueError("Fitness vector does not match registered counts")
    return True


def rank_fitness_vectors(vectors):
    if not vectors or any(len(v)!=5 or any(not math.isfinite(x) or x<0 for x in v) for v in vectors):
        raise ValueError("Invalid lexicographic vectors")
    unique=sorted(set(tuple(v) for v in vectors))
    ranks={v:float(i) for i,v in enumerate(unique)}
    return [ranks[tuple(v)] for v in vectors]


def aggregate_fitness(rows, expected_design):
    expected=set(expected_design)
    identities=[(r["case"],r["seed"]) for r in rows]
    if len(identities)!=len(set(identities)) or set(identities)!=expected:
        raise ValueError("Unexpected candidate/scenario/seed results")
    for r in rows: validate_fitness(r)
    exposure=sum(r["planned_ev_days"] for r in rows)
    return [sum(r[k] for r in rows)/exposure for k in ("stranded_vehicle_count","mobility_unserved_count","not_on_time_count","unmet_kwh")]+[sum(r["operational_objective"] for r in rows)/len(rows)]


def validate_paired_results(groups):
    reference=None
    for rows in groups:
        identity={(r["case"],r["seed"]):(r["exogenous_hash"],r["planned_ev_days"]) for r in rows}
        if len(identity)!=len(rows) or (reference is not None and identity!=reference):
            raise ValueError("Mismatched exogenous schedule hash or planned exposure")
        reference=identity
    return True


def validate_behavior_config(environment):
    for kind in ("private", "taxi"):
        for values, probabilities in (
            (environment["soc_threshold_intervals"], environment[kind + "_threshold_probabilities"]),
            (environment[kind + "_target_soc_values"], environment[kind + "_target_probabilities"]),
        ):
            if len(values) != len(probabilities) or any(not math.isfinite(p) or p < 0 for p in probabilities) or not math.isclose(sum(probabilities), 1.0):
                raise ValueError("Invalid personal SOC probability distribution")
        if any(not environment["safety_soc_reserve"] < low < high <= 70 for low, high in environment["soc_threshold_intervals"]):
            raise ValueError("Invalid individual SOC threshold interval")
        if any(not 70 <= target <= 100 for target in environment[kind + "_target_soc_values"]):
            raise ValueError("Invalid preferred charging target")
    if not 0 < environment["energy_retry_minutes"] <= environment["energy_retry_max_minutes"]:
        raise ValueError("Invalid bounded retry configuration")
    return True


def rescore_components(components):
    """Check the native operational decomposition, never replace native fitness."""
    validate_objective_identity(components)
    if not components.get("fitness_valid") or not finite_tree(components):
        raise ValueError("Invalid objective decomposition")
    return sum(components[k] for k in ("time_component","tail_component","queue_component"))


def validate_configuration(actual, config):
    """GUI/Headless equivalence, including declared primary-scenario overrides."""
    expected = dict(config)
    case = expected.get("case", "normal")
    if case in {"low_compliance", "combined"}: expected["compliance"] = .2
    if case in {"delayed", "combined"}: expected["delay_minutes"] = 5.
    if case == "combined": expected["packet_loss"] = .1
    mapping = {"background_cars":"initial_private_cars", "private_evs":"initial_private_evs", "electric_taxis":"initial_electric_taxis", "samples":"scenarios"}
    fields = ("method","case","seed","environment_version","objective_version","observation_version","warmup_minutes","measure_minutes","deadline_minutes","initial_hour","step_seconds","ev_speed_kmh","car_speed_kmh","background_cars","private_evs","electric_taxis","rush_enabled","rush_extra_percent","consumption_kwh_km","charge_efficiency","compliance","defer_probability","decline_probability","abandon_after_minutes","samples","calibrating","temperature","p2p_interval","min_send_seconds","delay_minutes","packet_loss","duplicate_probability","partition_begin","partition_end","behavior_case","stabilization","objective_config_hash")
    for field in fields:
        value=actual.get(mapping.get(field,field))
        wanted=expected[field]
        if isinstance(wanted,bool):
            equal=type(value) is bool and value==wanted
        elif isinstance(wanted,int):
            # GAMA can encode seeds as 800001.0; integer values must still match exactly.
            equal=isinstance(value,(int,float)) and not isinstance(value,bool) and value==wanted
        elif isinstance(wanted,float):
            equal=isinstance(value,(int,float)) and not isinstance(value,bool) and math.isclose(value,wanted,rel_tol=1e-8,abs_tol=1e-7)
        else: equal=value==wanted
        if not equal: raise ValueError(f"GAMA configuration mismatch: {field}")
    return True


def validate_physical_records(folder, config):
    """Independently audit GAMA artifacts; never simulate or synthesize EV behavior."""
    import csv
    from collections import Counter, defaultdict

    def records(name):
        return json.loads((folder / name).read_text())

    initial = records("initial_fleet.json")
    originals = {int(row["id"]): row for row in initial}
    fleet_size = config["background_cars"] + config["private_evs"] + config["electric_taxis"]
    if len(originals) != len(initial) or len(initial) != fleet_size:
        raise ValueError("Initial persistent fleet mismatch")
    kinds = Counter(row["kind"] for row in initial)
    if kinds != Counter(car=config["background_cars"], private=config["private_evs"], taxi=config["electric_taxis"]):
        raise ValueError("Initial fleet categories differ")
    traits_rows = records("vehicle_traits.json")
    traits = {int(row["id"]): row for row in traits_rows}
    if len(traits) != len(traits_rows):
        raise ValueError("Duplicate immutable EV identity")
    for row in traits.values():
        if not finite_tree(row) or not 10 <= row["soc_request_threshold"] < 70 or not row["soc_request_threshold"] < row["soc_preferred_target"] <= 100:
            raise ValueError("Invalid persistent personal charging preferences")
    inventory = records("station_inventory.json")
    ports = {(int(station["sid"]), int(port)): float(power) for station in inventory for port, power in station["ports"].items()}
    if len(inventory) != 11 or len(ports) != 125:
        raise ValueError("Charging station/port inventory differs")
    attempts = {row["request_id"]: row for row in records("request_attempts.json")}
    outcomes = {row['request_id']: row for row in records('outcomes.json')}
    active_ports, active_requests = {}, {}
    terminal_energy = defaultdict(float)
    terminal_ids = set()
    service_starts = 0
    event_keys=set()
    arrived = set()
    with (folder / "events.csv").open() as stream:
        for row in csv.DictReader(stream):
            identity = row["request_id"]
            if identity not in attempts:
                raise ValueError("Session event has no physical request")
            event = row["terminal_record"]
            key=(identity,row.get("token",""),row.get("leg",""),event,row["time_min"])
            if key in event_keys:
                raise ValueError("Duplicate attempt event")
            event_keys.add(key)
            at = float(row['time_min'])
            if not math.isfinite(at) or at < attempts[identity]['at'] - OBJECTIVE_SPEC['time_tol_min']:
                raise ValueError('Event precedes its physical request')
            leg = (identity, row.get('token', ''), row.get('leg', ''))
            if event == 'arrival':
                arrived.add(leg)
            if event == "service_started":
                if leg not in arrived:
                    raise ValueError('Charging service started before arrival')
                port = (int(row["station_sid"]), int(row["port_id"]))
                if port not in ports or port in active_ports or identity in active_requests:
                    raise ValueError("Duplicate or invalid physical port allocation")
                if not 0 < float(row["port_kw"]) <= ports[port] + 1e-7 or float(row["ev_limit_kw"]) <= 0:
                    raise ValueError("Invalid station/vehicle charging power")
                active_ports[port] = identity
                active_requests[identity] = (port, float(row["time_min"]), min(ports[port], float(row["ev_limit_kw"])))
                service_starts += 1
            if event in TERMINAL or event == "service_completed":
                if identity in terminal_ids:
                    raise ValueError("Duplicate terminal session event")
                terminal_ids.add(identity)
                energy = float(row["energy_kwh"])
                outcome = outcomes[identity]
                if (not math.isfinite(energy) or energy < 0
                    or abs(energy - outcome['delivered_kwh']) > OBJECTIVE_SPEC['energy_abs_tol_kwh']
                    or abs(at - outcome['finished_min']) > OBJECTIVE_SPEC['time_tol_min']
                    or outcome['status'] != ('completed' if event == 'service_completed' else event)):
                    raise ValueError('Physical terminal event differs from attempt outcome')
                if identity in active_requests:
                    port, started, maximum = active_requests.pop(identity)
                    active_ports.pop(port)
                    if energy > maximum * config["charge_efficiency"] * max(0.0, float(row["time_min"]) - started) / 60 + 1e-5:
                        raise ValueError("Energy exceeds physical charging power/time")
                elif energy > 1e-7:
                    raise ValueError("Battery charged without a physical charging port")
                terminal_energy[int(attempts[identity]["vehicle_id"])] += energy
                if event == "service_completed" and float(row["soc"]) + 1e-6 < float(row["target_soc"]):
                    raise ValueError("Physical session stopped below target SOC")
    if active_ports or active_requests or terminal_ids != attempts.keys():
        raise ValueError("Unreleased ports or unresolved request sessions")
    last = {}
    observed_stranded=set()
    eligible={int(r["id"]) for r in initial if r["kind"]!="car"}
    traffic_plan=records("traffic_plan.json")
    measurement_start=config["warmup_minutes"];measurement_end=measurement_start+config["measure_minutes"]
    eligible.update(int(r["id"]) for r in traffic_plan if r["kind"]!="car" and min(r["depart"],measurement_end)>max(r["at"],measurement_start))
    soc_rows = 0
    with (folder / "vehicles.csv").open() as stream:
        for row in csv.DictReader(stream):
            identity = int(row["vehicle_id"])
            if row.get("state")=="stranded" and identity in eligible:observed_stranded.add(identity)
            metres, charged, at = float(row["total_metres"]), float(row["total_charged_kwh"]), float(row["at"])
            previous = last.get(identity)
            if previous:
                if at < previous[0] or metres + 1e-6 < previous[1] or charged + 1e-6 < previous[2]:
                    raise ValueError("Vehicle lifetime history moved backwards")
                distance = math.hypot(float(row["x"]) - previous[3], float(row["y"]) - previous[4])
                if distance > metres - previous[1] + 1e-3:
                    raise ValueError(
                        f"Vehicle changed location without recording travel: id={identity}, "
                        f"minutes={previous[0]:g}->{at:g}, "
                        f"displacement_m={distance:.6f}, recorded_m={metres-previous[1]:.6f}"
                    )
            last[identity] = (at, metres, charged, float(row["x"]), float(row["y"]))
            if row["kind"] == "car":
                continue
            if identity not in traits:
                raise ValueError("EV lacks immutable physical/behavior traits")
            trait = traits[identity]
            expected = trait["initial_soc"] + 100 * (charged - metres * config["consumption_kwh_km"] / 1000) / trait["battery_capacity_kwh"]
            soc = float(row["soc"])
            if not 0 <= soc <= 100 or abs(soc - expected) > 1e-4:
                raise ValueError("SOC does not conserve physical energy")
            if abs(float(row["threshold"]) - trait["soc_request_threshold"]) > 1e-6:
                raise ValueError("Individual SOC threshold changed during the episode")
            soc_rows += 1
    if set(map(int,records("stranded_ev_ids.json")))!=observed_stranded:
        raise ValueError("Stranded vehicle history was hidden or inconsistent")
    end = config["warmup_minutes"] + config["measure_minutes"] + config["deadline_minutes"]
    for identity, original in originals.items():
        if identity not in last or last[identity][0] + 1e-7 < end:
            raise ValueError("Persistent vehicle missing from the final snapshot")
        if original["kind"] != "car" and abs(last[identity][2] - terminal_energy[identity]) > 1e-5:
            raise ValueError("Vehicle charged energy differs from its physical sessions")
    gateways = records("gateway_validation.json")["gateways"]
    present = {}
    peak_inbound = 0
    with (folder / "traffic.csv").open() as stream:
        for row in csv.DictReader(stream):
            event, identity, kind = row["event"], int(row["vehicle_id"]), row["kind"]
            if event == "capacity_blocked":
                continue
            gateway = gateways[int(row["gateway"])]
            if math.hypot(float(row["x"]) - gateway["x"], float(row["y"]) - gateway["y"]) >= 2.0001:
                raise ValueError("Inbound vehicle entered/exited away from a gateway")
            if event == "entered":
                if identity in present or identity in originals:
                    raise ValueError("Duplicate inbound vehicle")
                present[identity] = kind
            elif event == "exited":
                if identity not in present:
                    raise ValueError("Inbound vehicle exited without entering")
                del present[identity]
            for category, base in (("car", config["background_cars"]), ("private", config["private_evs"]), ("taxi", config["electric_taxis"])):
                if sum(value == category for value in present.values()) > math.floor(base * config["rush_extra_percent"] / 100):
                    raise ValueError("Concurrent inbound vehicle cap exceeded")
            peak_inbound = max(peak_inbound, len(present))
    intents = records("charging_intents.json")
    for intent in intents:
        if intent["at"] >= config["warmup_minutes"] + config["measure_minutes"]:
            raise ValueError("New charging intent generated during drain")
        if intent["cause"] in {"trip_energy", "shift_energy"} and intent["trip_energy_kwh"] <= intent["soc_at_need"] * traits[int(intent["vehicle_id"])]["battery_capacity_kwh"] / 100 + 1e-7:
            raise ValueError("Energy-feasibility intent lacks an energy shortfall")
    for name in ("opportunities.json", "energy_opportunities.json", "opportunity_outcomes.json"):
        if (folder / name).exists():
            raise ValueError("Legacy charging opportunity artifacts in the revised dataset")
    with (folder / "calibration_contexts.csv").open() as stream:
        for row in csv.DictReader(stream):
            context = json.loads(row["context"])
            if not config["warmup_minutes"] <= context["at"] < config["warmup_minutes"] + config["measure_minutes"]:
                raise ValueError("Calibration issuance context outside measurement window")
    return {"passed": True, "persistent_vehicles": fleet_size, "soc_rows_checked": soc_rows,
            "charging_service_starts": service_starts, "port_inventory": len(ports), "peak_inbound": peak_inbound,
            "intents_checked": len(intents), "requests_checked": len(attempts), "legacy_schedule_present": False}
