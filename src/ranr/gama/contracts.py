"""Schemas and independent checks of GAMA records; no simulation or prediction."""
from __future__ import annotations
import math

TERMINAL = frozenset({"completed", "no_feasible_station", "voluntary_deferred", "declined", "abandoned", "deadline_missed", "stranded"})
OBJECTIVE_VERSION = "opportunity-service-3"
OBSERVATION_VERSION = "station-observation-3"


def finite_tree(value):
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(finite_tree(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return all(finite_tree(v) for v in value)
    return False


def validate_ledger(opportunities, ledger, outcomes):
    """Check opportunity accounting including legitimate physical ineligibility."""
    planned = {x["key"]: x for x in opportunities}
    if len(planned) != len(opportunities):
        raise ValueError("Duplicate opportunity IDs")
    actual = {x["key"]: x for x in ledger}
    if len(actual) != len(ledger) or actual.keys() != planned.keys():
        raise ValueError("Missing or duplicate opportunity outcomes")
    requests = {x["key"]: x for x in outcomes}
    if len(requests) != len(outcomes):
        raise ValueError("Duplicate request outcomes")
    for key, row in actual.items():
        original = planned[key]
        if any(row[k] != original[k] for k in ("vehicle_id", "at", "cause")):
            raise ValueError("Opportunity manifest changed")
        if row["status"] == "activated":
            if key not in requests or requests[key]["vehicle_id"] != row["vehicle_id"]:
                raise ValueError("Activated opportunity missing request outcome")
        elif key in requests:
            raise ValueError("Ineligible opportunity produced a request")
    for row in outcomes:
        if row["status"] not in TERMINAL or not finite_tree(row):
            raise ValueError("Invalid terminal outcome")
        if not 0 <= row["delivered_kwh"] <= row["requested_kwh"] + 1e-7:
            raise ValueError("Invalid delivered energy")
        if row["status"] == "completed" and row["requested_kwh"] - row["delivered_kwh"] > 1e-7:
            raise ValueError("Incomplete energy labeled completed")
        for name in ("travel_min", "waiting_min", "charging_min"):
            if row[name] < 0:
                raise ValueError("Negative lifecycle duration")
        if abs(row["service_time_min"] - sum(row[n] for n in ("travel_min", "waiting_min", "charging_min"))) > 1e-7:
            raise ValueError("Inconsistent completion-time accounting")
    return True


def rescore_components(components, failure_factor=1.0, energy_factor=1.0):
    """Analysis of GAMA-produced decompositions, never replacement fitness."""
    if components["version"] != OBJECTIVE_VERSION or not finite_tree(components):
        raise ValueError("Invalid objective decomposition")
    return (components["time_component"] + components["tail_component"] + components["queue_component"]
            + failure_factor * components["failure_component"] + energy_factor * components["energy_component"])


def validate_configuration(actual, config):
    """GUI/Headless equivalence, including declared primary-scenario overrides."""
    expected = dict(config)
    case = expected.get("case", "normal")
    if case in {"low_compliance", "combined"}: expected["compliance"] = .2
    if case in {"delayed", "combined"}: expected["delay_minutes"] = 5.
    if case == "combined": expected["packet_loss"] = .1
    mapping = {"background_cars":"initial_private_cars", "private_evs":"initial_private_evs", "electric_taxis":"initial_electric_taxis", "samples":"scenarios"}
    fields = ("method","case","seed","environment_version","objective_version","observation_version","warmup_minutes","measure_minutes","deadline_minutes","initial_hour","step_seconds","ev_speed_kmh","car_speed_kmh","background_cars","private_evs","electric_taxis","private_frequency","taxi_frequency","soc_threshold","target_soc","rush_enabled","rush_extra_percent","consumption_kwh_km","charge_efficiency","compliance","defer_probability","decline_probability","abandon_after_minutes","burst_size","samples","calibrating","temperature","p2p_interval","min_send_seconds","delay_minutes","packet_loss","duplicate_probability","partition_begin","partition_end","behavior_case","stabilization","failure_beta","energy_beta")
    for field in fields:
        value=actual.get(mapping.get(field,field))
        wanted=expected[field]
        if isinstance(wanted,(int,float)) and not isinstance(wanted,bool):
            equal=isinstance(value,(int,float)) and math.isclose(value,wanted,rel_tol=1e-8,abs_tol=1e-7)
        else: equal=value==wanted
        if not equal: raise ValueError(f"GAMA configuration mismatch: {field}")
    return True
