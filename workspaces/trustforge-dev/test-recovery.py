#!/usr/bin/env python3
"""Directed offline tests; registry and crypto results are simulated, never real."""
import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('recovery',HERE/'recover-evidence.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


def policy():
    p=r.b.strict_json((HERE/'recovery-policy.example.json').read_text())
    p.update(approved=True,signer_commit='a'*40,trusted_root_sha256=r.ROOT)
    return p


def environment():
    p=policy();h=r.policy_hash(p)
    return {'GITHUB_REPOSITORY':r.C['repository'],'GITHUB_REF':'refs/heads/main','GITHUB_WORKFLOW_REF':r.WORKFLOW,
            'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_SHA':'a'*40,'GITHUB_WORKFLOW_SHA':'a'*40,
            'GITHUB_RUN_ID':'999','GITHUB_RUN_ATTEMPT':'1','TF_POLICY_SHA256':h,
            'TF_RECOVERY_CONFIRMATION':r.p.confirmation().replace('PROMOTE ','RECOVER ',1)+' policy=sha256:'+h}


class Recovery(unittest.TestCase):
    def test_explicit_policy_hash_and_new_workflow_context(self):
        self.assertEqual(r.context(environment()),policy())
        with self.assertRaises(ValueError):r.check_policy(r.b.strict_json((HERE/'recovery-policy.example.json').read_text()))
        for key in environment():
            with self.subTest(key=key),self.assertRaises(ValueError):
                env=environment();env[key]+='bad';r.context(env)
        for run in ('41380381655',str(r.C['run_id'])):
            env=environment();env['GITHUB_RUN_ID']=run
            with self.assertRaises(ValueError):r.context(env)
        for key in ('identity','source_commit','signer_commit','trusted_root_sha256','previous_signer_commit'):
            p=policy();p[key]='invalid'
            with self.subTest(key=key),self.assertRaises(ValueError):r.check_policy(p)

    def test_only_missing_roles_created_and_complete_state_is_noop(self):
        for existing in ({},{'signature':'old-sig'},{'spdx':'old-sbom','provenance':'old-prov'},dict.fromkeys(r.TYPES,'old')):
            state=dict(existing);made=[]
            def scan():return dict(state)
            def create(role):made.append(role);state[role]='new-'+role
            result=r.recover(scan,create)
            self.assertEqual(set(result),set(r.TYPES))
            self.assertEqual(set(made),set(r.TYPES)-set(existing))
            for role,value in existing.items():self.assertEqual(result[role],value)

    def test_scan_errors_never_mean_missing_and_races_stop_writes(self):
        create=mock.Mock()
        with self.assertRaises(ValueError):r.recover(mock.Mock(side_effect=ValueError('invalid signature')),create)
        create.assert_not_called()
        scan=mock.Mock(side_effect=[{}, {'signature':'concurrent'}])
        with self.assertRaises(ValueError):r.recover(scan,create)
        create.assert_not_called()
        state={}
        def fail(role):raise subprocess.CalledProcessError(1,['not-executed'])
        with self.assertRaises(subprocess.CalledProcessError):r.recover(lambda:state.copy(),fail)

    def test_complete_authenticated_inventory_not_generic_verify_output(self):
        env={'payloadType':'application/vnd.in-toto+json','payload':base64.b64encode(json.dumps({
            '_type':'https://in-toto.io/Statement/v1','predicateType':r.b.IMAGE_SIGNATURE,
            'subject':[{'digest':{'sha256':r.C['manifest_digest'][7:]},'annotations':{r.b.REPOSITORY_ANNOTATION:r.b.REPOSITORY}}],
            'predicate':{}}).encode()).decode()}
        entry=('signature','sha256:'+'f'*64,b'fixture',env)
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(r,'discover',return_value=[entry]):
            verifier=mock.Mock(return_value=(r.IDENTITY,'a'*40))
            result=r.inventory(None,None,None,policy(),Path(tmp),verifier)
            self.assertEqual(result,{'signature':entry[1]});verifier.assert_called_once()
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(r,'discover',return_value=[entry,entry]):
            with self.assertRaises(ValueError):r.inventory(None,None,None,policy(),Path(tmp),verifier)
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(r,'discover',return_value=[entry]):
            verifier=mock.Mock(side_effect=ValueError('crypto rejected'))
            with self.assertRaises(ValueError):r.inventory(None,None,None,policy(),Path(tmp),verifier)

    def test_cosign_local_bundle_interface_pins_all_security_controls(self):
        runner=mock.Mock(return_value=subprocess.CompletedProcess([],0,'','Verified OK'))
        self.assertEqual(r.verify_bundle(Path('/cosign'),Path('/root'),policy(),Path('/bundle'),'signature',runner),(r.b.PROMOTION_IDENTITY,r.PREVIOUS))
        command=runner.call_args.args[0]
        for flag in ('verify-blob-attestation','--bundle','--trusted-root','--certificate-identity','--certificate-oidc-issuer',
                     '--certificate-github-workflow-sha','--certificate-github-workflow-trigger','--check-claims=true',
                     '--insecure-ignore-tlog=false','--insecure-ignore-sct=false','--digestAlg'):
            self.assertIn(flag,command)
        self.assertIn(r.C['manifest_digest'][7:],command)
        runner.return_value=subprocess.CompletedProcess([],1,'','failure')
        with self.assertRaises(ValueError):r.verify_bundle(Path('/cosign'),Path('/root'),policy(),Path('/bundle'),'spdx',runner)

    def test_recovery_provenance_retains_original_builder_and_new_signer(self):
        # Reuse the original record constructor; no artifact or crypto is executed.
        env={'GITHUB_REPOSITORY':r.C['repository'],'GITHUB_REF':'refs/heads/main','GITHUB_EVENT_NAME':'workflow_dispatch',
             'GITHUB_WORKFLOW_REF':r.b.WORKFLOW,'GITHUB_SHA':r.C['source_commit'],'GITHUB_WORKFLOW_SHA':r.C['source_commit'],
             'GITHUB_RUN_ID':str(r.C['run_id']),'GITHUB_RUN_ATTEMPT':'1'}
        value=r.p.maker.record(r.CONTRACT,env)
        value.update(artifact=r.IMAGE,recovery={'workflow':{'id':r.IDENTITY,'workflow_ref':r.WORKFLOW,'workflow_sha':'a'*40,'event':'workflow_dispatch'},
                    'invocation':{'run_id':'999','attempt':'1'},'candidate':r.C})
        statement={'_type':'https://in-toto.io/Statement/v1','predicateType':r.b.PROVENANCE,'subject':[{'name':r.b.REPOSITORY,'digest':{'sha256':r.C['manifest_digest'][7:]}}],'predicate':value}
        def envelope(v):return {'payloadType':'application/vnd.in-toto+json','payload':base64.b64encode(json.dumps(v).encode()).decode()}
        r.claims(envelope(statement),'provenance',(r.IDENTITY,'a'*40),policy())
        for field in ('source','builder','recovery'):
            changed=copy.deepcopy(statement);changed['predicate'][field]={}
            with self.subTest(field=field),self.assertRaises((ValueError,KeyError)):r.claims(envelope(changed),'provenance',(r.IDENTITY,'a'*40),policy())

    def test_discovery_rejects_legacy_pagination_and_unavailable_index(self):
        # Root/config bytes are known fixtures; no real registry or manifest fetched.
        raw=b'fixture manifest';config=b'{"os":"linux","architecture":"amd64"}'
        manifest={'config':{'digest':r.C['config_digest'],'size':len(config)}}
        class Fake:
            def __init__(self,mode):self.mode=mode
            def get(self,path,absent=False):
                if path=='manifests/'+r.C['manifest_digest']:return raw,{}
                if absent:return (b'legacy',{}) if self.mode=='legacy' else (None,{})
                if path.startswith('referrers/'):
                    if self.mode=='error':raise ValueError('403 or unsupported 404')
                    return b'{"schemaVersion":2,"mediaType":"application/vnd.oci.image.index.v1+json","manifests":[]}', {'Link':'next'} if self.mode=='page' else {}
                raise AssertionError(path)
        original=r.b.strict_json
        def parse(s):return manifest if s==raw.decode() else original(s)
        with mock.patch.object(r.hashlib,'sha256',return_value=mock.Mock(hexdigest=lambda:r.C['manifest_digest'][7:])),mock.patch.object(r.b,'strict_json',side_effect=parse),mock.patch.object(r,'blob',return_value=config):
            self.assertEqual(r.discover(Fake('empty')),[])
            for mode in ('legacy','page','error'):
                with self.subTest(mode=mode),self.assertRaises(ValueError):r.discover(Fake(mode))

    def test_native_referrer_wire_shapes_and_unknown_types_fail_closed(self):
        # Source-shaped OCI/bundle fixture. Crypto remains explicitly untested.
        def raw(value):return json.dumps(value,separators=(',',':')).encode()
        store={}
        def desc(value,kind='blobs'):
            data=value if isinstance(value,bytes) else raw(value)
            digest='sha256:'+hashlib.sha256(data).hexdigest();store[kind+'/'+digest]=data
            return {'digest':digest,'size':len(data)}
        config=desc({'os':'linux','architecture':'amd64'})
        image=raw({'schemaVersion':2,'config':config,'layers':[]})
        candidate=copy.deepcopy(r.C);candidate['manifest_digest']='sha256:'+hashlib.sha256(image).hexdigest();candidate['config_digest']=config['digest']
        store['manifests/'+candidate['manifest_digest']]=image
        empty=desc(b'{}');empty['mediaType']='application/vnd.oci.empty.v1+json'
        media=next(iter(r.MEDIA))
        for predicate in (r.b.IMAGE_SIGNATURE,'https://unapproved.invalid/predicate'):
            payload={'predicateType':predicate}
            bundle={'mediaType':media,'dsseEnvelope':{'payloadType':'application/vnd.in-toto+json','payload':base64.b64encode(raw(payload)).decode(),'signatures':[{'sig':'fixture'}]}}
            layer=desc(bundle);layer['mediaType']=media
            manifest={'schemaVersion':2,'mediaType':'application/vnd.oci.image.manifest.v1+json','artifactType':media,
                      'subject':{'digest':candidate['manifest_digest'],'size':len(image)},'config':empty,'layers':[layer]}
            descriptor=desc(manifest,'manifests');descriptor['artifactType']=media
            index=raw({'schemaVersion':2,'mediaType':'application/vnd.oci.image.index.v1+json','manifests':[descriptor]})
            class Fake:
                def get(self,path,absent=False):
                    if absent:return None,{}
                    return (index if path.startswith('referrers/') else store[path]),{}
            with mock.patch.object(r,'C',candidate):
                if predicate==r.b.IMAGE_SIGNATURE:self.assertEqual(r.discover(Fake())[0][0],'signature')
                else:
                    with self.assertRaises(ValueError):r.discover(Fake())

    def test_workflow_is_manual_main_environment_and_no_image_write(self):
        w=json.loads((HERE.parents[1]/'.github/workflows/trustforge-recover.yml').read_text())
        self.assertEqual(set(w['on']),{'workflow_dispatch'})
        self.assertEqual(w['jobs']['candidate']['permissions'],{'contents':'read','actions':'read'})
        self.assertEqual(w['jobs']['signer']['environment'],'trustforge-bootstrap-publish')
        self.assertEqual(w['concurrency']['group'],'trustforge-bootstrap-candidate-promotion')
        for job in w['jobs'].values():
            self.assertEqual(job['if'],"github.ref == 'refs/heads/main'")
            for step in job['steps']:
                if 'run' in step:
                    subprocess.run(['bash','-n'],input=step['run'],text=True,check=True)
                    self.assertNotRegex(step['run'],r'\b(skopeo copy|podman|docker|buildah)\b')
                if 'uses' in step:self.assertRegex(step['uses'],r'@[0-9a-f]{40}$')
        run=w['jobs']['signer']['steps'][5]['run']
        self.assertIn('export DOCKER_CONFIG="$authdir"',run)
        self.assertIn('recovery-private',run)
        self.assertEqual(w['jobs']['signer']['permissions'],{'contents':'read','actions':'read','packages':'write','id-token':'write'})


if __name__=='__main__':unittest.main(verbosity=2)
