#!/usr/bin/env python3
"""Manual first promotion to an owner-approved, fresh, exclusively written Zot namespace.
No GHCR recovery, legacy fallback, rebuild, deployment, or automatic policy approval.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

import importlib.util
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('native_recovery_helpers', HERE/'recover-evidence.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
p, b, C = r.p, r.b, r.C
WORKFLOW = 'jnbntc/distrobox-stack/.github/workflows/trustforge-native-promote.yml@refs/heads/main'
IDENTITY = 'https://github.com/' + WORKFLOW
ZOT = 'ghcr.io/project-zot/zot@sha256:9d3de83ac2099e6f4843045b4c9b65b7e8baf40f92d28f54906dee9d4d390fd7'
require = b.require


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def destination(value):
    # One explicit TLS origin; no credentials, ports, query, IP/loopback or GHCR.
    require(isinstance(value, str) and re.fullmatch(r'[a-z0-9][a-z0-9.-]*\.[a-z]{2,}/[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*', value), 'invalid destination')
    require(value.split('/')[0] not in ('ghcr.io', 'localhost'), 'GHCR recovery forbidden')
    return value


def check_policy(policy):
    template = b.strict_json((HERE/'native-policy.example.json').read_text())
    require(set(policy) == set(template), 'unexpected native policy fields')
    for key in set(template)-{'approved', 'signer_commit', 'destination', 'namespace_approval'}:
        require(type(policy[key]) is type(template[key]) and policy[key] == template[key], 'native policy mismatch')
    require(policy['approved'] is True, 'explicit owner approval required')
    require(isinstance(policy['signer_commit'], str) and b.COMMIT.fullmatch(policy['signer_commit']), 'invalid signer commit')
    destination(policy['destination'])
    require(isinstance(policy['namespace_approval'], str) and re.fullmatch(r'[a-zA-Z0-9_-]{16,128}', policy['namespace_approval']), 'owner fresh-namespace/exclusive-writer approval required')


def confirmation(policy):
    return p.confirmation().replace('PROMOTE ', 'PROMOTE-NATIVE ', 1)+' destination='+policy['destination']+' policy=sha256:'+canonical(policy)


def context(env):
    require(env.get('GITHUB_REPOSITORY') == C['repository'] and env.get('GITHUB_REF') == 'refs/heads/main', 'wrong repository/ref')
    require(env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch' and env.get('GITHUB_WORKFLOW_REF') == WORKFLOW, 'wrong workflow/event')
    require(env.get('GITHUB_SHA') == env.get('GITHUB_WORKFLOW_SHA'), 'checkout/workflow mismatch')
    require(env.get('GITHUB_RUN_ATTEMPT') == '1' and re.fullmatch(r'[1-9][0-9]*', env.get('GITHUB_RUN_ID', '')), 'rerun forbidden')
    policy = b.strict_json((HERE/'native-policy.example.json').read_text())
    policy.update(approved=True, signer_commit=env.get('GITHUB_SHA'), destination=env.get('TF_DESTINATION'), namespace_approval=env.get('TF_NAMESPACE_APPROVAL'))
    check_policy(policy)
    # No approval file is created: the independently approved external policy's
    # canonical hash and full confirmation must match this exact invocation.
    require(env.get('TF_POLICY_SHA256') == canonical(policy), 'external policy approval hash required')
    require(env.get('TF_NATIVE_CONFIRMATION') == confirmation(policy), 'exact confirmation required')
    return policy


class Registry:
    """GET-only, bounded, same-origin TLS Basic auth. Redirects are rejected."""
    def __init__(self, policy):
        self.target = destination(policy['destination'])
        self.host, self.repository = self.target.split('/', 1)
        config = b.strict_json((Path(os.environ['DOCKER_CONFIG'])/'config.json').read_text())
        self.auth = config['auths'][self.host]['auth']
        self.opener = urllib.request.build_opener(r.NoRedirect)

    def fresh_namespace(self):
        # A complete catalog under the explicitly approved namespace-admin
        # account is an operational precondition, never a cryptographic proof.
        request = urllib.request.Request('https://'+self.host+'/v2/_catalog', headers={
            'Accept': 'application/json', 'Authorization': 'Basic '+self.auth})
        try:
            with self.opener.open(request, timeout=90) as reply:
                raw = reply.read(1024*1024+1)
                require(reply.status == 200 and len(raw) <= 1024*1024 and not reply.headers.get('Link'), 'catalog incomplete')
                obj = b.strict_json(raw.decode())
                rows = obj.get('repositories')
                require(isinstance(rows, list) and all(isinstance(x, str) for x in rows) and len(rows) == len(set(rows)), 'invalid catalog')
                require(self.repository not in rows, 'destination namespace already exists')
        except urllib.error.HTTPError as error:
            error.close()
            raise b.VerificationError('catalog HTTP failure') from None

    def get(self, suffix, absent=False):
        require(re.fullmatch(r'(?:manifests|blobs|referrers)/[a-zA-Z0-9:._-]+', suffix), 'invalid registry path')
        url = 'https://'+self.host+'/v2/'+self.repository+'/'+suffix
        headers = {'Accept': 'application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json', 'Authorization': 'Basic '+self.auth}
        try:
            with self.opener.open(urllib.request.Request(url, headers=headers), timeout=90) as response:
                raw = response.read(64*1024*1024+1)
                require(response.status == 200 and len(raw) <= 64*1024*1024, 'invalid registry response')
                if suffix.startswith('referrers/'):
                    require(response.headers.get('Content-Type') == 'application/vnd.oci.image.index.v1+json', 'invalid referrers content type')
                return raw, response.headers
        except urllib.error.HTTPError as error:
            try:
                if absent and error.code == 404:
                    obj = b.strict_json(error.read(4096).decode())
                    require(isinstance(obj.get('errors'), list) and obj['errors'] and all(x.get('code') == 'MANIFEST_UNKNOWN' for x in obj['errors']), 'ambiguous legacy absence')
                    return None, {}
                raise b.VerificationError('registry HTTP failure') from None
            finally:
                error.close()


def authenticated_inventory(registry, policy, binary, root, directory):
    """Unfiltered native inventory; unknown types, duplicates and ANY Link DENY.
    Maximum approved cardinality is three. Never truncate or accept a first page.
    Reuse strict digest/config/bundle validation, but never old GHCR signer trust.
    """
    check_policy(policy)
    target = policy['destination']
    # Helpers are loaded into a private module instance in this CLI process.
    b.REPOSITORY = target
    image = target+'@'+C['manifest_digest']
    result = {}
    for role, digest, raw, envelope in r.discover(registry):
        require(role not in result, 'duplicate evidence role')
        path = directory/(digest[7:]+'.bundle.json')
        path.write_bytes(raw)
        command = [str(binary), 'verify-blob-attestation', '--bundle', str(path), '--type', r.TYPES[role],
                   '--digest', C['manifest_digest'][7:], '--digestAlg', 'sha256', '--check-claims=true',
                   '--trusted-root', str(root), '--certificate-identity', IDENTITY,
                   '--certificate-oidc-issuer', b.ISSUER, '--certificate-github-workflow-repository', C['repository'],
                   '--certificate-github-workflow-ref', 'refs/heads/main', '--certificate-github-workflow-trigger', 'workflow_dispatch',
                   '--certificate-github-workflow-sha', policy['signer_commit'], '--insecure-ignore-tlog=false', '--insecure-ignore-sct=false']
        # Return-code verification precedes every DSSE claim parser.
        b.invoke(command)
        statements = b.verified_statements(json.dumps(envelope), image, r.TYPES[role])
        require(len(statements) == 1, 'ambiguous statement')
        predicate = statements[0]['predicate']
        if role == 'spdx':
            require(predicate.get('spdxVersion') == 'SPDX-2.3' and predicate.get('SPDXID') == 'SPDXRef-DOCUMENT'
                    and isinstance(predicate.get('documentNamespace'), str) and predicate['documentNamespace']
                    and isinstance(predicate.get('packages'), list) and predicate['packages']
                    and all(isinstance(x, dict) and isinstance(x.get('name'), str) and x['name'] for x in predicate['packages']), 'invalid SPDX')
        if role == 'provenance':
            keys = ('schema_version', 'source', 'builder', 'parameters', 'materials', 'invocation')
            # Original builder parameters remain GHCR: preserve historical truth.
            p.source_record({k: predicate[k] for k in keys}, r.CONTRACT)
            require(set(predicate) == set(keys)|{'artifact', 'native_promotion'} and predicate['artifact'] == image, 'invalid native provenance')
            native = predicate['native_promotion']
            require(set(native) == {'identity', 'signer_commit', 'candidate', 'destination', 'invocation'}, 'invalid promotion fields')
            require(native['identity'] == IDENTITY and native['signer_commit'] == policy['signer_commit'] and native['candidate'] == C
                    and native['destination'] == target, 'promotion provenance mismatch')
            invocation = native['invocation']
            require(set(invocation) == {'run_id', 'attempt'} and isinstance(invocation['run_id'], str)
                    and re.fullmatch(r'[1-9][0-9]*', invocation['run_id']) and invocation['attempt'] == '1', 'invalid promotion invocation')
        result[role] = digest
    return result


def tools(binary, root, policy):
    require(binary.is_absolute() and root.is_absolute(), 'explicit tool/root paths required')
    require(p.digest(binary) == r.CONTRACT['bootstrap']['cosign']['sha256'], 'Cosign hash mismatch')
    require(p.digest(root) == policy['trusted_root_sha256'], 'TrustedRoot hash mismatch')


def provenance(policy, record, env):
    p.source_record(record, r.CONTRACT)
    return {**record, 'artifact': policy['destination']+'@'+C['manifest_digest'], 'native_promotion': {
        'identity': IDENTITY, 'signer_commit': policy['signer_commit'], 'candidate': C,
        'destination': policy['destination'], 'invocation': {'run_id': env['GITHUB_RUN_ID'], 'attempt': '1'}}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('origin', 'validate', 'fresh-namespace', 'pre-sign', 'evidence', 'verify', 'provenance'))
    parser.add_argument('--policy', type=Path)
    parser.add_argument('--cosign', type=Path)
    parser.add_argument('--trusted-root', type=Path)
    parser.add_argument('--directory', type=Path, default=Path('promotion-input'))
    parser.add_argument('--output', type=Path, default=Path('candidate'))
    args = parser.parse_args()
    try:
        policy = b.strict_json(args.policy.read_text()) if args.policy else context(os.environ)
        check_policy(policy)
        require(args.mode == 'verify' or args.policy is None, 'external policy files are verification-only')
        if args.mode == 'origin':
            p.origin(*(b.strict_json((args.directory/n).read_text()) for n in ('source-run.json', 'source-artifact.json', 'source-jobs.json')))
            result = {'origin': 'PASS'}
        elif args.mode == 'validate':
            result = p.validate(args.directory, args.output, r.CONTRACT)
        elif args.mode == 'provenance':
            result = provenance(policy, b.strict_json((args.output/'workspace.build.json').read_text()), os.environ)
        elif args.mode == 'fresh-namespace':
            Registry(policy).fresh_namespace()
            result = {'namespace': 'ABSENT', 'owner_exclusive_writer_approval': policy['namespace_approval']}
        else:
            tools(args.cosign, args.trusted_root, policy)
            args.output.mkdir(mode=0o700, exist_ok=True)
            registry = Registry(policy)
            scan = lambda: authenticated_inventory(registry, policy, args.cosign, args.trusted_root, args.output)
            if args.mode == 'evidence':
                require(scan() == {}, 'first promotion requires empty authenticated native inventory')
                image = policy['destination']+'@'+C['manifest_digest']
                def create(role):
                    if role == 'signature':
                        command = [str(args.cosign), 'sign', '--yes', '--new-bundle-format=true', '-a', b.REPOSITORY_ANNOTATION+'='+policy['destination'], image]
                    else:
                        path = 'workspace.sbom.spdx.json' if role == 'spdx' else 'workspace.provenance.json'
                        kind = 'spdxjson' if role == 'spdx' else b.PROVENANCE
                        command = [str(args.cosign), 'attest', '--yes', '--predicate', path, '--type', kind, image]
                    b.invoke(command)
                r.recover(scan, create)
            state = scan()
            require(state == {} if args.mode == 'pre-sign' else set(state) == set(r.TYPES), 'unexpected or incomplete evidence inventory')
            result = {'verification': 'EMPTY' if args.mode == 'pre-sign' else 'VERIFIED', 'evidence': state, 'deployment_authorized': False}
        print(json.dumps(result, sort_keys=True))
    except r.CAUGHT:
        # Never emit downloaded bodies, certificates, signed URLs or credentials.
        print(json.dumps({'verification': 'DENY', 'error_code': 'NATIVE_PROMOTION_FAILED', 'deployment_authorized': False}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
