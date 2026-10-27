"""Run the existing multi-account suite against the recovery build, then clean fixtures."""
import json, tempfile
from pathlib import Path
import multi_account_live as q

q.OUT = Path(__file__).resolve().parents[1] / 'artifacts/session-recovery/regression'
q.OUT.mkdir(parents=True, exist_ok=True)
q.STATE = Path(tempfile.gettempdir()) / 'weknora-recovery-regression-state.json'
q.setup()
q.exercise()
q.extended()
s = json.loads(q.STATE.read_text())
q.call('add member for ownership regression', 'POST', f"/tenants/{s['workspace']}/members",
       s['users']['owner'], {'email': s['users']['member']['email'], 'role': 'contributor'}, (201,))
q.finish()
exec(Path(__file__).with_name('multi_account_cleanup.py').read_text(encoding='utf-8'))
assert all(r['pass'] for r in q.results), 'Regression failed; inspect results.json'
print(f'All {len(q.results)} assertions passed')
