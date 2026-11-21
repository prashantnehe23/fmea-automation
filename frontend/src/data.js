// ── Organisation / hierarchy ──────────────────────────────────────────────────

export const ORG = { id: 'o1', name: 'All portfolios' };

export const HIERARCHY = [
  {
    id: 'p1', name: 'Payments Platform', projects: [
      { id: 'pr1', name: 'Payment Gateway API', components: [
        { id: 'c1', name: 'checkout_service.py', locked: true  },
        { id: 'c2', name: 'processor.py',         locked: true  },
      ]},
      { id: 'pr2', name: 'Billing Service', components: [
        { id: 'c3', name: 'invoice_engine.py',    locked: false },
      ]},
    ],
  },
  {
    id: 'p2', name: 'Identity & Access', projects: [
      { id: 'pr3', name: 'Auth Service', components: [
        { id: 'c4', name: 'auth/login.py',      locked: true  },
        { id: 'c5', name: 'auth/middleware.py', locked: false },
      ]},
    ],
  },
];

// ── Risk data ─────────────────────────────────────────────────────────────────

export const ALL_RISKS = [
  { id: 1, name: 'SQL Injection via login form',         s: 9, o: 7, d: 6, rpn: 378, priority: 'Critical', status: 'Open',        comp: 'checkout_service.py', project: 'pr1', portfolio: 'p1', owner: 'Dev Team',      impact: 'Full database compromise — GDPR breach exposure £2.1M' },
  { id: 2, name: 'Race condition in payment processing', s: 9, o: 5, d: 8, rpn: 360, priority: 'Critical', status: 'In Progress', comp: 'processor.py',         project: 'pr1', portfolio: 'p1', owner: 'Payments Team', impact: 'Duplicate charges, financial loss, audit failure' },
  { id: 3, name: 'Hardcoded API credentials exposure',   s: 8, o: 6, d: 5, rpn: 240, priority: 'High',     status: 'Open',        comp: 'invoice_engine.py',    project: 'pr2', portfolio: 'p1', owner: 'Dev Team',      impact: 'Third-party system breach via credential reuse' },
  { id: 4, name: 'JWT authentication bypass',            s: 8, o: 4, d: 7, rpn: 224, priority: 'High',     status: 'Reviewing',   comp: 'auth/login.py',        project: 'pr3', portfolio: 'p2', owner: 'Security Team', impact: 'Unauthorised access to any customer account' },
  { id: 5, name: 'Missing CSRF tokens on endpoints',     s: 6, o: 5, d: 5, rpn: 150, priority: 'Medium',   status: 'Open',        comp: 'auth/middleware.py',   project: 'pr3', portfolio: 'p2', owner: 'Dev Team',      impact: 'Account takeover via social engineering' },
  { id: 6, name: 'Insecure direct object reference',     s: 7, o: 4, d: 5, rpn: 140, priority: 'Medium',   status: 'Mitigated',   comp: 'auth/login.py',        project: 'pr3', portfolio: 'p2', owner: 'Dev Team',      impact: 'Cross-customer data leakage' },
  { id: 7, name: 'DoS via unvalidated file upload',      s: 6, o: 3, d: 6, rpn: 108, priority: 'Medium',   status: 'Open',        comp: 'checkout_service.py',  project: 'pr1', portfolio: 'p1', owner: 'Dev Team',      impact: 'Service outage, customer disruption' },
];

export const FIXES = {
  1: ['Use parameterised queries — SQLAlchemy ORM or cursor.execute with tuple params', 'Validate and sanitise all user-supplied input at controller layer', 'Enable WAF SQLi rules, alert on pattern matches'],
  2: ['Implement distributed locks via Redis SETNX with TTL', 'Add idempotency keys to all payment endpoints', 'Roll back and alert on duplicate detection within 5s window'],
  3: ['Move all credentials to AWS Secrets Manager or HashiCorp Vault', 'Rotate every exposed key immediately; revoke old ones', 'Add detect-secrets pre-commit hook to block credential commits'],
  4: ['Enforce RS256; reject HS256 and "none" algorithms at middleware', 'Implement token binding + short-lived access tokens (15 min TTL)', 'Anomaly detection on JWT claim changes per session'],
};

// ── Process steps ─────────────────────────────────────────────────────────────

export const PROCESS_STEPS = [
  { id: 'scan',        label: 'Context & Scan',    icon: '🔍', step: 1 },
  { id: 'scenarios',   label: 'Failure Scenarios', icon: '⚠️',  step: 2 },
  { id: 'scoring',     label: 'Risk Scoring',      icon: '📊', step: 3 },
  { id: 'mitigations', label: 'Mitigations',       icon: '🛠️', step: 4 },
  { id: 'remediation', label: 'Auto-Remediation',  icon: '🔧', step: 5 },
  { id: 'dashboard',   label: 'Dashboard',         icon: '📈', step: 6 },
];

// Which steps are "primary" (full opacity) vs "available" (muted) per persona
export const PERSONA_PRIMARY = {
  developer:         ['scan', 'scenarios', 'remediation'],
  risk_manager:      ['scenarios', 'scoring', 'mitigations', 'dashboard'],
  sre:               ['mitigations', 'remediation'],
  security_engineer: ['scenarios', 'scoring'],
  executive:         ['scoring', 'mitigations', 'dashboard'],
};

// ── Personas ──────────────────────────────────────────────────────────────────

export const PERSONAS = [
  { id: 'developer',         label: 'Developer',         icon: '💻', desc: 'Scan & analyse code'    },
  { id: 'risk_manager',      label: 'Risk Manager',      icon: '📊', desc: 'Manage & track risks'   },
  { id: 'sre',               label: 'SRE',               icon: '🛠️', desc: 'Remediate & mitigate'   },
  { id: 'security_engineer', label: 'Security Engineer', icon: '🔐', desc: 'Review & adjust scores' },
  { id: 'executive',         label: 'Executive',         icon: '📈', desc: 'Business risk overview' },
];

export const PERSONA_DEFAULT_SCOPE = {
  developer: 'component', risk_manager: 'project', sre: 'component',
  security_engineer: 'component', executive: 'portfolio',
};

export const PERSONA_SCOPE_OPTIONS = {
  developer:         ['component'],
  sre:               ['component', 'project'],
  security_engineer: ['component', 'project', 'portfolio'],
  risk_manager:      ['project', 'portfolio', 'org'],
  executive:         ['portfolio', 'org'],
};

export const SCOPE_LABEL = {
  component: 'Component', project: 'Project', portfolio: 'Portfolio', org: 'Organisation',
};
