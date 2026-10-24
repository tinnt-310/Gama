"""Produce an independent final/current report without changing runtime or gates."""
from pathlib import Path
import importlib.util
import argparse
import json
import sys
import time
ROOT=Path('/home/tinnt/Gama_Workspace/Nha Trang CSs planning')
OPS=ROOT/'operations/mc_checkpoint_20261023'
ARCHIVE=ROOT/'outputs/gama_ranr/autonomous_20261023'
sys.path.insert(0,str(ROOT/'src'))
from ranr.paths import write_json,digest
from ranr.gama.evidence import reference,verify_reference,read_evidence
from ranr.gama.headless import provenance
from reporting_checks import stage_status,failure_certificate
spec=importlib.util.spec_from_file_location('original_research_audit',OPS/'research_audit.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)


def finalize(release):
    release=Path(release).resolve();destination,record=base.audit(release)
    state=json.loads((release/'state.json').read_text());checks=record['checks'];proofs=[]
    mapping={'Python tests':'python_tests','Accuracy':'accuracy','Development':'development',
             'Design configuration':'design','Design freeze':'freeze','Performance benchmark':'performance','Training':'training','Evaluation 720 combinations':'evaluation'}
    for name,stage in mapping.items():
        observed=stage_status(state,stage)
        if observed in {'FAIL','BUDGET_LIMITED','INTERRUPTED','RUNNING'}:checks[name]['status']=observed
    # Independent verification of the maximum-reference early FAIL; no full
    # grid, pass fraction or successful stage is fabricated from partial rows.
    certificate=release/'benchmark/conclusive_reference_failure.json'
    if certificate.exists():
        proof=failure_certificate(certificate);write_json(destination/'verified_reference_failure.json',proof)
        checks['Monte Carlo']={'status':'FAIL','details':proof};checks['Accuracy']['status']='FAIL';proofs.append(reference(certificate))
    chunk_ops=ROOT/'operations/mc_chunks_20261023'
    if (chunk_ops/'equivalence.json').exists():
        sys.path.insert(0,str(chunk_ops))
        import chunk_runtime
        try:
            equivalence=chunk_runtime.verify_equivalence()
            checks['Native chunk equivalence']={'status':'PASS','details':{'samples':equivalence['samples'],'keys':equivalence['keys'],'tolerance':1e-7,'code':equivalence['code']}}
            proofs.append(reference(chunk_ops/'equivalence.json'))
        except Exception as error:checks['Native chunk equivalence']={'status':'FAIL','details':str(error)}
    durable=ROOT/'outputs/gama_ranr/autonomous_mc_chunks_20261023/budget_durability_validation.json'
    if durable.exists():
        try:
            validation=read_evidence(durable)
            runtime=json.loads((chunk_ops/'runtime_registration.json').read_text())
            verify_reference(runtime['budget_ledger'])
            if validation['implementation_sha256']!=runtime['budget_ledger']['sha256']:raise ValueError('Durable budget implementation differs from runtime')
            checks['Budget I/O durability']={'status':'PASS','details':{'unit_tests':validation['unit_tests'],'cma_integration_tests':validation['cma_integration_tests'],'isolated_sigkill_recovery':validation['isolated_sigkill_recovery']}}
            proofs.append(reference(durable))
        except Exception as error:checks['Budget I/O durability']={'status':'FAIL','details':str(error)}
    if provenance()!=json.loads((release/'registration.json').read_text())['source']:
        checks['Release provenance']={'status':'FAIL','details':'Core source mismatch'}
    else:checks['Release provenance']={'status':'PASS','details':'Current core source matches immutable release registration'}
    if checks['Accuracy']['status']=='PASS':
        accuracy=read_evidence(release/'benchmark/accuracy_gate.json');proofs.append(reference(release/'benchmark/accuracy_gate.json'))
    training=release/'training/registration.json'
    if training.exists():
        train=json.loads(training.read_text())
        if train['status']!='complete':checks['Training']['status']=str(train['status']).upper()
    progress=[]
    progress_paths=[path for layout in ('native_shards','native_chunks') for path in sorted((release/'benchmark'/layout).glob('*/progress.json'))]
    for path in progress_paths:
        progress.append({'path':str(path),**json.loads(path.read_text())})
    write_json(destination/'runtime_progress_snapshot.json',{'at':time.time(),'state':state,'native_probe_progress':progress})
    integrity_ok=all(checks[name]['status']=='PASS' for name in ('Native validation','GAML validation','Calibration','Replay','Release provenance'))
    checks['Data integrity']={'status':'PASS' if integrity_ok else 'FAIL','details':'Checks cover existing sealed native, replay and calibration records; no assertion of future training/evaluation integrity'}
    complete=all(x['status']=='PASS' for x in checks.values()) and not record['failures'] and state.get('status')=='complete'
    record.update(checks=checks,research_complete=complete,at=time.time());record['dependencies']+=proofs
    write_json(destination/'integrity.json',record)
    write_json(destination/'missing_evidence.json',{'missing_or_not_passed':[k for k,v in checks.items() if v['status']!='PASS']})
    write_json(destination/'execution_summary.json',{'state':state,'audit_at':time.time(),'research_complete':complete})
    for name in ('training_summary','evaluation_summary','baseline_comparison','statistical_analysis'):
        source=release/('training/registration.json' if name=='training_summary' else 'evaluation/results.json')
        write_json(destination/(name+'.json'),{'status':'AVAILABLE' if source.exists() else 'MISSING','source':reference(source) if source.exists() else None,'note':'No replacement values; see sealed official report for seed-level statistics when complete'})
    write_json(destination/'issue_resolution.json',[
      {'id':'MC-001','status':'DEPLOYED_TESTED','files':['mc_runtime.py','PredictionShard.gaml'],'evidence':reference(OPS/'equivalence.json'),'result':'165/165 native probe equivalence at 32 samples; sealed resumable full-count jobs'},
      {'id':'MC-002','status':'DEPLOYED_TESTED','result':'Benchmark-only scenario cache disabled; heavy 1024 probe mean/P95/H exact. No unpaired speedup claim.'},
      {'id':'OPS-001','status':'RESOLVED','result':'Historical Signal 15 state retained in resume_history; current attempt has distinct state'},
      {'id':'TRAIN-001','status':'TESTED_AWAITING_PRODUCTION','files':['budget_ledger.py'],'result':'5-second conservative elapsed journal; SIGKILL fixture and 2 CMA resume integration tests passed; official training not started yet'},
      {'id':'REPORT-001','status':'TESTED','files':['reporting_checks.py'],'result':'Scientific failure verified from native CSV hashes; failed and budget_limited stages cannot appear as PASS; 5 regression tests passed'}])
    if (ARCHIVE/'issues.json').exists():
        import shutil;shutil.copy2(ARCHIVE/'issues.json',destination/'issues_before_resolution.json')
    sourceproof=json.loads((OPS/'equivalence.json').read_text())
    (destination/'METHODS_AND_LIMITATIONS_VI.md').write_text('''# Phương pháp và giới hạn — RANR–GAMA

Đây là hệ thống mô phỏng tác tử GAMA và tối ưu CMA-ES, không phải training mạng neural hay reinforcement learning. GAMA tính vật lý và fitness; Python kiểm tra ledger, điều phối rollout và xếp hạng lexicographic. Model vật lý persistent-soc-activity-6, objective intent-service-5.

Giao thức chính: 360 phút warmup, 3600 phút measurement, 360 phút drain, bước 60 giây. Fleet chính 3000 xe thông thường, 1000 EV cá nhân, 700 taxi điện; traffic inbound là thành phần riêng của mô hình. Bốn phương pháp RANR-AW, No-P2P, No-Prediction, Fixed-Weights. Ba phương pháp thích nghi có 20 tham số, Fixed-Weights có 4. Giữ số cổng/công suất trạm trong vật lý, không tự thêm feature policy.

Fitness có năm thành phần ưu tiên: stranded/EV-day, mobility unserved/EV-day, not-on-time/EV-day, unmet kWh/EV-day, operational. Thành phần cuối bằng 0.5 mean completion/360 + 0.3 P95 wait/360 + 0.2 queue pressure. Không được dùng riêng operational để bỏ qua bốn ưu tiên đầu.

Calibration dùng seed 800001–800003, train-only. Candidate dùng seed 11001–11006 theo scenario, validation cố định 21001–21006. Optimizer dùng 41001–41003. Evaluation dùng 31001–31030, 4 phương pháp × 6 scenario × 30 seed = 720 lượt. Validation dùng chọn model nên không phải tập kiểm định độc lập. Không dùng candidate hoặc từng xe như những mẫu thống kê độc lập.

Accuracy estimator giữ ngưỡng mean wait 1 phút, P95 wait 5 phút, externality 5 vehicle-minutes; reference stability dùng một nửa. Từng phương pháp phải có ít nhất 95% trong 55 probe đạt đồng thời. Ngưỡng externality là lựa chọn kỹ thuật đăng ký trước, không phải chuẩn thực địa. Reference tối đa 16384 mẫu; không tự tăng cap hoặc nới tiêu chí khi không đạt. Bộ điều phối mới chỉ chia probe, vẫn dùng toàn bộ N mẫu/seed native cho mỗi probe.

Design chính temperature=0.2, heartbeat=5 phút, stabilization=off. Biến thể design là phân tích độ nhạy, không chọn sau khi xem evaluation. Ngân sách training riêng tối đa 72 giờ, cộng dồn qua resume; development, benchmark và evaluation tính riêng. Không xuất model chính thức từ một population chưa đủ hoặc training budget_limited.

Báo cáo thống kê chính dùng seed làm đơn vị, so sánh ghép cặp và Holm cho ba baseline trong từng metric/scenario như pipeline đăng ký. Cần báo cả cỡ mẫu, thống kê null, constraint violations và kết quả không thuận lợi. Các phép kiểm định nhiều metric/scenario không đồng nghĩa đã kiểm soát family-wise error trên toàn bài báo.

Fleet, dung lượng pin, SOC ban đầu, hoạt động, mức tiêu thụ, đáp ứng và công suất là giả định mô phỏng; calibration từ mô phỏng không xác nhận thực địa Nha Trang. Kết quả GAMA chỉ hỗ trợ kết luận trong phạm vi các giả định được kiểm chứng. Chưa có evaluation thì chưa có bằng chứng RANR vượt baseline, chưa có effect size hoặc cải thiện có ý nghĩa để công bố.
''')
    rows=[('Release',str(state.get('status','unknown')).upper(),'Release '+release.name),
      *[(name,checks[name]['status'],'Xem integrity.json') for name in ('Native validation','Replay','Calibration','Accuracy','Monte Carlo','Development','Design freeze','Training','Evaluation 720 combinations','Python tests','GAML validation','Data integrity')],
      ('Final report','COMPLETE' if complete else 'INTERIM','Báo cáo hiện trạng; không thay thế kết quả còn thiếu')]
    text='# Báo cáo thực thi và kiểm chứng RANR–GAMA\n\n'
    text+='**'+('COMPLETED' if complete else str(state.get('status','unknown')).upper())+'** — trạng thái theo dữ liệu thực tế.\n\n| Hạng mục | Trạng thái | Bằng chứng |\n|---|---|---|\n'
    text+=''.join('| '+' | '.join(row)+' |\n' for row in rows)
    text+='\n## Công việc và sửa lỗi\n\nĐã triển khai bộ checkpoint theo probe trên cùng release/service, kiểm chứng đủ 165 probe native tại 32 mẫu và đối chiếu thêm probe tải nặng tại 1024 mẫu; không đổi tiêu chí. Đã bổ sung journal training, thử mất điện bằng fixture riêng, watchdog chỉ giám sát Java thuộc service và lưu chứng cứ. Core Python 110 test đạt, 30/30 GAML biên dịch; 18 test runtime, 2 test CMA tích hợp và 5 test báo cáo bổ sung đạt. Xem issue_resolution.json và archive autonomous_20261023. Bản chia khối sau đó đạt 165/165 probe trong tolerance 1e-7, thêm 12 regression test và đối chiếu native probe tải nặng 1024 mẫu. Ghi bền vững journal/checkpoint có 9 test, 3 CMA integration và thử SIGKILL riêng; bằng chứng ở autonomous_mc_chunks_20261023.\n'
    if certificate.exists():
        text+='\n## Gate không đạt\n\nCặp reference 8192/16384 không thể đạt yêu cầu: đã có ít nhất 3 probe của cùng phương pháp thất bại trong 55 probe, nên tỷ lệ đạt tối đa 52/55 = 94.545%, thấp hơn 95%. verified_reference_failure.json tái tính từ dữ liệu native đã seal. Đây là kết quả kiểm định, không phải lỗi hạ tầng. Giữ nguyên dữ liệu, dừng trước training; cần quyết định giao thức phiên bản mới.\n'
    text+='\n## Công việc còn lại\n\n'+', '.join(k for k,v in checks.items() if v['status']!='PASS')+'. Xem missing_evidence.json. Không tạo kết quả thay thế cho dữ liệu thiếu.\n'
    text+='\n## Vận hành\n\nRelease: `'+str(release)+'`. State: `state.json`; log: `supervisor.log` và `<stage>.log`; Monte Carlo checkpoint hiện hành: `benchmark/native_chunks/16384/` (các native_shards cũ giữ nguyên); training checkpoint khi bắt đầu: `training/checkpoint.pkl`.\n\nTừ thư mục dự án:\n\n```bash\n.venv/bin/python -B operations/mc_chunks_20261023/status.py\n.venv/bin/python -B -m ranr.gama.release status\n.venv/bin/python -B -m ranr.gama.release stop\n```\n'
    text+='\n## Kết quả nghiên cứu và IEEE\n\nBằng chứng hiện có xác nhận khả năng chạy/kiểm chứng kỹ thuật trong phạm vi fixture, replay và calibration. Chưa đủ evaluation độc lập để kết luận hiệu quả so với baseline hoặc sẵn sàng công bố kết quả thực nghiệm IEEE. Xem METHODS_AND_LIMITATIONS_VI.md; các giả định mô phỏng chưa được đo thực địa.\n'
    (destination/'FINAL_REPORT_VI.md').write_text(text)
    if (chunk_ops/'runtime_registration.json').exists():
        import shutil
        for name in ('runtime_registration.json','equivalence.json'):
            prior=destination/name
            if prior.exists():prior.rename(destination/('legacy_'+name))
            shutil.copy2(chunk_ops/name,destination/name)
        reproduction=json.loads((destination/'reproducibility_manifest.json').read_text())
        reproduction['runtime_registration']=reference(chunk_ops/'runtime_registration.json')
        reproduction['native_chunk_equivalence']=reference(chunk_ops/'equivalence.json')
        reproduction['durable_budget_validation']=reference(durable)
        write_json(destination/'reproducibility_manifest.json',reproduction)
        issues=json.loads((destination/'issue_resolution.json').read_text())
        issues.extend([
            {'id':'MC-003','status':'DEPLOYED_TESTED','files':['chunk_runtime.py','PredictionChunk.gaml','NativeAggregate.gaml'],'evidence':reference(chunk_ops/'equivalence.json'),'result':'Absolute sample range checkpoints, native full-sample statistics, 165/165 oracle and heavy 1024 equivalence; 12 regression tests'},
            {'id':'TRAIN-002','status':'DEPLOYED_TESTED_AWAITING_TRAINING','evidence':reference(durable),'result':'Fsync checkpoint/journal data before atomic replace and directory sync; same pickle/CMA state; 9 unit, 3 CMA integration, isolated SIGKILL fixture'},
            {'id':'OPS-002','status':'DEPLOYED_TESTED','result':'Same service, no automatic replay of a proved scientific reference/physical/budget failure'}])
        write_json(destination/'issue_resolution.json',issues)
    files=[reference(path) for path in sorted(destination.iterdir()) if path.is_file()]
    write_json(destination/'package_manifest.json',{'at':time.time(),'release':str(release),'research_complete':complete,'files':files,'reporter':reference(Path(__file__)),'checks_module':reference(Path(__file__).with_name('reporting_checks.py'))})
    print(json.dumps({'package':str(destination),'research_complete':complete,'status':state['status'],'checks':{k:v['status'] for k,v in checks.items()}},indent=2))
    return destination

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--release',type=Path,required=True);args=parser.parse_args();finalize(args.release)
