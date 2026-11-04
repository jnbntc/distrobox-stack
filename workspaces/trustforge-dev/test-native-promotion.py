#!/usr/bin/env python3
"""Directed OFFLINE negatives; no registry writes, signing, or crypto claims."""
import base64
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('native',HERE/'promote-native.py')
n=importlib.util.module_from_spec(spec);spec.loader.exec_module(n)


def policy():
    p=json.loads((HERE/'native-policy.example.json').read_text())
    p.update(approved=True,signer_commit='a'*40,destination='registry.example.org/tf003/new',namespace_approval='owner-reviewed-new-namespace-0001')
    return p


def env():
    p=policy()
    return {'GITHUB_REPOSITORY':n.C['repository'],'GITHUB_REF':'refs/heads/main','GITHUB_EVENT_NAME':'workflow_dispatch',
            'GITHUB_WORKFLOW_REF':n.WORKFLOW,'GITHUB_SHA':'a'*40,'GITHUB_WORKFLOW_SHA':'a'*40,'GITHUB_RUN_ID':'1000','GITHUB_RUN_ATTEMPT':'1',
            'TF_DESTINATION':p['destination'],'TF_NAMESPACE_APPROVAL':p['namespace_approval'],'TF_POLICY_SHA256':n.canonical(p),
            'TF_NATIVE_CONFIRMATION':n.confirmation(p)}


