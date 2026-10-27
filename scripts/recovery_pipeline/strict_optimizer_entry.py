"""One native strict-F04 entry for smoke and conditional official training."""
from pathlib import Path
import argparse
import json
import os
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[3]
SOURCE = Path(__file__).resolve().parents[2]
os.environ['RANR_WORKSPACE'] = str(SOURCE)
sys.path.insert(0,str(SOURCE / 'src'))
from ranr.gama.headless import provenance, RunConfig
from ranr.gama.evidence import verify_reference
from strict_fitness_boundary import StrictNativeRunner


def verify_model(path):
    record = json.loads(Path(path).read_text())
    if (record.get('kind') != 'model_validation_acceptance'
            or record.get('passed') is not True or record.get('source') != provenance()
            or not record.get('dependencies')):
        raise ValueError('Current repair-source model acceptance required before optimizer smoke')
    for item in record['dependencies']:
        verify_reference(item)


def official_hold():
    hold = json.loads((BASE / 'TRAINING_LAUNCH_HOLD.json').read_text())
    # A missing/unreadable record also raises before any optimizer construction.
    if hold.get('active') is not False or not hold.get('release_acceptance'):
        raise ValueError('Official training launch is held for repair/source/scientific acceptance')
    verify_reference(hold['release_acceptance'])
    release = json.loads(Path(hold['release_acceptance']['path']).read_text())
    if release.get('passed') is not True or release.get('source') != provenance():
        raise ValueError('Launch-hold release does not match the accepted repair source')
    for item in release.get('dependencies',[]):
        verify_reference(item)
    frozen = json.loads((BASE / 'official_training/inputs_frozen.json').read_text())
    if frozen.get('source') != provenance() or frozen.get('hours') != 72 or frozen.get('held_out_720') is not False:
        raise ValueError('Immutable official inputs do not match the authorized training')
    for item in frozen['dependencies']:
        verify_reference(item)
    from ranr.gama.evidence import verify_training_acceptance
    verify_training_acceptance(SOURCE / 'outputs/gama_ranr/pre_training_acceptance.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--budget',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--model-proof',type=Path)
    parser.add_argument('--smoke',action='store_true')
    parser.add_argument('--resume',action='store_true')
    args = parser.parse_args()
    if args.smoke:
        if not args.model_proof:
            raise ValueError('Model proof required before smoke')
        verify_model(args.model_proof)
    else:
        official_hold()
    # RunConfig enforces the canonical, hash-linked limited import certificate.
    config = RunConfig.load(args.config)
    from ranr.gama import training
    original = training.run
    training.run = StrictNativeRunner(original,args.output,provenance())
    try:
        print(json.dumps(training.train(config,args.output,args.budget,
            resume=args.resume,smoke=args.smoke)),flush=True)
    finally:
        training.run = original


if __name__=='__main__':
    main()
