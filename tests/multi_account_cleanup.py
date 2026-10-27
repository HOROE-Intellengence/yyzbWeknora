"""Disable only the disposable users recorded by multi_account_live.py."""
import json, re, subprocess
import multi_account_live as q
s=json.loads(q.STATE.read_text()); run=s['run']
assert re.fullmatch(r'qa\d{10}',run)
ids=[u['id'] for u in s['users'].values()]
assert all(re.fullmatch(r'[0-9a-f-]{36}',i) for i in ids)
uid=','.join("'"+i+"'" for i in ids)
tid=','.join(str(int(i)) for i in s['tenants'])
sql=f"""BEGIN;
UPDATE auth_tokens SET is_revoked=true WHERE user_id IN ({uid});
UPDATE users SET is_active=false, deleted_at=NOW(), updated_at=NOW() WHERE id IN ({uid}) AND email LIKE '{run}.%@example.invalid';
UPDATE tenant_members SET deleted_at=NOW() WHERE user_id IN ({uid}) AND tenant_id IN ({tid}) AND deleted_at IS NULL;
COMMIT;
SELECT 'active_test_users',count(*) FROM users WHERE id IN ({uid}) AND is_active=true;
SELECT 'active_test_workspaces',count(*) FROM tenants WHERE id IN ({tid}) AND deleted_at IS NULL;
SELECT 'active_test_memberships',count(*) FROM tenant_members WHERE tenant_id IN ({tid}) AND deleted_at IS NULL;
"""
r=subprocess.run(['docker','exec','-i','WeKnora-postgres','sh','-c','psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'],input=sql,text=True,capture_output=True)
print(r.stdout);print(r.stderr);assert r.returncode==0
(q.OUT/'cleanup.txt').write_text(r.stdout,encoding='utf-8')
manifest={'run':run,'accounts':[{'id':u['id'],'email':u['email']} for u in s['users'].values()],'workspaces':s['tenants'],'kb_ids':[s['kb'],s['member_kb']],'org_id':s['org'],'session_id':s['session'],'cleanup':'API deleted fixtures; test users disabled and soft deleted; membership rows soft deleted; auth tokens revoked; audit retained'}
(q.OUT/'fixtures.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
q.STATE.unlink()