class Native(unittest.TestCase):
    def test_policy_and_context_no_implicit_old_policy(self):
        self.assertEqual(n.context(env()),policy())
        for key in env():
            e=env();e[key]+='invalid'
            with self.subTest(key=key),self.assertRaises(ValueError):n.context(e)
        for key in policy():
            p=policy();p[key]=None
            with self.subTest(key=key),self.assertRaises((ValueError,TypeError)):n.check_policy(p)
        for value in ['ghcr.io/jnbntc/trustforge-dev','http://registry.example.org/repo','localhost/repo','registry.example.org:443/repo','registry.example.org/repo?x=1','user:secret@registry.example.org/repo']:
            with self.subTest(value=value),self.assertRaises(ValueError):n.destination(value)

    def test_original_source_not_rewritten(self):
        record=n.p.maker.record(n.r.CONTRACT,{'GITHUB_REPOSITORY':n.C['repository'],'GITHUB_REF':'refs/heads/main','GITHUB_EVENT_NAME':'workflow_dispatch',
            'GITHUB_WORKFLOW_REF':n.b.WORKFLOW,'GITHUB_SHA':n.C['source_commit'],'GITHUB_WORKFLOW_SHA':n.C['source_commit'],
            'GITHUB_RUN_ID':str(n.C['run_id']),'GITHUB_RUN_ATTEMPT':'1'})
        result=n.provenance(policy(),record,env())
        self.assertEqual(result['source']['commit'],n.C['source_commit'])
        self.assertEqual(result['parameters']['image_repository'],'ghcr.io/jnbntc/trustforge-dev')
        self.assertEqual(result['artifact'],policy()['destination']+'@'+n.C['manifest_digest'])
        self.assertNotEqual(result['native_promotion']['signer_commit'],result['source']['commit'])
        bad=copy.deepcopy(record);bad['source']['commit']='b'*40
        with self.assertRaises(ValueError):n.provenance(policy(),bad,env())

    def test_signature_cannot_be_replaced_and_crypto_failure_denies(self):
        with tempfile.TemporaryDirectory() as d:
            for role in ('signature','spdx','provenance'):
                entry=(role,'sha256:'+'f'*64,b'not-a-real-bundle',{})
                with mock.patch.object(n.r,'discover',return_value=[entry]),mock.patch.object(n.b,'invoke',side_effect=ValueError('simulated crypto failure')):
                    with self.subTest(role=role),self.assertRaises(ValueError):n.authenticated_inventory(object(),policy(),Path('/cosign'),Path('/root'),Path(d))
            envelope={'payloadType':'application/vnd.in-toto+json','payload':base64.b64encode(json.dumps({'_type':'https://in-toto.io/Statement/v1','predicateType':n.b.SPDX,'subject':[{'name':policy()['destination'],'digest':{'sha256':n.C['manifest_digest'][7:]}}],'predicate':{}}).encode()).decode()}
            entry=('signature','sha256:'+'f'*64,b'fixture',envelope)
            with mock.patch.object(n.r,'discover',return_value=[entry]),mock.patch.object(n.b,'invoke',return_value=''):
                with self.assertRaises(ValueError):n.authenticated_inventory(object(),policy(),Path('/cosign'),Path('/root'),Path(d))

    def test_incomplete_and_unknown_inventory_denies(self):
        with tempfile.TemporaryDirectory() as d:
            for error in ('duplicate referrer','unknown predicate','incomplete paginated inventory','unsupported evidence format','referrer subject mismatch'):
                with mock.patch.object(n.r,'discover',side_effect=ValueError(error)),mock.patch.object(n.b,'invoke') as invoke:
                    with self.subTest(error=error),self.assertRaises(ValueError):n.authenticated_inventory(object(),policy(),Path('/cosign'),Path('/root'),Path(d))
                    invoke.assert_not_called()

    def test_native_discovery_parser_rejects_duplicate_unknown_and_pagination(self):
        def raw(x):return json.dumps(x,separators=(',',':')).encode()
        store={}
        def desc(value,kind='blobs'):
            data=value if isinstance(value,bytes) else raw(value)
            digest='sha256:'+n.hashlib.sha256(data).hexdigest();store[kind+'/'+digest]=data
            return {'digest':digest,'size':len(data)}
        config=desc({'os':'linux','architecture':'amd64'})
        image=raw({'schemaVersion':2,'config':config,'layers':[]})
        candidate=copy.deepcopy(n.C);candidate.update(manifest_digest='sha256:'+n.hashlib.sha256(image).hexdigest(),config_digest=config['digest'])
        store['manifests/'+candidate['manifest_digest']]=image
        empty=desc(b'{}');empty['mediaType']='application/vnd.oci.empty.v1+json';media=next(iter(n.r.MEDIA))
        statement={'predicateType':n.b.IMAGE_SIGNATURE}
        bundle={'mediaType':media,'dsseEnvelope':{'payloadType':'application/vnd.in-toto+json','payload':base64.b64encode(raw(statement)).decode(),'signatures':[{'sig':'fixture'}]}}
        layer=desc(bundle);layer['mediaType']=media
        manifest={'schemaVersion':2,'mediaType':'application/vnd.oci.image.manifest.v1+json','artifactType':media,'subject':{'digest':candidate['manifest_digest'],'size':len(image)},'config':empty,'layers':[layer]}
        descriptor=desc(manifest,'manifests');descriptor['artifactType']=media
        class Fake:
            def __init__(self,rows,headers=None):self.rows=rows;self.headers=headers or {}
            def get(self,path,absent=False):
                if absent:return None,{}
                if path.startswith('referrers/'):
                    return raw({'schemaVersion':2,'mediaType':'application/vnd.oci.image.index.v1+json','manifests':self.rows}),self.headers
                return store[path],{}
        with mock.patch.object(n.r,'C',candidate):
            self.assertEqual(n.r.discover(Fake([descriptor]))[0][0],'signature')
            for registry in (Fake([descriptor,descriptor]),Fake([descriptor],{'Link':'</next>; rel="next"'}),Fake([{**descriptor,'artifactType':'application/unknown'}])):
                with self.assertRaises(ValueError):n.r.discover(registry)
            # A real parse of an unknown predicate, not an exception mock.
            statement['predicateType']='https://unknown.invalid/type'
            bundle['dsseEnvelope']['payload']=base64.b64encode(raw(statement)).decode()
            layer=desc(bundle);layer['mediaType']=media;manifest['layers']=[layer]
            descriptor=desc(manifest,'manifests');descriptor['artifactType']=media
            with self.assertRaises(ValueError):n.r.discover(Fake([descriptor]))

    def test_commands_keep_all_verification_controls(self):
        envelope={'payloadType':'application/vnd.in-toto+json','payload':base64.b64encode(json.dumps({'_type':'https://in-toto.io/Statement/v1','predicateType':n.b.IMAGE_SIGNATURE,'subject':[{'digest':{'sha256':n.C['manifest_digest'][7:]},'annotations':{n.b.REPOSITORY_ANNOTATION:policy()['destination']}}],'predicate':{}}).encode()).decode()}
        entry=('signature','sha256:'+'f'*64,b'fixture',envelope)
        with tempfile.TemporaryDirectory() as d,mock.patch.object(n.r,'discover',return_value=[entry]),mock.patch.object(n.b,'invoke',return_value='') as invoke:
            state=n.authenticated_inventory(object(),policy(),Path('/cosign'),Path('/root'),Path(d))
            self.assertEqual(set(state),{'signature'})
            cmd=invoke.call_args.args[0]
            for flag in ('--check-claims=true','--insecure-ignore-tlog=false','--insecure-ignore-sct=false','--certificate-github-workflow-sha','--certificate-identity','--trusted-root'):
                self.assertIn(flag,cmd)
            self.assertIn(n.IDENTITY,cmd);self.assertNotIn(n.b.PROMOTION_IDENTITY,cmd)
            with mock.patch.object(n.r,'discover',return_value=[entry,entry]):
                with self.assertRaises(ValueError):n.authenticated_inventory(object(),policy(),Path('/cosign'),Path('/root'),Path(d))

    def test_workflow_permissions_cleanup_and_exact_copy(self):
        w=json.loads((HERE.parents[1]/'.github/workflows/trustforge-native-promote.yml').read_text())
        self.assertEqual(set(w['on']),{'workflow_dispatch'})
        for job in w['jobs'].values():
            for step in job['steps']:
                if 'run' in step:
                    subprocess.run(['bash','-n'],input=step['run'],text=True,capture_output=True,check=True)
        self.assertEqual(w['jobs']['publish']['environment'],'trustforge-bootstrap-publish')
        for job in w['jobs'].values():self.assertNotIn('packages',job['permissions'])
        self.assertNotIn('id-token',w['jobs']['validate']['permissions'])
        self.assertEqual(w['jobs']['publish']['permissions']['id-token'],'write')
        command=next(x['run'] for x in w['jobs']['publish']['steps'] if 'env' in x)
        for text in ('--preserve-digests','DOCKER_CONFIG','trap', 'fresh-namespace','pre-sign','promote-native.py evidence','unset REGISTRY_PASSWORD'):
            self.assertIn(text,command)
        self.assertLess(command.index('fresh-namespace'),command.index('skopeo copy'))
        self.assertNotIn('docker://ghcr.io/',command)
        self.assertFalse(json.loads((HERE/'native-policy.example.json').read_text())['approved'])


if __name__=='__main__':unittest.main()
