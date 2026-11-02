#!/usr/bin/env python3
"""Evidence-only recovery. Strict OCI 1.1 discovery; never push an image."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

import importlib.util
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('candidate_promotion', HERE/'promote-candidate.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
b = p.bootstrap
C = p.CANDIDATE
require = b.require
WORKFLOW = 'jnbntc/distrobox-stack/.github/workflows/trustforge-recover.yml@refs/heads/main'
IDENTITY = 'https://github.com/' + WORKFLOW
ROOT = '6494e21ea73fa7ee769f85f57d5a3e6a08725eae1e38c755fc3517c9e6bc0b66'
PREVIOUS = 'e9b7b7b393f34b4027a0910ea58981b3e378f9e1'
IMAGE = b.REPOSITORY + '@' + C['manifest_digest']
TYPES = {'signature': b.IMAGE_SIGNATURE, 'spdx': b.SPDX, 'provenance': b.PROVENANCE}
MEDIA = {'application/vnd.dev.sigstore.bundle.v0.3+json', 'application/vnd.dev.sigstore.bundle+json;version=0.3'}
CONTRACT = b.strict_json((HERE/'contract.json').read_text())


def policy_hash(policy):
    return hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def confirmation(policy):
    return p.confirmation().replace('PROMOTE ', 'RECOVER ', 1) + ' policy=sha256:' + policy_hash(policy)


def check_policy(policy):
    template = b.strict_json((HERE/'recovery-policy.example.json').read_text())
    require(set(policy) == set(template), 'unexpected policy fields')
    for key in set(template) - {'approved', 'signer_commit', 'trusted_root_sha256'}:
        require(type(policy[key]) is type(template[key]) and policy[key] == template[key], 'wrong recovery policy')
    require(policy['approved'] is True, 'explicit approval required')
    require(isinstance(policy['signer_commit'], str) and b.COMMIT.fullmatch(policy['signer_commit']), 'unapproved signer')
    require(policy['trusted_root_sha256'] == ROOT, 'unapproved root')


def context(env):
    require(env.get('GITHUB_REPOSITORY') == C['repository'] and env.get('GITHUB_REF') == 'refs/heads/main', 'wrong recovery repository/ref')
    require(env.get('GITHUB_WORKFLOW_REF') == WORKFLOW and env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch', 'wrong recovery workflow')
    sha = env.get('GITHUB_SHA', '')
    require(b.COMMIT.fullmatch(sha) and env.get('GITHUB_WORKFLOW_SHA') == sha, 'wrong signer revision')
    require(env.get('GITHUB_RUN_ATTEMPT') == '1' and re.fullmatch(r'[1-9][0-9]*', env.get('GITHUB_RUN_ID', '')), 'rerun/invalid invocation')
    require(env['GITHUB_RUN_ID'] not in (str(C['run_id']), '41380381655'), 'recovery must be a new run')
    policy = b.strict_json((HERE/'recovery-policy.example.json').read_text())
    policy.update(approved=True, signer_commit=sha, trusted_root_sha256=ROOT)
    check_policy(policy)
    # The operator must first approve an external policy with this canonical hash.
    require(env.get('TF_POLICY_SHA256') == policy_hash(policy), 'external approved policy hash required')
    require(env.get('TF_RECOVERY_CONFIRMATION') == confirmation(policy), 'exact recovery confirmation required')
    return policy


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Registry:
    """Bounded GET-only client. No write method, no insecure TLS or auth redirects."""
    def __init__(self):
        config = b.strict_json((Path(os.environ['DOCKER_CONFIG'])/'config.json').read_text())
        auth = config['auths']['ghcr.io']['auth']
        raw, _ = self.http('https://ghcr.io/token?service=ghcr.io&scope=repository:jnbntc/trustforge-dev:pull', 'Basic '+auth)
        token = b.strict_json(raw.decode()).get('token')
        require(isinstance(token, str) and token, 'registry authentication failed')
        self.token = token

    @staticmethod
    def http(url, auth=None, blob=False):
        headers = {'Accept': 'application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json'}
        if auth: headers['Authorization'] = auth
        opener = urllib.request.build_opener(NoRedirect)
        for _ in range(4):
            try:
                with opener.open(urllib.request.Request(url, headers=headers), timeout=90) as reply:
                    raw = reply.read(64*1024*1024+1)
                    require(len(raw) <= 64*1024*1024 and reply.status == 200, 'oversized/invalid registry response')
                    return raw, reply.headers
            except urllib.error.HTTPError as error:
                if blob and error.code in (301, 302, 307, 308):
                    url = error.headers['Location']; parsed = urllib.parse.urlparse(url)
                    require(parsed.scheme == 'https' and parsed.hostname and
                            (parsed.hostname.endswith('.githubusercontent.com') or parsed.hostname.endswith('.blob.core.windows.net')), 'untrusted blob redirect')
                    headers.pop('Authorization', None)
                    continue
                raise
        raise b.VerificationError('registry redirect limit')

    def get(self, suffix, absent=False):
        try:
            return self.http('https://ghcr.io/v2/jnbntc/trustforge-dev/'+suffix, 'Bearer '+self.token, suffix.startswith('blobs/'))
        except urllib.error.HTTPError as error:
            # Only an authenticated legacy-tag MANIFEST_UNKNOWN is absence.
            if absent and error.code == 404:
                obj = b.strict_json(error.read(4096).decode())
                require(obj.get('errors') and all(e.get('code') == 'MANIFEST_UNKNOWN' for e in obj['errors']), 'ambiguous 404')
                return None, {}
            raise b.VerificationError('registry GET failed: '+str(error.code)) from None


def blob(registry, descriptor, kind):
    value = descriptor['digest']
    require(re.fullmatch(r'sha256:[0-9a-f]{64}', value), 'invalid blob digest')
    raw, _ = registry.get(kind+'/'+value)
    require(len(raw) == descriptor['size'] and 'sha256:'+hashlib.sha256(raw).hexdigest() == value, 'blob digest/length mismatch')
    return raw


def discover(registry):
    raw, _ = registry.get('manifests/'+C['manifest_digest'])
    require('sha256:'+hashlib.sha256(raw).hexdigest() == C['manifest_digest'], 'existing image digest mismatch')
    image = b.strict_json(raw.decode())
    require(image['config']['digest'] == C['config_digest'], 'image config mismatch')
    config = b.strict_json(blob(registry,image['config'],'blobs').decode())
    require(config.get('os') == 'linux' and config.get('architecture') == 'amd64', 'image platform mismatch')
    digest = C['manifest_digest'].replace(':', '-')
    for tag in (digest, digest+'.sig', digest+'.att'):
        legacy, _ = registry.get('manifests/'+tag, absent=True)
        require(legacy is None, 'legacy/fallback evidence requires separate review')
    raw_index, headers = registry.get('referrers/'+C['manifest_digest'])
    require(not headers.get('Link'), 'incomplete paginated inventory')
    index = b.strict_json(raw_index.decode())
    require(index.get('schemaVersion') == 2 and index.get('mediaType') == 'application/vnd.oci.image.index.v1+json', 'unsupported referrers API')
    descriptors = index.get('manifests')
    require(isinstance(descriptors, list) and len(descriptors) <= 3, 'ambiguous evidence count')
    seen, result = set(), []
    for desc in descriptors:
        require(desc['digest'] not in seen, 'duplicate referrer'); seen.add(desc['digest'])
        manifest = b.strict_json(blob(registry, desc, 'manifests').decode())
        require(desc.get('artifactType') in MEDIA and manifest.get('artifactType') == desc['artifactType'], 'unsupported evidence format')
        require(manifest.get('schemaVersion') == 2 and manifest.get('mediaType') == 'application/vnd.oci.image.manifest.v1+json', 'unexpected referrer manifest')
        require(manifest.get('subject', {}).get('digest') == C['manifest_digest'] and manifest['subject'].get('size') == len(raw), 'referrer subject mismatch')
        require(manifest['config'].get('mediaType') == 'application/vnd.oci.empty.v1+json'
                and b.strict_json(blob(registry, manifest['config'], 'blobs').decode()) == {}, 'unsupported referrer config')
        require(len(manifest['layers']) == 1 and manifest['layers'][0]['mediaType'] in MEDIA, 'ambiguous evidence layers')
        bundle_raw = blob(registry, manifest['layers'][0], 'blobs')
        bundle = b.strict_json(bundle_raw.decode()); envelope = bundle.get('dsseEnvelope', {})
        require(bundle.get('mediaType') in MEDIA and envelope.get('payloadType') == 'application/vnd.in-toto+json'
                and len(envelope.get('signatures', [])) == 1, 'unsupported bundle')
        statement = b.strict_json(base64.b64decode(envelope['payload'], validate=True).decode())
        role = next((k for k,v in TYPES.items() if v == statement.get('predicateType')), None)
        require(role is not None, 'unknown predicate; never interpret as missing')
        # Unauthenticated parsing only routes verification; it grants no trust.
        result.append((role, desc['digest'], bundle_raw, envelope))
    return result


def verify_bundle(binary, root, policy, bundle_path, role, runner=subprocess.run):
    for identity, sha in ((b.PROMOTION_IDENTITY, PREVIOUS), (IDENTITY, policy['signer_commit'])):
        command = [str(binary), 'verify-blob-attestation', '--bundle', str(bundle_path), '--type', TYPES[role],
                   '--digest', C['manifest_digest'][7:], '--digestAlg', 'sha256', '--check-claims=true',
                   '--trusted-root', str(root), '--certificate-identity', identity, '--certificate-oidc-issuer', b.ISSUER,
                   '--certificate-github-workflow-repository', C['repository'], '--certificate-github-workflow-ref', 'refs/heads/main',
                   '--certificate-github-workflow-trigger', 'workflow_dispatch', '--certificate-github-workflow-sha', sha,
                   '--insecure-ignore-tlog=false', '--insecure-ignore-sct=false']
        env = {k:v for k,v in os.environ.items() if not k.startswith(('COSIGN_','SIGSTORE_','FULCIO_','REKOR_'))}
        result = runner(command, capture_output=True, text=True, timeout=180, env=env)
        if result.returncode == 0: return identity, sha
    raise b.VerificationError('existing evidence is not authenticated; no replacement allowed')


def claims(envelope, role, signer, policy):
    statement = b.verified_statements(json.dumps(envelope), IMAGE, TYPES[role])
    require(len(statement) == 1, 'ambiguous statement')
    value = statement[0]['predicate']
    if role == 'spdx':
        require(value.get('spdxVersion') == 'SPDX-2.3' and value.get('SPDXID') == 'SPDXRef-DOCUMENT'
                and isinstance(value.get('documentNamespace'), str) and value['documentNamespace'], 'invalid SPDX')
        require(isinstance(value.get('packages'), list) and value['packages']
                and all(isinstance(x, dict) and isinstance(x.get('name'), str) and x['name'] for x in value['packages']), 'invalid SPDX packages')
    if role == 'provenance':
        require(type(value.get('schema_version')) is int and value['schema_version'] == 1, 'invalid provenance schema')
        keys = ('schema_version', 'source', 'builder', 'parameters', 'materials', 'invocation')
        p.source_record({k:value[k] for k in keys}, CONTRACT)
        field = 'promotion' if signer[0] == b.PROMOTION_IDENTITY else 'recovery'
        require(set(value) == set(keys)|{'artifact', field} and value['artifact'] == IMAGE, 'unexpected provenance')
        info = value[field]
        require(set(info) == {'workflow','invocation','candidate'} and info['candidate'] == C, 'candidate provenance mismatch')
        workflow = b.PROMOTION_WORKFLOW if field == 'promotion' else WORKFLOW
        require(info['workflow'] == {'id':signer[0], 'workflow_ref':workflow, 'workflow_sha':signer[1], 'event':'workflow_dispatch'}, 'signer provenance mismatch')
        invocation = info['invocation']
        require(set(invocation) == {'run_id','attempt'} and isinstance(invocation['run_id'],str)
                and re.fullmatch(r'[1-9][0-9]*', invocation['run_id']) and invocation['attempt'] == '1', 'invalid recovery invocation')
        if field == 'recovery':
            require(invocation['run_id'] not in (str(C['run_id']), '41380381655'), 'old run cannot be recovery')


def inventory(registry, binary, root, policy, directory, verifier=verify_bundle):
    result = {}
    for role, value, raw, envelope in discover(registry):
        require(role not in result, 'duplicate evidence type')
        path = directory/(value[7:]+'.bundle.json'); path.write_bytes(raw)
        signer = verifier(binary, root, policy, path, role)
        claims(envelope, role, signer, policy)
        result[role] = value
    return result


def recover(scan, create):
    """Only a successful complete scan may classify a role as absent."""
    state = scan()
    for role in TYPES:
        if role in state: continue
        require(scan() == state, 'concurrent evidence change')
        create(role)
        after = scan()
        require(set(after) == set(state)|{role} and all(after[k] == v for k,v in state.items()), 'unexpected post-sign inventory')
        state = after
    require(set(state) == set(TYPES) and scan() == state, 'incomplete or changed final evidence')
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('confirmation','policy-hash','origin','candidate','prepare','recover','verify'))
    parser.add_argument('--policy', type=Path, default=Path('recovery-private/policy.json'))
    parser.add_argument('--root', type=Path, default=Path('recovery-private/trusted-root.json'))
    parser.add_argument('--cosign', type=Path)
    args = parser.parse_args(); os.umask(0o077)
    try:
        if args.mode in ('confirmation','policy-hash'):
            policy = b.strict_json(args.policy.read_text()); check_policy(policy)
            print(confirmation(policy) if args.mode == 'confirmation' else policy_hash(policy))
            return 0
        if args.mode in ('origin','candidate','prepare'):
            policy = context(os.environ)
            if args.mode == 'origin':
                p.origin(*(b.strict_json((Path('promotion-input')/n).read_text()) for n in ('source-run.json','source-artifact.json','source-jobs.json')))
            elif args.mode == 'candidate':
                p.validate(Path('promotion-input'),Path('candidate'),CONTRACT)
            else:
                args.policy.parent.mkdir(mode=0o700)
                args.policy.write_text(json.dumps(policy,indent=2)+'\n')
                raw,_ = Registry.http('https://tuf-repo-cdn.sigstore.dev/targets/'+ROOT+'.trusted_root.json')
                require(hashlib.sha256(raw).hexdigest() == ROOT, 'approved root bytes unavailable')
                args.root.write_bytes(raw)
            return 0
        policy = b.strict_json(args.policy.read_text()); check_policy(policy)
        require(hashlib.sha256(args.root.read_bytes()).hexdigest() == ROOT, 'root mismatch')
        require(args.cosign and args.cosign.is_absolute() and p.digest(args.cosign) == CONTRACT['bootstrap']['cosign']['sha256'], 'unapproved Cosign')
        if args.mode == 'recover': require(context(os.environ) == policy, 'runtime policy mismatch')
        directory = Path('recovery-evidence'); directory.mkdir(mode=0o700,exist_ok=True)
        registry = Registry()
        scan = lambda: inventory(registry,args.cosign,args.root,policy,directory)
        def create(role):
            env = {k:v for k,v in os.environ.items() if not k.startswith(('COSIGN_','SIGSTORE_','FULCIO_','REKOR_'))}
            if role == 'signature': command = [str(args.cosign),'sign','--yes','--new-bundle-format=true','-a',b.REPOSITORY_ANNOTATION+'='+b.REPOSITORY,IMAGE]
            else:
                path = directory/(role+'.json')
                if role == 'spdx': subprocess.run(['syft','scan','oci-archive:candidate/trustforge-dev.oci.tar','-o','spdx-json='+str(path)],check=True,env=env,timeout=300)
                else:
                    record=b.strict_json(Path('candidate/workspace.build.json').read_text());p.source_record(record,CONTRACT)
                    record.update(artifact=IMAGE,recovery={'workflow':{'id':IDENTITY,'workflow_ref':WORKFLOW,'workflow_sha':policy['signer_commit'],'event':'workflow_dispatch'},'invocation':{'run_id':os.environ['GITHUB_RUN_ID'],'attempt':'1'},'candidate':C})
                    path.write_text(json.dumps(record,sort_keys=True)+'\n')
                command=[str(args.cosign),'attest','--yes','--predicate',str(path),'--type',TYPES[role],IMAGE]
            subprocess.run(command,check=True,env=env,timeout=300)
        result = recover(scan,create) if args.mode == 'recover' else scan()
        require(set(result) == set(TYPES), 'missing evidence; not VERIFIED')
        report={'verification':'VERIFIED','image':IMAGE,'evidence':result,'source_commit':C['source_commit'],'signer_commit':policy['signer_commit'],'policy_sha256':policy_hash(policy),'trusted_root_sha256':ROOT,'deployment_authorized':False}
        (directory/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
    except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError, subprocess.SubprocessError) as error:
        report={'verification':'DENY','error_type':type(error).__name__,'deployment_authorized':False}
        if Path('recovery-evidence').is_dir():
            Path('recovery-evidence/result.json').write_text(json.dumps(report)+'\n')
        print(json.dumps(report),file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
