#!/usr/bin/env python3
"""OPT-IN real writes to synthetic repository on hard-coded loopback Zot only.
Run only after starting the documented ephemeral pinned Zot; never a real candidate.
"""
import urllib.request as u,urllib.error,json,hashlib,pathlib,subprocess
base='http://127.0.0.1:18583';repo='tf003-probe/candidate';mt='application/vnd.oci.image.manifest.v1+json';ix='application/vnd.oci.image.index.v1+json'
def req(path,data=None,method='GET',ctype=None):
 h={'Accept':ix+', '+mt}
 if ctype:h['Content-Type']=ctype
 with u.urlopen(u.Request(base+path,data=data,method=method,headers=h),timeout=10) as r:return r.status,r.read(),dict(r.headers)
def ser(x):return json.dumps(x,separators=(',',':')).encode()
def dg(raw):return 'sha256:'+hashlib.sha256(raw).hexdigest()
def blob(raw,media):
 _,_,h=req('/v2/'+repo+'/blobs/uploads/',b'','POST');loc=h['Location'];loc=loc.replace(base,'');req(loc+('&' if '?' in loc else '?')+'digest='+dg(raw),raw,'PUT','application/octet-stream');return {'mediaType':media,'digest':dg(raw),'size':len(raw)}
assert req('/v2/')[0]==200
cfg=blob(ser({'architecture':'amd64','os':'linux','config':{},'rootfs':{'type':'layers','diff_ids':[]}}),'application/vnd.oci.image.config.v1+json')
root=ser({'schemaVersion':2,'mediaType':mt,'config':cfg,'layers':[]});digest=dg(root)
req('/v2/'+repo+'/manifests/root',root,'PUT',mt)
subject={'mediaType':mt,'digest':digest,'size':len(root)}
status,raw,h=req('/v2/'+repo+'/referrers/'+digest);obj=json.loads(raw);assert status==200 and h['Content-Type']==ix and obj['manifests']==[]
empty={'status':status,'content_type':h['Content-Type'],'count':0}
refs=[]
for i in range(3):
 config=blob(b'{}','application/vnd.oci.empty.v1+json');layer=blob(ser({'test':i}),'application/test.tf003')
 m=ser({'schemaVersion':2,'mediaType':mt,'artifactType':'application/test.tf003','config':config,'layers':[layer],'subject':subject})
 req('/v2/'+repo+'/manifests/'+dg(m),m,'PUT',mt);refs.append(dg(m))
path='/v2/'+repo+'/referrers/'+digest+'?n=1';seen=[];pages=0
while path:
 pages+=1;assert pages<=4
 status,raw,h=req(path);obj=json.loads(raw);assert status==200 and h['Content-Type']==ix
 for d in obj['manifests']:
  assert d['artifactType']=='application/test.tf003' and d['digest'] not in seen
  _,m,_=req('/v2/'+repo+'/manifests/'+d['digest']);assert dg(m)==d['digest'];assert json.loads(m)['subject']==subject
  seen.append(d['digest'])
 link=h.get('Link');path=link.split('<')[1].split('>')[0] if link else None
 if path and path.startswith(base):path=path[len(base):]
assert set(seen)==set(refs)
client=subprocess.run(['skopeo','inspect','--raw','--tls-verify=false','docker://127.0.0.1:18583/'+repo+'@'+digest],capture_output=True,check=True);assert dg(client.stdout)==digest
result={'registry':'ghcr.io/project-zot/zot:v2.1.23','pinned_digest':'sha256:9d3de83ac2099e6f4843045b4c9b65b7e8baf40f92d28f54906dee9d4d390fd7','v2':'PASS','empty_referrers':empty,'subject_and_artifactType':'PASS','referrer_hashes':'PASS','unfiltered_count':len(seen),'pagination_pages':pages,'skopeo_read':'PASS','real_candidate_used':False,'cosign_tested':False}
pathlib.Path('/tmp/tf003-zot-probe').mkdir(mode=0o700,exist_ok=True)
pathlib.Path('/tmp/tf003-zot-probe/result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
