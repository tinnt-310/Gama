"""Generate an evidence-linked research package; missing results stay missing."""
from pathlib import Path
import argparse
import csv
import json
import shutil
import sys
import time
ROOT=Path('/home/tinnt/Gama_Workspace/Nha Trang CSs planning')
sys.path.insert(0,str(ROOT/'src'))
from ranr.paths import digest,write_json
from ranr.gama.headless import provenance,RunConfig,checked_result,METHODS
from ranr.gama.evidence import reference,verify_reference,verify_native,read_evidence,validate_collection


def audit(release,destination=None):
    release=Path(release).resolve()
    destination=Path(destination) if destination else ROOT/'outputs/gama_ranr/final_research_package'/f'audit_{time.time_ns()}'
    destination.mkdir(parents=True,exist_ok=False)
    state=json.loads((release/'state.json').read_text());registration=json.loads((release/'registration.json').read_text())
    source=provenance();failures=[];refs=[];results={}
    def check(name,fn):
        try:
            value=fn();results[name]={'status':'PASS','details':value}
        except FileNotFoundError as error:results[name]={'status':'PENDING','details':str(error)}
        except Exception as error:results[name]={'status':'FAIL','details':str(error)};failures.append(name+': '+str(error))
    def sealed_stage(stage):
        record=state.get('stages',{}).get(stage)
        if not record or record.get('status')!='complete':raise FileNotFoundError('Stage not complete: '+stage)
        for item in record.get('artifacts',[]):verify_reference(item);refs.append(item)
        return {'active_seconds':record.get('active_seconds'),'artifacts':record.get('artifacts',[])}
    if source!=registration['source']:failures.append('Release source changed')
    check('Python tests',lambda:sealed_stage('python_tests'))
    def native():
        path=ROOT/'outputs/gama_ranr/validation.json';record=verify_native(path);refs.append(reference(path))
        return {'compile_checked':record.get('compile_checked'),'fixture_count':len(record.get('dependencies',[])),
            'execution_source_preserved':record.get('execution_source',record['source'])}
    check('Native validation',native)
    check('GAML validation',lambda:{'compiled':native()['compile_checked'],'model_count':len(list((ROOT/'models').rglob('*.gaml')))})
    def calibration():
        selection=json.loads((release/'calibration_selection.json').read_text())
        path=Path(selection['calibration'])
        if digest(path)!=selection['sha256']:raise ValueError('Calibration hash mismatch')
        record=json.loads(path.read_text())
        if record['source']!=source or record.get('split')!='train':raise ValueError('Calibration is not current train-only data')
        compatibility=record.get('compatibility');proof=Path(compatibility['path']) if compatibility else None
        if proof and digest(proof)!=compatibility['sha256']:raise ValueError('Compatibility changed')
        seeds=[]
        for folder,sha in record['runs'].items():
            folder=Path(folder)
            if digest(folder/'manifest.json')!=sha:raise ValueError('Calibration manifest changed')
            validate_collection(folder,proof)
            seeds.append(json.loads((folder/'manifest.json').read_text())['config']['seed'])
        if sorted(seeds)!=[800001,800002,800003]:raise ValueError('Calibration seeds changed')
        refs.extend([reference(path),reference(release/'calibration_selection.json')])
        return {'seeds':seeds,'prior_snapshots':len(record['prior_snapshots']),'arrival_contexts':len(record['arrival_prior'])}
    check('Calibration',calibration)
    def replay():
        if registration.get('source_transition'):
            from ranr.gama.transition import verify_transition
            proof=verify_transition(registration['source_transition']['path']);path=Path(proof['headless_reproduction']['path'])
        else:path=release/'native_reproducibility.json'
        record=json.loads(path.read_text())
        if not record.get('passed'):raise ValueError('Replay evidence not passed')
        for item in record['dependencies']:verify_reference(item)
        refs.append(reference(path));return {'comparisons':record['comparisons']}
    check('Replay',replay)
    check('Accuracy',lambda:sealed_stage('accuracy'))
    def monte_carlo():
        path=release/'benchmark/reference_stability.json';record=json.loads(path.read_text());refs.append(reference(path))
        if record.get('passed') is not True:
            return {'reference_stable':False,'samples':record.get('samples'),'check_samples':record.get('check_samples'),
                'status':'RUNNING' if state.get('status')=='running' and state.get('current_stage')=='accuracy' else 'NOT_PASSED',
                'pass_fraction':{k:v['pass_fraction'] for k,v in record['methods'].items()}}
        return record
    check('Monte Carlo',monte_carlo)
    if results.get('Monte Carlo',{}).get('details',{}).get('reference_stable') is False:
        results['Monte Carlo']['status']=results['Monte Carlo']['details']['status']
    check('Development',lambda:sealed_stage('development'))
    check('Design configuration',lambda:sealed_stage('design'))
    check('Design freeze',lambda:sealed_stage('freeze'))
    check('Performance benchmark',lambda:sealed_stage('performance'))
    check('Training',lambda:sealed_stage('training'))
    def training():
        path=release/'training/registration.json';record=json.loads(path.read_text())
        if record.get('status')!='complete' or record.get('profile')!='research':raise FileNotFoundError('Research training incomplete')
        if record['source']!=source or record.get('active_seconds',0)>72*3600:raise ValueError('Training provenance/budget invalid')
        refs.append(reference(path));models={}
        for method in METHODS:
            modelpath=release/'training'/method/'parameters.json';model=json.loads(modelpath.read_text())
            if not model.get('training_completed') or model.get('source')!=source:raise ValueError('Untrained/mismatched model')
            refs.append(reference(modelpath));models[method]={'validation_fitness_vector':model['validation_fitness_vector'],'sha256':digest(modelpath)}
        return {'active_seconds':record['active_seconds'],'models':models}
    check('Training model integrity',training)
    def evaluation():
        from ranr.gama.evaluation import check_evaluation_grid
        path=release/'evaluation/registration.json';record=json.loads(path.read_text())
        if record.get('status')!='complete' or record['source']!=source:raise FileNotFoundError('Evaluation incomplete')
        rows_path=release/'evaluation/results.json'
        if record.get('results_sha256')!=digest(rows_path):raise ValueError('Evaluation results changed')
        rows=json.loads(rows_path.read_text());check_evaluation_grid(rows)
        for method,sha in record['models_sha256'].items():
            if digest(Path(record['models'])/method/'parameters.json')!=sha:raise ValueError('Frozen model changed')
        for row in rows:
            folder=release/'evaluation/runs'/row['case']/str(row['seed'])/row['method']
            native=checked_result(folder,{'source':source})
            if native['fitness_vector']!=row['fitness_vector']:raise ValueError('Report differs from sealed physical result')
        refs.extend([reference(path),reference(rows_path)])
        for name in ('summary.csv','summary.json','comparisons.csv','comparisons.json','REPORT_VI.md'):
            sourcepath=release/'evaluation/report'/name
            if sourcepath.exists():shutil.copy2(sourcepath,destination/name);refs.append(reference(sourcepath))
        return {'unique_rollouts':len(rows),'seed_count':30,'methods':list(METHODS),'selection_seeds_disjoint':True}
    check('Evaluation 720 combinations',evaluation)
    if state.get('status')=='running' and state.get('current_stage'):
        matching={'accuracy':'Accuracy','training':'Training','evaluation':'Evaluation 720 combinations','development':'Development','design':'Design configuration'}
        name=matching.get(state['current_stage'])
        if name in results and results[name]['status']=='PENDING':results[name]['status']='RUNNING'
    all_pass=all(x['status']=='PASS' for x in results.values()) and not failures and state.get('status')=='complete'
    inventory={'release':str(release),'source':source,'at':time.time(),'pipeline_status':state.get('status'),
        'current_stage':state.get('current_stage'),'research_complete':all_pass,'checks':results,'failures':failures,'dependencies':refs}
    write_json(destination/'integrity.json',inventory)
    write_json(destination/'missing_evidence.json',{'missing_or_not_passed':[k for k,v in results.items() if v['status']!='PASS']})
    write_json(destination/'reproducibility_manifest.json',{'source':source,'release_registration':reference(release/'registration.json'),'evidence':refs})
    write_json(destination/'execution_summary.json',{'state':state,'audit_at':time.time(),'research_complete':all_pass})
    for name in ('issues.json','equivalence.json','runtime_registration.json'):
        p=Path(__file__).parent/name
        if p.exists():shutil.copy2(p,destination/name)
    text='# Báo cáo kiểm chứng RANR–GAMA\n\n'
    text+='Trạng thái: **'+('COMPLETED' if all_pass else str(state.get('status','unknown')).upper())+'**. Release `'+release.name+'`.\n\n'
    text+='| Hạng mục | Trạng thái | Bằng chứng |\n|---|---|---|\n'
    for name,row in results.items():text+='| '+name+' | '+row['status']+' | Xem integrity.json |\n'
    text+='\nKhông suy ra gate đạt từ sự tồn tại của code. Dữ liệu chưa có được ghi thiếu, không có giá trị thay thế.\n\n'
    text+='## Hạn chế nghiên cứu\n\nFleet, SOC, lịch hoạt động, tiêu thụ năng lượng và hành vi phản hồi là các giả định mô phỏng chưa được hiệu chỉnh bằng khảo sát Nha Trang. Calibration là dữ liệu mô phỏng train-only, không phải xác nhận thực địa. Hiệu quả RANR so với baseline chỉ được kết luận sau evaluation độc lập.\n\n'
    text+='## Mức sẵn sàng IEEE\n\n'+('Đủ dữ liệu kỹ thuật để rà soát kết quả và viết phần thực nghiệm; vẫn cần đánh giá giả định và giới hạn thực địa.' if all_pass else 'Chưa đủ bằng chứng để viết kết luận hiệu quả hoặc công bố hoàn tất thực nghiệm. Các gate chưa đạt được liệt kê trong missing_evidence.json.')+'\n'
    (destination/'FINAL_REPORT_VI.md').write_text(text)
    return destination,inventory


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--release',type=Path,required=True);parser.add_argument('--output',type=Path)
    args=parser.parse_args();path,result=audit(args.release,args.output)
    print(json.dumps({'package':str(path),'research_complete':result['research_complete'],'checks':{k:v['status'] for k,v in result['checks'].items()}},ensure_ascii=False,indent=2))
