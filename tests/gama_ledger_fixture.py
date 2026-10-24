"""Explicit synthetic ledgers for contract tests; never used by the simulator."""
from ranr.gama.contracts import OBJECTIVE_VERSION, OBJECTIVE_CONFIG_HASH


def ledger_fixture(created=5., finished=22., status='completed', delivered=10.):
    intent=dict(intent_id='i1',key=1,vehicle_id=10000,kind='private',at=created,deadline=created+360.,
                cause='low_soc',soc_at_need=29.,threshold=40.,attempts=1,status=status)
    attempt=dict(intent_id='i1',key=1,vehicle_id=10000,request_id='r1',attempt_id='r1',at=created,
                 deadline=created+360.,attempt=1,passenger=False,source='physical_energy')
    outcome=dict(key=1,intent_id='i1',vehicle_id=10000,request_id='r1',attempt_id='r1',status=("stranded" if status=="failed" else status),
                 issued_min=created,finished_min=finished,requested_kwh=10.,delivered_kwh=delivered,
                 travel_min=3.,waiting_min=4.,charging_min=10.,service_time_min=17.)
    completed=status=='completed'
    final=dict(intent,issued_min=created,finished_min=finished,observation_end=finished,status=status,
        actual_completion_time=finished if completed else None,completion_time_min=finished-created if completed else None,
        elapsed_min=finished-created,service_time_min=finished-created,travel_min=3.,waiting_min=4.,charging_min=10.,
        deferred_min=0.,retry_delay_min=0.,other_elapsed_min=finished-created-17.,
        requested_kwh=10.,initial_required_kwh=10.,consumed_kwh=0.,delivered_kwh=delivered,
        initial_battery_kwh=17.4,final_battery_kwh=17.4+delivered,grid_kwh=delivered/.9,
        charging_loss_kwh=delivered/.9-delivered,energy_complete=delivered>=10.-1e-6,
        on_time=completed and finished<=created+360.,deadline_missed=finished>created+360. and not (completed and finished<=created+360.),
        right_censored=status=='unresolved',queue_eligible=True,attempt_ids=['r1'],final_soc=90.,target_soc=90.)
    target=(17.4+10.)/60.*100.
    intent['target_soc']=target
    intent.update(battery_capacity_kwh=60.,initial_required_kwh=10.,initial_battery_kwh=17.4)
    final.update(target_soc=target,final_soc=(17.4+delivered)/60.*100.,battery_capacity_kwh=60.)
    return [intent],[attempt],[outcome],[final]


def fitness_fixture(case='normal', seed=1, **changes):
    r=dict(objective_version=OBJECTIVE_VERSION,objective_config_hash=OBJECTIVE_CONFIG_HASH,fitness_valid=True,
           fitness_vector=[0.,0.,0.,0.,0.],operational_objective=0.,planned_ev_days=10.,
           stranded_vehicle_count=0,mobility_unserved_count=0,not_on_time_count=0,unmet_kwh=0.,
           exogenous_hash='same-plan',case=case,seed=seed)
    r.update(changes)
    r['fitness_vector']=[r[k]/r['planned_ev_days'] for k in ('stranded_vehicle_count','mobility_unserved_count','not_on_time_count','unmet_kwh')]+[r['operational_objective']]
    return r
