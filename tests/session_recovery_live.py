"""Disposable fixtures for browser validation of workspace session recovery."""
import json, sys, tempfile, subprocess, re
from pathlib import Path
import multi_account_live as q

q.OUT=Path(__file__).resolve().parents[1]/'artifacts/session-recovery'
q.OUT.mkdir(parents=True,exist_ok=True)
q.STATE=Path(tempfile.gettempdir())/'weknora-session-recovery-state.json'
action=sys.argv[1]
if action=='setup':
    q.setup()
s=json.loads(q.STATE.read_text())
q.results=json.loads((q.OUT/'results.json').read_text(encoding='utf-8'))
a=s['users']['owner'];b=s['users']['member'];p='/tenants/'+str(s['workspace'])
if action in ('setup','add'):
    q.call('add browser member','POST',p+'/members',a,{'email':b['email'],'role':'contributor'},(201,))
    print(json.dumps({'email':b['email'],'password':b['password'],'workspace':s['workspace']}))
elif action=='remove':
    q.call('remove active browser member','DELETE',p+'/members/'+b['id'],a)
elif action=='delete-shared':
    q.call('delete active shared workspace','DELETE',p,a)
elif action=='delete-home':
    b.update(q.call('login test home owner','POST','/auth/login',body={'email':b['email'],'password':b['password']}))
    q.call('delete last remaining workspace','DELETE','/tenants/'+str(b['active_tenant']['id']),b)
elif action=='revoke':
    b.update(q.call('login for revocation','POST','/auth/login',body={'email':b['email'],'password':b['password']}))
    q.call('revoke every member session','POST','/auth/logout',b,{})
elif action=='restore-two':
    b.update(q.call('login tenantless member','POST','/auth/login',body={'email':b['email'],'password':b['password']}))
    t=q.call('create final UI test workspace','POST','/tenants',b,{'name':s['run']+'_final'},(201,))['data']
    s['final_workspace']=t['id'];s['tenants'].append(t['id']);q.save(s)
    q.call('add final UI member to surviving workspace','POST',f"/tenants/{a['active_tenant']['id']}/members",a,{'email':b['email'],'role':'viewer'},(201,))
elif action=='delete-final':
    b.update(q.call('login final workspace owner','POST','/auth/login',body={'email':b['email'],'password':b['password']}))
    q.call('delete final active UI workspace','DELETE',f"/tenants/{s['final_workspace']}",b)
elif action=='invite-only':
    from urllib.parse import urlparse, parse_qs
    import secrets
    a.update(q.call('login fixture owner','POST','/auth/login',body={'email':a['email'],'password':a['password']}))
    tid=a['active_tenant']['id']
    link=q.call('create final-membership invite','POST',f'/tenants/{tid}/invite-links',a,{'role':'viewer'},(201,))['data']
    token=parse_qs(urlparse(link['invite_url']).query)['token'][0]
    email=s['run']+'.invited@example.invalid'; password=secrets.token_urlsafe(24)
    q.call('register account with only invited workspace','POST','/auth/register-by-invite',body={'token':token,'email':email,'username':s['run']+'_invited','password':password},expected=(200,201))
    d=q.call('login invited-only account','POST','/auth/login',body={'email':email,'password':password})
    d.update({'email':email,'password':password,'id':d['user']['id']})
    s['users']['invited']=d
    q.call('revoke fixture invite link','DELETE',f"/tenants/{tid}/invitations/{link['id']}",a)
    print(json.dumps({'email':email,'password':password}))
elif action=='remove-last':
    d=s['users']['invited'];tid=d['active_tenant']['id']
    q.call('remove last membership','DELETE',f"/tenants/{tid}/members/{d['id']}",a)
    r=q.call('refresh after last membership removed','POST','/auth/refresh',body={'refreshToken':d['refresh_token']})
    q.call('tenantless refreshed identity remains valid','GET','/auth/me',{'token':r['access_token']})
elif action=='cleanup':
    # Only UUIDs returned by fixture registration and its generated prefix.
    assert re.fullmatch(r'qa\d{10}',s['run'])
    ids=[u['id'] for u in s['users'].values()]
    assert all(re.fullmatch(r'[0-9a-f-]{36}',i) for i in ids)
    uid=','.join("'"+i+"'" for i in ids)
    tid=','.join(str(int(i)) for i in s['tenants'])
    sql=f"""BEGIN;
UPDATE auth_tokens SET is_revoked=true WHERE user_id IN ({uid});
UPDATE users SET is_active=false, deleted_at=NOW(), updated_at=NOW() WHERE id IN ({uid}) AND email LIKE '{s['run']}.%@example.invalid';
UPDATE tenant_members SET deleted_at=NOW() WHERE user_id IN ({uid}) AND tenant_id IN ({tid}) AND deleted_at IS NULL;
UPDATE tenants SET deleted_at=NOW() WHERE id IN ({tid}) AND deleted_at IS NULL;
COMMIT;
SELECT count(*) AS active_test_users FROM users WHERE id IN ({uid}) AND is_active;
SELECT count(*) AS active_test_workspaces FROM tenants WHERE id IN ({tid}) AND deleted_at IS NULL;
"""
    r=subprocess.run(['docker','exec','-i','WeKnora-postgres','sh','-c','psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'],input=sql,text=True,capture_output=True)
    print(r.stdout);assert r.returncode==0,r.stderr
    (q.OUT/'cleanup.txt').write_text(r.stdout,encoding='utf-8')
    q.STATE.unlink()
    sys.exit()
q.save(s)
