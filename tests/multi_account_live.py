"""Live multi-account regression; touches only uniquely named disposable fixtures.
Results omit authentication secrets. Credentials/state stay in a local temp file.
"""
import json, os, secrets, tempfile, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, timezone

BASE = 'http://localhost:8081/api/v1'
OUT = Path(__file__).resolve().parents[1] / 'artifacts/multi-account'
OUT.mkdir(parents=True, exist_ok=True)
STATE = Path(tempfile.gettempdir()) / 'weknora-multi-account-state.json'
results = []
def call(name, method, path, actor=None, body=None, expected=(200,), headers=None):
    h = {'Content-Type':'application/json'}
    if actor: h['Authorization'] = 'Bearer ' + actor['token']
    h.update(headers or {})
    req = urllib.request.Request(BASE+path, data=json.dumps(body).encode() if body is not None else None, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r: status, raw = r.status, r.read()
    except urllib.error.HTTPError as e: status, raw = e.code, e.read()
    try: data=json.loads(raw)
    except Exception: data={'raw':raw.decode(errors='replace')[:500]}
    passed = status in expected
    result={'name':name,'method':method,'path':path,'status':status,'expected':list(expected),'pass':passed}
    if status >= 400: result['response']=data
    results.append(result)
    print(('PASS' if passed else 'FAIL'), name, status, flush=True)
    (OUT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    return data
def check(name, ok, detail=None):
    results.append({'name':name,'pass':bool(ok),'detail':detail})
    print(('PASS' if ok else 'FAIL'),name,flush=True)
    (OUT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
def save(s): STATE.write_text(json.dumps(s),encoding='utf-8')

def setup():
    run='qa'+datetime.now(timezone.utc).strftime('%m%d%H%M%S')
    s={'run':run,'users':{},'tenants':[]}
    save(s)
    for label in ('owner','member','outsider'):
        email=f'{run}.{label}@example.invalid'; password=secrets.token_urlsafe(24)
        reg=call('register '+label,'POST','/auth/register',body={'username':run+'_'+label,'email':email,'password':password},expected=(201,))
        login=call('login '+label,'POST','/auth/login',body={'email':email,'password':password})
        u={'email':email,'password':password,'id':reg['user']['id'],**login}
        s['users'][label]=u
        if login.get('active_tenant'): s['tenants'].append(login['active_tenant']['id'])
        save(s)
    a,b,c=[s['users'][x] for x in ('owner','member','outsider')]
    t=call('create workspace','POST','/tenants',a,{'name':run+'_shared','description':'Disposable multi-account QA','storage_quota':99999999999999,'status':'disabled'},(200,201))['data']
    s['workspace']=t['id'];s['tenants'].append(t['id']);save(s)
    check('self-service rejects privileged quota/status injection',t['status']=='active' and t['storage_quota']!=99999999999999)
    a.update(call('switch owner workspace','POST','/auth/switch-tenant',a,{'tenant_id':t['id']}));save(s)
    print('Fixture state saved to temp; no secrets in results.')

def exercise():
    global results
    results=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
    s=json.loads(STATE.read_text()); a,b,c=[s['users'][x] for x in ('owner','member','outsider')]
    tid=s['workspace']; p=f'/tenants/{tid}'
    call('anonymous member roster denied','GET',p+'/members',expected=(401,))
    for suffix in ('','/members','/invitations','/api-keys','/audit-log'):
        call('outsider denied '+suffix,'GET',p+suffix,c,expected=(403,404))
    call('outsider switch denied','POST','/auth/switch-tenant',c,{'tenant_id':tid},(403,))
    call('forged tenant header denied','GET',p+'/members',c,expected=(403,),headers={'X-Tenant-ID':str(tid)})
    call('ordinary user platform admin denied','GET','/system/admin/list',a,expected=(403,))
    call('ordinary user global tenant list denied','GET','/tenants/all',a,expected=(403,))
    for method,path,body in [('POST',p+'/leave',{}),('DELETE',p+'/members/'+a['id'],None),('PUT',p+'/members/'+a['id'],{'role':'viewer'})]:
        call('last owner protection '+method,method,path,a,body,(409,))
    inv=call('invite member viewer','POST',p+'/invitations',a,{'email':b['email'],'role':'viewer'},(201,))['data']; iid=inv['id']
    call('duplicate invitation','POST',p+'/invitations',a,{'email':b['email'],'role':'viewer'},(409,))
    inbox=call('invitee inbox','GET','/me/invitations',b)
    check('invitee sees invitation',str(iid) in json.dumps(inbox))
    call('other user cannot accept invite','POST',f'/me/invitations/{iid}/accept',c,{},(403,404))
    call('invitee cannot access before accept','POST','/auth/switch-tenant',b,{'tenant_id':tid},(403,))
    call('accept invitation','POST',f'/me/invitations/{iid}/accept',b,{})
    call('accepted invite replay rejected','POST',f'/me/invitations/{iid}/accept',b,{},(400,409,410))
    b.update(call('switch member into shared workspace','POST','/auth/switch-tenant',b,{'tenant_id':tid}));save(s)
    call('viewer reads members','GET',p+'/members',b)
    call('viewer reads settings','GET',p,b)
    for name,method,path,body in [
        ('self promote','PUT',p+'/members/'+b['id'],{'role':'owner'}),
        ('add member','POST',p+'/members',{'email':c['email'],'role':'owner'}),
        ('invite member','POST',p+'/invitations',{'email':c['email'],'role':'viewer'}),
        ('invite link','POST',p+'/invite-links',{'role':'owner'}),
        ('change workspace','PUT',p,{'name':s['run']+'_hacked'}),
        ('create KB','POST','/knowledge-bases',{'name':s['run']+'_denied'}),
        ('list keys','GET',p+'/api-keys',None),('read audit','GET',p+'/audit-log',None)]:
        call('viewer denied '+name,method,path,b,body,(403,))
    kb=call('owner create KB','POST','/knowledge-bases',a,{'name':s['run']+'_private_kb','type':'document'},(201,)).get('data')
    if kb:
        s['kb']=kb['id'];save(s); k='/knowledge-bases/'+kb['id']
        call('member reads KB','GET',k,b)
        call('outsider cannot read KB','GET',k,c,expected=(403,404))
        call('outsider cannot mutate KB','PUT',k,c,{'name':'denied'},(403,404))
        call('outsider cannot delete KB','DELETE',k,c,expected=(403,404))
        listing=call('outsider KB list','GET','/knowledge-bases',c)
        check('outsider list excludes private KB',kb['id'] not in json.dumps(listing))
    call('promote to contributor','PUT',p+'/members/'+b['id'],a,{'role':'contributor'})
    if kb: call('contributor cannot change colleague KB','PUT',k,b,{'name':'denied'},(403,))
    bkb=call('contributor creates own KB with existing token','POST','/knowledge-bases',b,{'name':s['run']+'_member_kb','type':'document'},(201,)).get('data')
    if bkb:
        s['member_kb']=bkb['id'];save(s)
        call('contributor updates own KB','PUT','/knowledge-bases/'+bkb['id'],b,{'name':s['run']+'_member_kb_updated'})
    call('promote to admin','PUT',p+'/members/'+b['id'],a,{'role':'admin'})
    call('admin cannot manage members','POST',p+'/members',b,{'email':c['email'],'role':'viewer'},(403,))
    call('admin reads audit','GET',p+'/audit-log',b)
    if kb: call('admin updates colleague KB','PUT',k,b,{'name':s['run']+'_admin_updated'})
    call('demote to viewer','PUT',p+'/members/'+b['id'],a,{'role':'viewer'})
    call('demotion effective on existing token','POST','/knowledge-bases',b,{'name':'denied'},(403,))
    call('remove member','DELETE',p+'/members/'+b['id'],a)
    call('removed member stale token denied','GET',p+'/members',b,expected=(401,403))
    call('removed member cannot switch back','POST','/auth/switch-tenant',b,{'tenant_id':tid},(401,403))
    if kb: call('removed member stale token cannot read KB','GET',k,b,expected=(401,403))
    b.update(call('removed member can login home','POST','/auth/login',body={'email':b['email'],'password':b['password']}));save(s)
    call('direct add member','POST',p+'/members',a,{'email':b['email'],'role':'contributor'},(200,201))
    b.update(call('re-added member switch','POST','/auth/switch-tenant',b,{'tenant_id':tid}));save(s)
    call('member leaves workspace','POST',p+'/leave',b,{})
    call('departed member token denied','GET',p+'/members',b,expected=(401,403))
    b.update(call('departed member login home','POST','/auth/login',body={'email':b['email'],'password':b['password']}));save(s)
    inv=call('create decline invitation','POST',p+'/invitations',a,{'email':b['email'],'role':'viewer'},(201,))['data']
    call('decline invitation','POST',f"/me/invitations/{inv['id']}/decline",b,{})
    call('declined invite cannot accept','POST',f"/me/invitations/{inv['id']}/accept",b,{},(400,409,410))
    inv=call('create revoke invitation','POST',p+'/invitations',a,{'email':b['email'],'role':'viewer'},(201,))['data']
    call('owner revoke invitation','DELETE',p+'/invitations/'+str(inv['id']),a)
    call('revoked invite cannot accept','POST',f"/me/invitations/{inv['id']}/accept",b,{},(400,409,410))
    save(s)

def extended():
    global results
    from urllib.parse import urlparse,parse_qs
    results=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
    s=json.loads(STATE.read_text());a,b,c=[s['users'][x] for x in ('owner','member','outsider')];tid=s['workspace'];p=f'/tenants/{tid}'
    link=call('create share invitation link','POST',p+'/invite-links',a,{'role':'viewer'},(201,))['data']
    token=parse_qs(urlparse(link['invite_url']).query)['token'][0]
    call('public link lookup','POST','/auth/invitations/lookup',body={'token':token})
    email=s['run']+'.invited@example.invalid'; password=secrets.token_urlsafe(24)
    reg=call('register through invitation','POST','/auth/register-by-invite',body={'token':token,'email':email,'username':s['run']+'_invited','password':password},expected=(200,201))
    d=call('invited account login','POST','/auth/login',body={'email':email,'password':password})
    d.update({'email':email,'password':password,'id':d['user']['id']});s['users']['invited']=d;save(s)
    check('invite registration joins correct workspace as viewer',d['active_tenant']['id']==tid and any(m['tenant_id']==tid and m['role']=='viewer' for m in d['memberships']))
    view=call('viewer list invitations hides bearer links','GET',p+'/invitations',d)
    check('invite token not disclosed to viewer',token not in json.dumps(view))
    call('revoke share link','DELETE',p+'/invitations/'+str(link['id']),a)
    call('revoked share link lookup denied','POST','/auth/invitations/lookup',body={'token':token},expected=(410,))
    call('revoked link registration denied','POST','/auth/register-by-invite',body={'token':token,'email':s['run']+'.rejected@example.invalid','username':'rejected','password':password},expected=(410,))
    session=call('create private chat','POST','/sessions',a,{'title':s['run']+'_private_chat'},(201,))['data'];s['session']=session['id'];save(s)
    for user,label in [(d,'same workspace viewer'),(c,'other workspace owner')]:
        for method,body in [('GET',None),('PUT',{'title':'denied'}),('DELETE',None)]:
            call(label+' cannot access private chat '+method,method,'/sessions/'+session['id'],user,body,(403,404))
        listing=call(label+' list chats','GET','/sessions',user)
        check(label+' list hides private chat',session['id'] not in json.dumps(listing))
    key=call('create restricted API key','POST',p+'/api-keys',a,{'name':s['run']+'_key','full_access':False,'knowledge_base_ids':[s['kb']],'capabilities':['retrieve']},(201,))['data']
    h={'X-API-Key':key['token']}
    call('scoped key reads allowed KB','GET','/knowledge-bases/'+s['kb'],headers=h)
    call('scoped key denied other KB','GET','/knowledge-bases/'+s['member_kb'],headers=h,expected=(403,))
    call('scoped key denied member management','GET',p+'/members',headers=h,expected=(403,))
    call('revoke API key','DELETE',p+'/api-keys/'+str(key['id']),a)
    call('revoked API key denied immediately','GET','/knowledge-bases/'+s['kb'],headers=h,expected=(401,))
    org=call('create shared organization','POST','/organizations',a,{'name':s['run']+'_org'},(200,201))['data'];s['org']=org['id'];save(s);op='/organizations/'+org['id']
    call('outsider cannot see organization members','GET',op+'/members',c,expected=(403,404))
    call('disable join approval for test organization','PUT',op,a,{'require_approval':False})
    call('join organization by code','POST','/organizations/join',c,{'invite_code':org['invite_code']},(200,201))
    call('organization viewer cannot change settings','PUT',op,c,{'name':'denied'},(403,))
    share=call('share KB read-only','POST','/knowledge-bases/'+s['kb']+'/shares',a,{'organization_id':org['id'],'permission':'viewer'},(200,201))['data']
    call('shared KB now readable across workspaces','GET','/knowledge-bases/'+s['kb'],c)
    call('read-only share cannot write KB','PUT','/knowledge-bases/'+s['kb'],c,{'name':'denied'},(403,))
    call('remove organization member','DELETE',op+'/members/'+str(c['active_tenant']['id']),a)
    call('removed org member loses KB access','GET','/knowledge-bases/'+s['kb'],c,expected=(403,404))
    call('remove KB share','DELETE','/knowledge-bases/'+s['kb']+'/shares/'+share['id'],a)
    call('logout outsider','POST','/auth/logout',c,{})
    call('logged out access token denied','GET','/auth/me',c,expected=(401,))
    call('logged out refresh token denied','POST','/auth/refresh',body={'refreshToken':c['refresh_token']},expected=(401,))
    save(s)

def finish():
    global results
    results=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
    s=json.loads(STATE.read_text()); a,b,c=[s['users'][x] for x in ('owner','member','outsider')]; tid=s['workspace'];p=f'/tenants/{tid}'
    for u in (a,b,c):
        u.update(call('relogin for final validation','POST','/auth/login',body={'email':u['email'],'password':u['password']}))
    for u in (a,b):u.update(call('switch for ownership transfer','POST','/auth/switch-tenant',u,{'tenant_id':tid}))
    call('add second owner','PUT',p+'/members/'+b['id'],a,{'role':'owner'})
    call('original owner can demote when another exists','PUT',p+'/members/'+a['id'],a,{'role':'viewer'})
    call('old owner loses member management immediately','PUT',p+'/members/'+a['id'],a,{'role':'owner'},(403,))
    call('new owner can restore original owner','PUT',p+'/members/'+a['id'],b,{'role':'owner'})
    call('restore member contributor','PUT',p+'/members/'+b['id'],a,{'role':'contributor'})
    r=call('refresh token works before logout','POST','/auth/refresh',body={'refreshToken':c['refresh_token']})
    call('rotated refresh token replay denied','POST','/auth/refresh',body={'refreshToken':c['refresh_token']},expected=(401,))
    c.update(r);save(s)
    op='/organizations/'+s['org']
    call('enable organization join approval','PUT',op,a,{'require_approval':True})
    org=call('read test organization','GET',op,a)['data']
    call('submit organization join request','POST','/organizations/join-request',c,{'invite_code':org['invite_code'],'role':'editor'},(200,201))
    call('pending org applicant cannot read members','GET',op+'/members',c,expected=(403,404))
    reqs=call('owner sees join requests','GET',op+'/join-requests',a)['data']['requests']
    call('approve organization join request','PUT',op+'/join-requests/'+reqs[0]['id']+'/review',a,{'approved':True,'role':'viewer'})
    call('approved organization member reads roster','GET',op+'/members',c)
    call('organization member leaves','POST',op+'/leave',c,{})
    call('left organization access denied','GET',op+'/members',c,expected=(403,404))
    # Delete via public API, using only IDs saved from this run's creations.
    call('delete test chat','DELETE','/sessions/'+s['session'],a)
    for field in ('kb','member_kb'):call('delete test '+field,'DELETE','/knowledge-bases/'+s[field],a)
    call('delete test organization','DELETE',op,a)
    call('delete test shared workspace','DELETE',p,a)
    call('deleted workspace rejects old token','GET',p+'/members',a,expected=(401,403,404))
    for label in ('owner','member','outsider'):
        u=s['users'][label]
        u.update(call('login after shared workspace deletion '+label,'POST','/auth/login',body={'email':u['email'],'password':u['password']}))
        home=u['active_tenant']['id']
        assert home in s['tenants'] and home!=tid
        call('delete disposable home '+label,'DELETE',f'/tenants/{home}',u)
    save(s)

if __name__=='__main__':
    import sys
    finish() if '--finish' in sys.argv else extended() if '--extended' in sys.argv else exercise() if '--exercise' in sys.argv else setup()
